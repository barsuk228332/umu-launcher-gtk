"""Dialogs: environment editor, umu-database search, settings, confirmations."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk, Pango  # noqa: E402

from ..core import config, covers, umudb  # noqa: E402
from ..core.i18n import _  # noqa: E402
from .common import LANGUAGES, proton_options  # noqa: E402


def parse_env(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse KEY=VALUE lines, returning (env, errors)."""
    env: dict[str, str] = {}
    errors: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            errors.append(_("line %d: expected KEY=VALUE") % number)
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in ("'", '"') and len(value) >= 2:
            value = value[1:-1]
        if not key or not all(ch.isalnum() or ch == "_" for ch in key) or key[0].isdigit():
            errors.append(_("line %d: invalid variable name") % number)
            continue
        env[key] = value
    return env, errors


def format_env(env: dict[str, str]) -> str:
    return "".join(f"{key}={value}\n" for key, value in sorted(env.items()))


class EnvDialog(Adw.Dialog):
    def __init__(self, env: dict[str, str], on_apply: Callable[[dict[str, str]], None]) -> None:
        super().__init__()
        self.on_apply = on_apply
        self.set_title(_("Environment variables"))
        self.set_content_width(620)
        self.set_content_height(460)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        save_button = Gtk.Button(label=_("Save"))
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", self._on_save)
        header.pack_end(save_button)
        toolbar.add_top_bar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        hint = Gtk.Label(
            label=_("One KEY=VALUE pair per line. Lines starting with # are ignored."),
            xalign=0,
            wrap=True,
        )
        hint.add_css_class("dim-label")
        box.append(hint)

        self.error_label = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.error_label.add_css_class("error")
        box.append(self.error_label)

        self.text_view = Gtk.TextView()
        self.text_view.set_monospace(True)
        self.text_view.set_left_margin(8)
        self.text_view.set_right_margin(8)
        self.text_view.set_top_margin(8)
        self.text_view.set_bottom_margin(8)
        self.text_view.get_buffer().set_text(format_env(env))

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_has_frame(True)
        scroller.set_child(self.text_view)
        box.append(scroller)

        toolbar.set_content(box)
        self.set_child(toolbar)

    def _on_save(self, _button) -> None:
        buffer = self.text_view.get_buffer()
        start, end = buffer.get_bounds()
        text = buffer.get_text(start, end, True)
        env, errors = parse_env(text)
        if errors:
            self.error_label.set_label("\n".join(errors))
            self.error_label.set_visible(True)
            return
        self.on_apply(env)
        self.close()


class UmuIdDialog(Adw.Dialog):
    """Search the umu-database by title to pick a GAMEID."""

    def __init__(self, query: str, on_select: Callable[[umudb.UmuEntry], None]) -> None:
        super().__init__()
        self.on_select = on_select
        self.entries: list[umudb.UmuEntry] = []
        self.set_title(_("Find a GAMEID"))
        self.set_content_width(620)
        self.set_content_height(560)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(_("Game title"))
        self.search_entry.set_text(query)
        self.search_entry.connect("search-changed", self._on_search)
        box.append(self.search_entry)

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.add_css_class("dim-label")
        box.append(self.status)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")
        self.list_box.connect("row-activated", self._on_row_activated)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.list_box)
        box.append(scroller)

        toolbar.set_content(box)
        self.set_child(toolbar)

        self._load_database()
        if query:
            GLib.idle_add(lambda: self._on_search(self.search_entry) or False)

    def _load_database(self) -> None:
        self.status.set_label(_("Loading umu-database…"))

        def work() -> None:
            entries = umudb.load()
            if not entries:
                umudb.update()
                entries = umudb.load()
            GLib.idle_add(self._apply_entries, entries)

        threading.Thread(target=work, name="umu-db", daemon=True).start()

    def _apply_entries(self, entries: list[umudb.UmuEntry]) -> bool:
        self.entries = entries
        if not entries:
            self.status.set_label(
                _("umu-database is empty. Open Settings and press “Update umu-database”.")
            )
        else:
            self.status.set_label(_("%d games in the database") % len(entries))
            self._on_search(self.search_entry)
        return False

    def _on_search(self, entry: Gtk.SearchEntry) -> None:
        if not self.entries:
            return
        results = umudb.search(entry.get_text(), self.entries, limit=40)
        while (row := self.list_box.get_first_child()) is not None:
            self.list_box.remove(row)
        if not results:
            self.status.set_label(_("Nothing found"))
            return
        self.status.set_label(_("%d matches") % len(results))
        for item in results:
            row = Adw.ActionRow(title=item.title, subtitle=f"{item.store or 'none'} · {item.umu_id}")
            row.set_activatable(True)
            row.item = item
            self.list_box.append(row)

    def _on_row_activated(self, _list_box, row: Adw.ActionRow) -> None:
        item = getattr(row, "item", None)
        if item is not None:
            self.on_select(item)
            self.close()


