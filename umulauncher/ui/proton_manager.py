"""Dialog to inspect, download and remove Proton builds."""

from __future__ import annotations

import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..core import prefixes, proton_releases, protons  # noqa: E402
from ..core.i18n import _  # noqa: E402
from .format import short_path  # noqa: E402


class ProtonManagerDialog(Adw.Dialog):
    def __init__(self, app, on_changed=None) -> None:
        super().__init__()
        self.app = app
        self.on_changed = on_changed
        self._cancel: threading.Event | None = None
        self._source_results: list[
            tuple[proton_releases.ProtonSource, list[proton_releases.ProtonRelease], str]
        ] = []
        self._available_loaded = False
        self._installed_names: set[str] = set()
        self._download_buttons: list[Gtk.Widget] = []
        self._installed_rows: list[Gtk.Widget] = []

        self.set_title(_("Proton builds"))
        self.set_content_width(760)
        self.set_content_height(720)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_button.set_tooltip_text(_("Refresh"))
        refresh_button.connect("clicked", lambda _b: self._reload())
        header.pack_end(refresh_button)
        toolbar.add_top_bar(header)

        self.page = Adw.PreferencesPage()

        self.download_group = Adw.PreferencesGroup()
        self.download_group.set_visible(False)
        self.download_row = Adw.ActionRow()
        self.download_progress = Gtk.ProgressBar()
        self.download_progress.set_size_request(220, -1)
        self.download_progress.set_valign(Gtk.Align.CENTER)
        self.download_row.add_suffix(self.download_progress)

        self.cancel_button = Gtk.Button(icon_name="process-stop-symbolic")
        self.cancel_button.set_valign(Gtk.Align.CENTER)
        self.cancel_button.set_tooltip_text(_("Cancel"))
        self.cancel_button.connect("clicked", self._on_cancel)
        self.download_row.add_suffix(self.cancel_button)
        self.download_group.add(self.download_row)
        self.page.add(self.download_group)

        self.installed_group = Adw.PreferencesGroup(title=_("Installed"))
        self.page.add(self.installed_group)

        self._source_groups: dict[str, Adw.PreferencesGroup] = {}
        self._source_rows: dict[str, list[Gtk.Widget]] = {}
        for source in proton_releases.SOURCES:
            group = Adw.PreferencesGroup(title=source.label)
            self.page.add(group)
            self._source_groups[source.label] = group
            self._source_rows[source.label] = []

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.page)
        toolbar.set_content(scroller)
        self.set_child(toolbar)

        self.connect("closed", self._on_closed)
        self._reload()

    # ------------------------------------------------------------- loading
    def _reload(self) -> None:
        self._load_installed()
        self._load_available()

    def _load_installed(self) -> None:
        _clear_rows(self.installed_group, self._installed_rows)
        builds = protons.installed(include_incomplete=True)
        self._installed_names = {build.name for build in builds}

        if not builds:
            row = Adw.ActionRow(title=_("No Proton builds installed"))
            row.add_css_class("dim-label")
            self.installed_group.add(row)
            self._installed_rows.append(row)
            return

        for build in builds:
            row = Adw.ActionRow(title=build.name, subtitle=short_path(build.path, 64))
            row.set_tooltip_text(build.path)

            size_label = Gtk.Label(label="…")
            size_label.add_css_class("dim-label")
            size_label.set_valign(Gtk.Align.CENTER)
            row.add_suffix(size_label)
            self._load_size(build.path, size_label)

            if protons.is_removable(build.path):
                delete_button = Gtk.Button(icon_name="user-trash-symbolic")
                delete_button.add_css_class("flat")
                delete_button.set_valign(Gtk.Align.CENTER)
                delete_button.set_tooltip_text(_("Delete"))
                delete_button.connect("clicked", lambda _b, b=build: self._on_delete(b))
                row.add_suffix(delete_button)

            self.installed_group.add(row)
            self._installed_rows.append(row)

    def _load_size(self, path: str, label: Gtk.Label) -> None:
        def work() -> None:
            size = prefixes.size_bytes(path)
            GLib.idle_add(self._size_ready, label, prefixes.human_size(size))

        threading.Thread(target=work, name="proton-size", daemon=True).start()

    def _size_ready(self, label: Gtk.Label, text: str) -> bool:
        label.set_label(text)
        return False

    def _load_available(self) -> None:
        self._available_loaded = False
        self._source_results = []
        self._download_buttons.clear()

        for source in proton_releases.SOURCES:
            group = self._source_groups[source.label]
            rows = self._source_rows[source.label]
            _clear_rows(group, rows)

            row = Adw.ActionRow(title=_("Loading Proton releases…"))
            spinner = Gtk.Spinner()
            spinner.set_valign(Gtk.Align.CENTER)
            spinner.start()
            row.add_suffix(spinner)
            group.add(row)
            rows.append(row)

        def work() -> None:
            try:
                results = proton_releases.fetch_by_source()
            except Exception as exc:  # noqa: BLE001 - report any network failure
                results = [
                    (source, [], str(exc)) for source in proton_releases.SOURCES
                ]
            GLib.idle_add(self._apply_releases, results)

        threading.Thread(target=work, name="proton-releases", daemon=True).start()

    def _apply_releases(
        self,
        results: list[
            tuple[proton_releases.ProtonSource, list[proton_releases.ProtonRelease], str]
        ],
    ) -> bool:
        self._source_results = results
        self._available_loaded = True
        self._render_available()
        return False

    def _render_available(self) -> None:
        if not self._available_loaded:
            return
        self._download_buttons.clear()

        for source, releases, error in self._source_results:
            group = self._source_groups[source.label]
            rows = self._source_rows[source.label]
            _clear_rows(group, rows)

            if error:
                row = Adw.ActionRow(
                    title=_("Could not load the release list"),
                    subtitle=error,
                )
                row.add_css_class("dim-label")
                group.add(row)
                rows.append(row)
                continue

            if not releases:
                row = Adw.ActionRow(title=_("No releases found"))
                row.add_css_class("dim-label")
                group.add(row)
                rows.append(row)
                continue

            for release in releases:
                published = release.published[:10]
                bits = [prefixes.human_size(release.size)]
                if published:
                    bits.append(published)
                row = Adw.ActionRow(
                    title=release.name,
                    subtitle=" · ".join(part for part in bits if part),
                )

                if release.name in self._installed_names:
                    installed_label = Gtk.Label(label=_("Installed"))
                    installed_label.add_css_class("dim-label")
                    installed_label.set_valign(Gtk.Align.CENTER)
                    row.add_suffix(installed_label)
                else:
                    download_button = Gtk.Button(icon_name="folder-download-symbolic")
                    download_button.set_valign(Gtk.Align.CENTER)
                    download_button.set_tooltip_text(_("Download"))
                    download_button.connect(
                        "clicked", lambda _b, r=release: self._start_download(r)
                    )
                    row.add_suffix(download_button)
                    self._download_buttons.append(download_button)

                group.add(row)
                rows.append(row)

    # ------------------------------------------------------------ download
    def _start_download(self, release: proton_releases.ProtonRelease) -> None:
        if self._cancel is not None:
            self.app.toast(_("Another Proton download is already running"))
            return

        cancel = threading.Event()
        self._cancel = cancel
        self._set_download_buttons_sensitive(False)
        self.download_group.set_visible(True)
        self.download_row.set_title(_("Downloading %s…") % release.name)
        self.download_row.set_subtitle("")
        self.download_progress.set_fraction(0.0)
        self.cancel_button.set_sensitive(True)

        last_update = [0.0]

        def on_progress(done: int, total: int) -> None:
            now = time.monotonic()
            if now - last_update[0] < 0.15 and total and done < total:
                return
            last_update[0] = now
            GLib.idle_add(self._progress_ready, done, total)

        def work() -> None:
            try:
                path = proton_releases.download_install(
                    release,
                    on_progress=on_progress,
                    cancel=cancel,
                )
                GLib.idle_add(self._download_finished, release, str(path), "")
            except proton_releases.DownloadCancelled:
                GLib.idle_add(self._download_finished, release, "", "cancelled")
            except Exception as exc:  # noqa: BLE001 - show the failure to the user
                GLib.idle_add(self._download_finished, release, "", str(exc))

        threading.Thread(target=work, name="proton-download", daemon=True).start()

    def _progress_ready(self, done: int, total: int) -> bool:
        if total > 0:
            self.download_progress.set_fraction(min(1.0, done / total))
            total_text = prefixes.human_size(total)
        else:
            self.download_progress.pulse()
            total_text = "?"
        self.download_row.set_subtitle(f"{prefixes.human_size(done)} / {total_text}")
        return False

    def _on_cancel(self, _button) -> None:
        if self._cancel is not None:
            self._cancel.set()
            self.cancel_button.set_sensitive(False)
            self.download_row.set_subtitle(_("Cancelling…"))

    def _download_finished(
        self,
        release: proton_releases.ProtonRelease,
        path: str,
        error: str,
    ) -> bool:
        self._cancel = None
        self.download_group.set_visible(False)
        self._set_download_buttons_sensitive(True)

        if error == "cancelled":
            self.app.toast(_("Download cancelled"))
            return False
        if error:
            self.app.toast(_("Download failed: %s") % error)
            return False

        self.app.toast(_("Proton installed: %s") % release.name)
        self._load_installed()
        self._render_available()
        if self.on_changed is not None:
            self.on_changed()
        return False

    def _set_download_buttons_sensitive(self, sensitive: bool) -> None:
        for button in self._download_buttons:
            button.set_sensitive(sensitive)

    # -------------------------------------------------------------- delete
    def _on_delete(self, build: protons.ProtonBuild) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Delete %s?") % build.name,
            body=_("The build will be removed from disk. Games using it will need another Proton."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "delete":
                self._delete_build(build)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _delete_build(self, build: protons.ProtonBuild) -> None:
        def work() -> None:
            try:
                protons.remove_build(build.path)
                error = ""
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
            GLib.idle_add(self._deleted, build.name, error)

        threading.Thread(target=work, name="proton-delete", daemon=True).start()

    def _deleted(self, name: str, error: str) -> bool:
        if error:
            self.app.toast(_("Could not delete %s: %s") % (name, error))
        else:
            self.app.toast(_("Proton build deleted: %s") % name)
        self._load_installed()
        self._render_available()
        if self.on_changed is not None:
            self.on_changed()
        return False

    def _on_closed(self, *_args) -> None:
        if self._cancel is not None:
            self._cancel.set()


def _clear_rows(group: Adw.PreferencesGroup, rows: list[Gtk.Widget]) -> None:
    for row in rows:
        group.remove(row)
    rows.clear()
