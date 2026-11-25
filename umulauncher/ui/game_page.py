"""Per-game page: launch, prefix, metadata and extra options."""

from __future__ import annotations

import shlex
import threading
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk, Pango  # noqa: E402

from ..core import config, db, desktop, prefixes  # noqa: E402
from ..core.db import Game  # noqa: E402
from ..core.i18n import _  # noqa: E402
from .common import FPS_CHOICES, RESOLUTIONS, open_folder, proton_options, store_options  # noqa: E402
from .dialogs import (  # noqa: E402
    EnvDialog,
    UmuIdDialog,
    choose_file,
    confirm,
    cover_dialog,
)
from .format import format_playtime, short_path  # noqa: E402
from .logs import LogWindow  # noqa: E402
from .widgets import CoverView, StatusPill  # noqa: E402


class GamePage(Adw.NavigationPage):
    def __init__(self, window, game: Game) -> None:
        super().__init__(title=game.title)
        self.window = window
        self.app = window.app
        self.game = game
        self._loading = True
        self._log_lines: list[str] = []
        self.log_window: LogWindow | None = None

        self.toolbar = Adw.ToolbarView()
        self.header = Adw.HeaderBar()

        menu = self._build_menu_button()
        self.header.pack_end(menu)

        self.toolbar.add_top_bar(self.header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_margin_top(24)
        box.set_margin_bottom(32)
        box.set_margin_start(18)
        box.set_margin_end(18)

        box.append(self._build_hero())
        self.run_group = self._build_run_group()
        box.append(self.run_group)
        self.prefix_group = self._build_prefix_group()
        box.append(self.prefix_group)
        self.art_group = self._build_art_group()
        box.append(self.art_group)
        self.extras_group = self._build_extras_group()
        box.append(self.extras_group)
        box.append(self._build_danger_group())

        clamp = Adw.Clamp()
        clamp.set_maximum_size(820)
        clamp.set_tightening_threshold(700)
        clamp.set_child(box)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(clamp)
        self.toolbar.set_content(scroller)

        self.set_child(self.toolbar)

        self.connect("shown", lambda *_: self._sync_running_state())
        self._loading = False
        self._sync_field_state()
        self._refresh_prefix_size()

    # ---------------------------------------------------------------- hero
    def _build_hero(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)

        self.cover = CoverView(168, 252)
        self.cover.set_cover(self.game.cover_path or None, self.game.title)
        row.append(self.cover)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        info.set_hexpand(True)
        info.set_valign(Gtk.Align.START)

        self.title_label = Gtk.Label(label=self.game.title, xalign=0, wrap=True)
        self.title_label.add_css_class("title-1")
        info.append(self.title_label)

        self.exe_label = Gtk.Label(
            label=short_path(self.game.exe_path, 70), xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE
        )
        self.exe_label.add_css_class("dim-label")
        info.append(self.exe_label)

        meta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.status_pill = StatusPill()
        meta.append(self.status_pill)
        self.playtime_label = Gtk.Label(label=format_playtime(self.game.playtime_sec), xalign=0)
        self.playtime_label.add_css_class("dim-label")
        meta.append(self.playtime_label)
        info.append(meta)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_margin_top(8)
        self.play_button = Gtk.Button(label=_("Play"))
        self.play_button.add_css_class("suggested-action")
        self.play_button.add_css_class("pill")
        self.play_button.set_icon_name("media-playback-start-symbolic")
        self.play_button.connect("clicked", self._on_play)
        buttons.append(self.play_button)

        self.stop_button = Gtk.Button(label=_("Stop"))
        self.stop_button.add_css_class("destructive-action")
        self.stop_button.add_css_class("pill")
        self.stop_button.set_icon_name("media-playback-stop-symbolic")
        self.stop_button.set_visible(False)
        self.stop_button.connect("clicked", self._on_stop)
        buttons.append(self.stop_button)

        log_button = Gtk.Button(label=_("Logs"))
        log_button.set_icon_name("utilities-terminal-symbolic")
        log_button.connect("clicked", lambda _b: self._open_logs())
        buttons.append(log_button)

        shortcut_button = Gtk.Button(icon_name="starred-symbolic")
        shortcut_button.set_tooltip_text(_("Export a .desktop shortcut"))
        shortcut_button.connect("clicked", self._on_export_shortcut)
        buttons.append(shortcut_button)

        info.append(buttons)
        row.append(info)
        return row

    # ----------------------------------------------------------- run group
    def _build_run_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=_("Launch"))

        self.proton_row = Adw.ComboRow(title=_("Proton"))
        labels, values = proton_options()
        self._proton_values = values
        self.proton_row.set_model(Gtk.StringList.new(labels))
        selected = values.index(self.game.proton_path) if self.game.proton_path in values else 0
        self.proton_row.set_selected(selected)
        self.proton_row.connect("notify::selected", self._on_proton_changed)
        group.add(self.proton_row)

        self.store_row = Adw.ComboRow(title=_("Store"))
        store_labels, store_values = store_options()
        self._store_values = store_values
        self.store_row.set_model(Gtk.StringList.new(store_labels))
        store_index = store_values.index(self.game.store) if self.game.store in store_values else 0
        self.store_row.set_selected(store_index)
        self.store_row.connect("notify::selected", self._on_store_changed)
        group.add(self.store_row)

        self.game_id_row = Adw.EntryRow(title=_("GAMEID (protonfixes)"))
        self.game_id_row.set_text(self.game.game_id or "umu-default")
        self.game_id_row.connect("changed", self._on_game_id_changed)
        find_button = Gtk.Button(icon_name="system-search-symbolic")
        find_button.set_valign(Gtk.Align.CENTER)
        find_button.set_tooltip_text(_("Search umu-database"))
        find_button.connect("clicked", self._on_find_game_id)
        self.game_id_row.add_suffix(find_button)
        group.add(self.game_id_row)

        self.args_row = Adw.EntryRow(title=_("Launch arguments"))
        self.args_row.set_text(shlex.join(self.game.launch_args))
        self.args_row.connect("changed", self._on_args_changed)
        group.add(self.args_row)

        return group

    # -------------------------------------------------------- prefix group
    def _build_prefix_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title=_("Wine prefix"),
            description=_("Each game should use its own prefix. Windows installers and registry live here."),
        )

        self.prefix_row = Adw.ActionRow(title=_("Prefix folder"))
        self.prefix_row.set_subtitle(short_path(self._prefix_path, 60))
        self.prefix_row.set_tooltip_text(self._prefix_path)

        create_button = suffix_button("folder-new-symbolic", _("Create prefix"), self._on_create_prefix)
        open_button = suffix_button("folder-open-symbolic", _("Open in file manager"), self._on_open_prefix)
        delete_button = suffix_button("user-trash-symbolic", _("Delete prefix"), self._on_delete_prefix)
        for button in (create_button, open_button, delete_button):
            self.prefix_row.add_suffix(button)

        group.add(self.prefix_row)

        self.prefix_info_row = Adw.ActionRow(title=_("Size on disk"))
        self.prefix_info_row.set_subtitle("…")
        group.add(self.prefix_info_row)

        self.env_row = Adw.ActionRow(title=_("Environment variables"))
        self.env_row.set_subtitle(self._env_summary())
        env_button = Gtk.Button(label=_("Edit"))
        env_button.set_valign(Gtk.Align.CENTER)
        env_button.connect("clicked", self._on_edit_env)
        self.env_row.add_suffix(env_button)
        group.add(self.env_row)

        return group

    def _env_summary(self) -> str:
        count = len(self.game.env)
        if not count:
            return _("none")
        keys = ", ".join(sorted(self.game.env)[:3])
        return f"{keys}{'…' if count > 3 else ''}"

    # -------------------------------------------------------- artwork group
    def _build_art_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=_("Cover art"))

        self.cover_row = Adw.ActionRow(title=_("Cover"))
        self.cover_row.set_subtitle(
            Path(self.game.cover_path).name if self.game.cover_path else _("placeholder")
        )
        download_button = Gtk.Button(label=_("Download"))
        download_button.set_valign(Gtk.Align.CENTER)
        download_button.connect("clicked", self._on_download_cover)
        self.cover_row.add_suffix(download_button)

        choose_button = Gtk.Button(icon_name="document-open-symbolic")
        choose_button.set_valign(Gtk.Align.CENTER)
        choose_button.set_tooltip_text(_("Choose a local image"))
        choose_button.connect("clicked", self._on_choose_cover)
        self.cover_row.add_suffix(choose_button)

        group.add(self.cover_row)
        return group

    # --------------------------------------------------------- extras group
    def _build_extras_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=_("Extra options"))

        self.gamescope_row = Adw.ExpanderRow(title="gamescope")
        self.gamescope_row.set_subtitle(_("Run the game inside the gamescope compositor"))
        self.gamescope_row.set_show_enable_switch(True)
        gs = self._gamescope()
        self.gamescope_row.set_enable_expansion(bool(gs.get("enabled")))
        self.gamescope_row.connect("notify::enable-expansion", self._on_gamescope_toggled)

        self.resolution_row = Adw.ComboRow(title=_("Resolution"))
        self.resolution_row.set_model(Gtk.StringList.new([f"{w} × {h}" for w, h in RESOLUTIONS]))
        index = 2
        for position, (width, height) in enumerate(RESOLUTIONS):
            if width == gs.get("width") and height == gs.get("height"):
                index = position
                break
        self.resolution_row.set_selected(index)
        self.resolution_row.connect("notify::selected", self._on_resolution_changed)
        self.gamescope_row.add_row(self.resolution_row)

        self.fps_row = Adw.ComboRow(title=_("Frame limit"))
        self.fps_row.set_model(Gtk.StringList.new([_("Unlimited")] + [str(value) for value in FPS_CHOICES[1:]]))
        fps = int(gs.get("fps") or 0)
        self.fps_row.set_selected(FPS_CHOICES.index(fps) if fps in FPS_CHOICES else 0)
        self.fps_row.connect("notify::selected", self._on_fps_changed)
        self.gamescope_row.add_row(self.fps_row)

        self.fullscreen_row = Adw.SwitchRow(title=_("Fullscreen"))
        self.fullscreen_row.set_active(bool(gs.get("fullscreen", True)))
        self.fullscreen_row.connect("notify::active", self._on_fullscreen_changed)
        self.gamescope_row.add_row(self.fullscreen_row)

        self.gs_extra_row = Adw.EntryRow(title=_("Extra gamescope flags"))
        self.gs_extra_row.set_text(" ".join(gs.get("extra") or []))
        self.gs_extra_row.connect("changed", self._on_gs_extra_changed)
        self.gamescope_row.add_row(self.gs_extra_row)
        group.add(self.gamescope_row)

        self.mangohud_row = Adw.SwitchRow(
            title="MangoHud",
            subtitle=_("Set MANGOHUD=1 for this game"),
        )
        self.mangohud_row.set_active(self.game.mangohud)
        self.mangohud_row.connect("notify::active", self._on_mangohud_toggled)
        group.add(self.mangohud_row)

        winetricks_row = Adw.ActionRow(
            title="Winetricks",
            subtitle=_("Install components into the prefix (requires GE-Proton or UMU-Proton)"),
        )
        winetricks_button = Gtk.Button(label=_("Run…"))
        winetricks_button.set_valign(Gtk.Align.CENTER)
        winetricks_button.connect("clicked", self._on_winetricks)
        winetricks_row.add_suffix(winetricks_button)
        group.add(winetricks_row)

        self.export_row = Adw.ActionRow(
            title=_("Menu shortcut"),
            subtitle=_("Add this game to the KDE/GNOME application menu"),
        )
        export_button = Gtk.Button(label=_("Export"))
        export_button.set_valign(Gtk.Align.CENTER)
        export_button.connect("clicked", self._on_export_shortcut)
        self.export_row.add_suffix(export_button)
        group.add(self.export_row)

        return group

    def _build_danger_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=_("Danger zone"))
        row = Adw.ActionRow(
            title=_("Remove from library"),
            subtitle=_("The prefix and game files are kept on disk"),
        )
        remove_button = Gtk.Button(label=_("Remove"))
        remove_button.add_css_class("destructive-action")
        remove_button.set_valign(Gtk.Align.CENTER)
        remove_button.connect("clicked", self._on_delete_game)
        row.add_suffix(remove_button)
        group.add(row)
        return group

    # ------------------------------------------------------------- helpers
    def _build_menu_button(self) -> Gtk.MenuButton:
        button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        button.set_tooltip_text(_("Menu"))
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        logs_button = Gtk.Button(label=_("Show log folder"))
        logs_button.add_css_class("flat")
        logs_button.connect("clicked", lambda _b: open_folder(str(config.LOGS_DIR)))
        box.append(logs_button)

        settings_button = Gtk.Button(label=_("Settings"))
        settings_button.add_css_class("flat")
        settings_button.connect(
            "clicked", lambda _b: (popover.popdown(), self.app.show_settings(self.window))
        )
        box.append(settings_button)

        popover.set_child(box)
        button.set_popover(popover)
        return button

    @property
    def _prefix_path(self) -> str:
        return self.game.prefix_path or config.default_prefix_for(self.game.title, self.game.game_id)

    def _gamescope(self) -> dict:
        if not isinstance(self.game.gamescope, dict):
            self.game.gamescope = {}
        gs = self.game.gamescope
        gs.setdefault("enabled", False)
        gs.setdefault("width", 1920)
        gs.setdefault("height", 1080)
        gs.setdefault("fps", 60)
        gs.setdefault("fullscreen", True)
        gs.setdefault("extra", [])
        return gs

    def _save(self) -> None:
        if self._loading:
            return
        db.update_game(self.game)
        self.app.refresh_library()

    def _sync_field_state(self) -> None:
        enabled = bool(self._gamescope().get("enabled"))
        for row in (self.resolution_row, self.fps_row, self.fullscreen_row, self.gs_extra_row):
            row.set_sensitive(enabled)

    def _sync_running_state(self) -> None:
        running = bool(self.game.id and self.app.is_running(self.game.id))
        self.play_button.set_visible(not running)
        self.stop_button.set_visible(running)
        if running:
            self.status_pill.show_text(_("Running"))
        else:
            self.status_pill.clear()
        self.playtime_label.set_label(format_playtime(self.game.playtime_sec))
        self.sync_playtime()

    def sync_playtime(self) -> None:
        fresh = db.get_game(self.game.id) if self.game.id else None
        if fresh:
            self.playtime_label.set_label(format_playtime(fresh.playtime_sec))
            self.game.playtime_sec = fresh.playtime_sec
            self.game.last_played = fresh.last_played

    # -------------------------------------------------------------- launch
    def _on_play(self, _button) -> None:
        if self.app.is_running(self.game.id):
            self.app.toast(_("This game is already running"))
            return
        self._log_lines.clear()
        started = self.app.play(
            self.game,
            on_line=self._on_log_line,
            on_exit=self._on_game_exit,
        )
        if started:
            self._sync_running_state()

    def _on_stop(self, _button) -> None:
        self.app.stop(self.game.id)

    def _on_log_line(self, line: str) -> None:
        self._log_lines.append(line)
        if len(self._log_lines) > 5000:
            del self._log_lines[:1000]
        if self.log_window is not None:
            self.log_window.append(line)

    def _on_game_exit(self, code: int, duration: float) -> None:
        self._sync_running_state()
        self.app.refresh_library()
        if code == 0:
            self.app.toast(_("Game exited"))
        else:
            self.app.toast(_("Game exited with code %d") % code)

    def _open_logs(self) -> None:
        if self.log_window is not None:
            self.log_window.present()
            return
        log_path = self.app.latest_log(self.game)
        self.log_window = LogWindow(self.window, self.game.title, log_path)
        self.log_window.connect("close-request", self._on_log_window_closed)
        for line in self._log_lines:
            self.log_window.append(line)
        self.log_window.present()

    def _on_log_window_closed(self, *_args) -> bool:
        self.log_window.destroy()
        self.log_window = None
        return False

    # -------------------------------------------------------------- fields
    def _on_proton_changed(self, row: Adw.ComboRow, _param) -> None:
        if self._loading:
            return
        index = row.get_selected()
        self.game.proton_path = self._proton_values[index] if 0 <= index < len(self._proton_values) else ""
        self._save()

    def _on_store_changed(self, row: Adw.ComboRow, _param) -> None:
        if self._loading:
            return
        index = row.get_selected()
        self.game.store = self._store_values[index] if 0 <= index < len(self._store_values) else ""
        self._save()

    def _on_game_id_changed(self, row: Adw.EntryRow) -> None:
        if self._loading:
            return
        self.game.game_id = row.get_text().strip() or "umu-default"
        self._save()

    def _on_args_changed(self, row: Adw.EntryRow) -> None:
        if self._loading:
            return
        try:
            self.game.launch_args = shlex.split(row.get_text())
        except ValueError:
            self.game.launch_args = row.get_text().split()
        self._save()

    def _on_find_game_id(self, _button) -> None:
        dialog = UmuIdDialog(self.game.title, self._apply_umu_entry)
        dialog.present(self)

    def _apply_umu_entry(self, entry) -> None:
        self.game.game_id = entry.umu_id
        if entry.store and entry.store in self._store_values:
            self.game.store = entry.store
        self._loading = True
        self.game_id_row.set_text(self.game.game_id)
        if self.game.store in self._store_values:
            self.store_row.set_selected(self._store_values.index(self.game.store))
        self._loading = False
        self._save()
        self.app.toast(_("GAMEID set to %s") % entry.umu_id)

    def _on_edit_env(self, _button) -> None:
        dialog = EnvDialog(self.game.env, self._apply_env)
        dialog.present(self)

    def _apply_env(self, env: dict[str, str]) -> None:
        self.game.env = env
        self.env_row.set_subtitle(self._env_summary())
        self._save()

    def _on_mangohud_toggled(self, row: Adw.SwitchRow, _param) -> None:
        if self._loading:
            return
        self.game.mangohud = row.get_active()
        self._save()

    def _on_gamescope_toggled(self, row: Adw.ExpanderRow, _param) -> None:
        if self._loading:
            return
        gs = self._gamescope()
        gs["enabled"] = row.get_enable_expansion()
        row.set_expanded(gs["enabled"])
        self._sync_field_state()
        self._save()

    def _on_resolution_changed(self, row: Adw.ComboRow, _param) -> None:
        if self._loading:
            return
        index = row.get_selected()
        if 0 <= index < len(RESOLUTIONS):
            width, height = RESOLUTIONS[index]
            gs = self._gamescope()
            gs["width"] = width
            gs["height"] = height
            self._save()

    def _on_fps_changed(self, row: Adw.ComboRow, _param) -> None:
        if self._loading:
            return
        index = row.get_selected()
        self._gamescope()["fps"] = FPS_CHOICES[index] if 0 <= index < len(FPS_CHOICES) else 0
        self._save()

    def _on_fullscreen_changed(self, row: Adw.SwitchRow, _param) -> None:
        if self._loading:
            return
        self._gamescope()["fullscreen"] = row.get_active()
        self._save()

    def _on_gs_extra_changed(self, row: Adw.EntryRow) -> None:
        if self._loading:
            return
        self._gamescope()["extra"] = row.get_text().split()
        self._save()

    # -------------------------------------------------------------- prefix
    def _refresh_prefix_size(self) -> None:
        prefix = self._prefix_path
        self.prefix_row.set_subtitle(short_path(prefix, 60))
        self.prefix_row.set_tooltip_text(prefix)

        def work() -> None:
            if not Path(prefix).is_dir():
                GLib.idle_add(self._prefix_size_done, _("not created"))
                return
            size = prefixes.size_bytes(prefix)
            GLib.idle_add(self._prefix_size_done, prefixes.human_size(size))

        threading.Thread(target=work, name="prefix-size", daemon=True).start()

    def _prefix_size_done(self, text: str) -> bool:
        self.prefix_info_row.set_subtitle(text)
        return False

    def _on_create_prefix(self, _button) -> None:
        prefix = self._prefix_path
        self.game.prefix_path = prefix
        self._save()
        self.app.toast(_("Creating prefix…"))
        proton = self.game.proton_path

        def work() -> None:
            try:
                code, output = prefixes.create(prefix, proton)
                if code == 0:
                    message = _("Prefix ready")
                else:
                    message = _("Prefix creation failed (code %d). Try another Proton build.") % code
            except Exception as exc:  # noqa: BLE001 - show any failure to the user
                message = str(exc)
            GLib.idle_add(self._prefix_created, message)

        threading.Thread(target=work, name="prefix-create", daemon=True).start()

    def _prefix_created(self, message: str) -> bool:
        self.app.toast(message)
        self._refresh_prefix_size()
        return False

    def _on_open_prefix(self, _button) -> None:
        prefixes.open_in_file_manager(self._prefix_path)

    def _on_delete_prefix(self, _button) -> None:
        prefix = self._prefix_path
        if not Path(prefix).is_dir():
            self.app.toast(_("Prefix does not exist"))
            return
        if not prefixes.is_safe_prefix(prefix):
            self.app.toast(_("Refusing to delete this folder"))
            return

        def do_delete() -> None:
            self.app.toast(_("Deleting prefix…"))

            def work() -> None:
                try:
                    prefixes.remove(prefix)
                    message = _("Prefix deleted")
                except Exception as exc:  # noqa: BLE001
                    message = str(exc)
                GLib.idle_add(self._prefix_created, message)

            threading.Thread(target=work, name="prefix-delete", daemon=True).start()

        confirm(
            self.window,
            _("Delete this prefix?"),
            _("Everything inside %s will be removed, including saves stored in the prefix.") % short_path(prefix, 50),
            _("Delete"),
            do_delete,
            destructive=True,
        )

    # ------------------------------------------------------------- artwork
    def _on_download_cover(self, _button) -> None:
        cover_dialog(
            self.window,
            int(self.game.id),
            self.game.title,
            self.app.settings,
            self._cover_done,
        )

    def _cover_done(self, path: str | None) -> None:
        if not path:
            self.app.toast(_("No cover found"))
            return
        self.apply_cover(path)

    def apply_cover(self, path: str) -> None:
        self.game.cover_path = path
        self.cover_row.set_subtitle(Path(path).name)
        self.cover.set_cover(path, self.game.title)
        self._save()

    def _on_choose_cover(self, _button) -> None:
        choose_file(
            self.window,
            _("Choose a cover image"),
            ["*.jpg", "*.jpeg", "*.png", "*.webp"],
            self._load_local_cover,
        )

    def _load_local_cover(self, source: Path) -> None:
        from ..core import covers

        try:
            path = covers.save_local_cover(source, int(self.game.id))
        except OSError as exc:
            self.app.toast(str(exc))
            return
        self._cover_done(str(path))

    # -------------------------------------------------------------- extras
    def _on_winetricks(self, _button) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Run winetricks"),
            body=_("Space separated verbs, for example: vcrun2022 d3dx9"),
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("vcrun2022 d3dx9")
        entry.set_margin_top(8)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("run", _("Run"))
        dialog.set_response_appearance("run", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("run")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response != "run":
                return
            verbs = entry.get_text().split()
            if not verbs:
                self.app.toast(_("No verbs given"))
                return
            self._open_logs()
            prefix = self._prefix_path
            proton = self.game.proton_path

            def work() -> None:
                try:
                    prefixes.winetricks(prefix, proton, verbs, on_line=self._on_winetricks_line)
                    message = _("winetricks finished")
                except Exception as exc:  # noqa: BLE001
                    message = str(exc)
                GLib.idle_add(lambda: self.app.toast(message) or False)

            threading.Thread(target=work, name="winetricks", daemon=True).start()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_winetricks_line(self, line: str) -> None:
        GLib.idle_add(self._append_winetricks_line, line)

    def _append_winetricks_line(self, line: str) -> bool:
        self._on_log_line(line)
        return False

    def _on_export_shortcut(self, _button) -> None:
        try:
            path = desktop.export(self.game, icon=self.game.cover_path or None)
        except Exception as exc:  # noqa: BLE001
            self.app.toast(str(exc))
            return
        self.app.toast(_("Shortcut created: %s") % str(path))

    # -------------------------------------------------------------- delete
    def _on_delete_game(self, _button) -> None:
        def do_delete() -> None:
            if self.game.id:
                self.app.stop(self.game.id)
                db.delete_game(self.game.id)
                desktop.remove(self.game.id)
            self.app.refresh_library()
            self.window.pop_game_page(self)

        confirm(
            self.window,
            _("Remove “%s” from the library?") % self.game.title,
            _("The executable, prefix and saves are not touched."),
            _("Remove"),
            do_delete,
            destructive=True,
        )


def suffix_button(icon_name: str, tooltip: str, callback: Callable) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon_name)
    button.set_valign(Gtk.Align.CENTER)
    button.set_tooltip_text(tooltip)
    button.connect("clicked", lambda _b: callback(_b))
    return button