class SettingsDialog(Adw.PreferencesDialog):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.settings = app.settings
        self._loading = True
        self.set_title(_("Settings"))

        page = Adw.PreferencesPage()
        self.set_content_width(640)
        self.set_content_height(720)

        appearance = Adw.PreferencesGroup(title=_("Appearance"))
        page.add(appearance)

        self.language_row = Adw.ComboRow(title=_("Interface language"))
        self.language_row.set_model(
            Gtk.StringList.new([label for _value, label in LANGUAGES])
        )
        values = [value for value, _label in LANGUAGES]
        self.language_row.set_selected(
            values.index(self.settings.language) if self.settings.language in values else 0
        )
        self.language_row.connect("notify::selected", self._on_language_changed)
        appearance.add(self.language_row)

        runtime = Adw.PreferencesGroup(
            title=_("Runtime"),
            description=_("Defaults applied when a game does not override them."),
        )
        page.add(runtime)

        self.proton_row = Adw.ComboRow(title=_("Default Proton"))
        labels, values = proton_options()
        self.proton_row.set_model(Gtk.StringList.new(labels))
        self.proton_row.set_subtitle(_("Used for new games and prefix creation"))
        current = self.settings.default_proton or ""
        self.proton_row.set_selected(values.index(current) if current in values else 0)
        self.proton_row.connect("notify::selected", self._on_proton_changed)
        runtime.add(self.proton_row)
        self._proton_values = values

        self.prefix_row = Adw.EntryRow(title=_("Prefix directory"))
        self.prefix_row.set_text(self.settings.prefix_root)
        self.prefix_row.connect("apply", self._on_prefix_apply)
        runtime.add(self.prefix_row)

        self.debug_row = Adw.SwitchRow(
            title=_("Debug logs"),
            subtitle=_("Set UMU_LOG=1 and keep verbose output in the log window"),
        )
        self.debug_row.set_active(self.settings.debug_logs)
        self.debug_row.connect("notify::active", self._on_debug_changed)
        runtime.add(self.debug_row)

        artwork = Adw.PreferencesGroup(
            title=_("Cover art"),
            description=_("SteamGridDB needs a free API key from steamgriddb.com/profile/preferences/api"),
        )
        page.add(artwork)

        self.key_row = Adw.PasswordEntryRow(title=_("SteamGridDB API key"))
        self.key_row.set_text(self.settings.sgdb_key)
        self.key_row.connect("changed", self._on_key_changed)
        artwork.add(self.key_row)
        self.cdn_row = Adw.SwitchRow(
            title=_("Steam CDN fallback"),
            subtitle=_("Download free square covers when SteamGridDB finds nothing"),
        )
        self.cdn_row.set_active(self.settings.steam_cdn_fallback)
        self.cdn_row.connect("notify::active", self._on_cdn_changed)
        artwork.add(self.cdn_row)

        database = Adw.PreferencesGroup(title=_("umu-database"))
        page.add(database)

        self.db_row = Adw.ActionRow(
            title=_("Update umu-database"),
            subtitle=_("Used to suggest GAMEID values for protonfixes"),
        )
        update_button = Gtk.Button(label=_("Update"))
        update_button.set_valign(Gtk.Align.CENTER)
        update_button.connect("clicked", self._on_update_db)
        self.db_row.add_suffix(update_button)
        database.add(self.db_row)

        about = Adw.PreferencesGroup(title=_("About"))
        page.add(about)
        about_row = Adw.ActionRow(
            title="umulauncher",
            subtitle=_("A GTK4 frontend for umu-launcher. Version %s") % app.version,
        )
        about.add(about_row)
        folder_button = Gtk.Button(icon_name="folder-open-symbolic")
        folder_button.set_valign(Gtk.Align.CENTER)
        folder_button.set_tooltip_text(_("Open data folder"))
        folder_button.connect("clicked", lambda _b: self._open_data_dir())
        about_row.add_suffix(folder_button)

        self.add(page)
        self.connect("closed", self._on_closed)
        self._loading = False

    def _on_closed(self, *_args) -> None:
        if self._loading:
            return
        root = self.prefix_row.get_text().strip()
        if root:
            self.settings.prefix_root = root
        self.settings.sgdb_key = self.key_row.get_text().strip()
        self._save()

    def _save(self) -> None:
        if self._loading:
            return
        config.save(self.settings)
        self.app.settings = self.settings

    def _on_language_changed(self, row: Adw.ComboRow, _param) -> None:
        if self._loading:
            return
        self.settings.language = LANGUAGES[row.get_selected()][0]
        self._save()
        self.app.toast(_("Restart umulauncher to apply the language"))

    def _on_proton_changed(self, row: Adw.ComboRow, _param) -> None:
        if self._loading:
            return
        index = row.get_selected()
        self.settings.default_proton = self._proton_values[index] if 0 <= index < len(self._proton_values) else ""
        self._save()

    def _on_prefix_changed(self, row: Adw.EntryRow) -> None:
        if self._loading:
            return
        value = row.get_text().strip()
        if value:
            self.settings.prefix_root = value

    def _on_prefix_apply(self, row: Adw.EntryRow) -> None:
        self._on_prefix_changed(row)
        self._save()

    def _on_debug_changed(self, row: Adw.SwitchRow, _param) -> None:
        if self._loading:
            return
        self.settings.debug_logs = row.get_active()
        self._save()

    def _on_cdn_changed(self, row: Adw.SwitchRow, _param) -> None:
        if self._loading:
            return
        self.settings.steam_cdn_fallback = row.get_active()
        self._save()

    def _on_key_changed(self, row: Adw.PasswordEntryRow) -> None:
        if self._loading:
            return
        self.settings.sgdb_key = row.get_text().strip()

    def _on_update_db(self, _button) -> None:
        self.db_row.set_subtitle(_("Updating…"))

        def work() -> None:
            changed = umudb.update(force=True)
            entries = umudb.load()
            if not changed:
                message = _("Update failed")
            else:
                message = _("%d records downloaded") % len(entries)
            GLib.idle_add(self._db_updated, message)

        threading.Thread(target=work, name="umu-db-update", daemon=True).start()

    def _db_updated(self, message: str) -> bool:
        self.db_row.set_subtitle(message)
        return False

    def _open_data_dir(self) -> None:
        import subprocess

        subprocess.Popen(["xdg-open", str(config.DATA_DIR)], start_new_session=True)


def choose_file(
    parent: Gtk.Window,
    title: str,
    patterns: list[str],
    on_chosen: Callable[[Path], None],
) -> None:
    dialog = Gtk.FileDialog()
    dialog.set_title(title)

    file_filter = Gtk.FileFilter()
    file_filter.set_name(_("Supported files"))
    for pattern in patterns:
        file_filter.add_pattern(pattern)
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(file_filter)
    dialog.set_filters(filters)
    dialog.set_default_filter(file_filter)

    def on_done(source: Gtk.FileDialog, result) -> None:
        try:
            file = source.open_finish(result)
        except GLib.Error:
            return
        if file is not None and file.get_path():
            on_chosen(Path(file.get_path()))

    dialog.open(parent, None, on_done)


def confirm(
    parent: Gtk.Window,
    heading: str,
    body: str,
    action_label: str,
    on_confirm: Callable[[], None],
    destructive: bool = False,
) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("confirm", action_label)
    if destructive:
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
    else:
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
        if response == "confirm":
            on_confirm()

    dialog.connect("response", on_response)
    dialog.present(parent)


def cover_dialog(
    parent: Gtk.Window,
    game_row_id: int,
    title: str,
    settings: config.Settings,
    on_done: Callable[[str | None], None],
) -> None:
    """Fetch a cover in a worker thread and report the stored path."""
    dialog = Adw.AlertDialog(
        heading=_("Download cover art"),
        body=_("Looking for “%s” on SteamGridDB…") % title,
    )
    dialog.add_response("close", _("Close"))
    dialog.present(parent)

    def work() -> None:
        path = None
        try:
            path = covers.fetch_cover(
                title,
                game_row_id,
                key=settings.sgdb_key,
                allow_cdn=settings.steam_cdn_fallback,
            )
        except Exception:
            path = None
        GLib.idle_add(finish, path)

    def finish(path) -> bool:
        dialog.close()
        on_done(str(path) if path else None)
        return False

    threading.Thread(target=work, name="cover", daemon=True).start()
