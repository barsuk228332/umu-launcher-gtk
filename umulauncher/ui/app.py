"""GTK application object: owns settings, the window and running games."""

from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import __version__  # noqa: E402
from ..core import config, covers, db, protons, runner, umudb  # noqa: E402
from ..core.i18n import _  # noqa: E402
from .dialogs import SettingsDialog, choose_file  # noqa: E402
from .widgets import install_css  # noqa: E402
from .window import MainWindow  # noqa: E402


class App(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=config.APP_ID)
        self.version = __version__
        self.settings = config.get()
        self.window: MainWindow | None = None
        self.runners: dict[int, runner.GameProcess] = {}
        self._refresh_source: int | None = None
        self._started_db_refresh = False

    # ----------------------------------------------------------- lifecycle
    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        config.ensure_dirs()
        db.init()
        install_css()
        try:
            Gtk.Window.set_default_icon_name("applications-games")
        except Exception:  # noqa: BLE001 - purely cosmetic
            pass

    def do_activate(self) -> None:
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()
        if not self._started_db_refresh:
            self._started_db_refresh = True
            threading.Thread(target=umudb.update, name="umu-db-refresh", daemon=True).start()

    # -------------------------------------------------------------- toasts
    def toast(self, text: str) -> None:
        if self.window is not None:
            self.window.toast(text)

    def refresh_library(self) -> None:
        if self.window is not None:
            self.window.refresh_library()

    def refresh_library_later(self, delay_ms: int = 250) -> None:
        if self.window is None:
            return
        if self._refresh_source is not None:
            GLib.source_remove(self._refresh_source)
        self._refresh_source = GLib.timeout_add(delay_ms, self._refresh_now)

    def _refresh_now(self) -> bool:
        self._refresh_source = None
        self.refresh_library()
        return False

    def show_settings(self, parent: Gtk.Window) -> None:
        SettingsDialog(self).present(parent)

    def show_about(self, parent: Gtk.Window) -> None:
        about = Adw.AboutDialog(
            application_name="umulauncher",
            application_icon="applications-games",
            developer_name="barsuk",
            version=self.version,
            comments=_("A small GTK4 frontend for umu-launcher."),
            license_type=Gtk.License.GPL_3_0,
        )
        about.present(parent)

    # ------------------------------------------------------------ add game
    def add_game(self, parent: Gtk.Window) -> None:
        choose_file(
            parent,
            _("Choose the game executable"),
            ["*.exe", "*.EXE"],
            self._create_game,
        )

    def _create_game(self, exe: Path) -> None:
        title = exe.parent.name or exe.stem
        game = db.Game(
            title=title,
            exe_path=str(exe),
            workdir=str(exe.parent),
            prefix_path=config.default_prefix_for(title),
            proton_path=self.settings.default_proton,
        )
        db.add_game(game)
        self.refresh_library()
        if self.window is not None:
            self.window.show_game(game)
        self._fetch_cover(game)
        self._suggest_game_id(game)

    def _suggest_game_id(self, game: db.Game) -> None:
        exe_name = Path(game.exe_path).name

        def work() -> None:
            entries = umudb.load()
            if not entries:
                umudb.update()
                entries = umudb.load()
            if not entries:
                return
            matches = umudb.match_by_exe(exe_name, entries)
            if not matches:
                hits = umudb.search(game.title, entries, limit=1)
                matches = hits if hits else []
            unique = {entry.umu_id for entry in matches}
            if len(unique) == 1:
                entry = matches[0]
                GLib.idle_add(self._apply_suggestion, game.id, entry.umu_id, entry.store)

        threading.Thread(target=work, name="umu-suggest", daemon=True).start()

    def _apply_suggestion(self, game_id: int | None, umu_id: str, store: str) -> bool:
        if not game_id:
            return False
        fresh = db.get_game(game_id)
        if fresh is None or (fresh.game_id not in ("", "umu-default")):
            return False
        fresh.game_id = umu_id
        if store and not fresh.store:
            fresh.store = store
        db.update_game(fresh)
        self.refresh_library_later()
        self.toast(_("GAMEID suggestion applied: %s") % umu_id)
        return False

    # --------------------------------------------------------------- cover
    def _fetch_cover(self, game: db.Game) -> None:
        if not game.id:
            return
        game_row_id = int(game.id)
        title = game.title
        settings = self.settings

        def work() -> None:
            path = None
            try:
                path = covers.fetch_cover(
                    title,
                    game_row_id,
                    key=settings.sgdb_key,
                    allow_cdn=settings.steam_cdn_fallback,
                )
            except Exception:  # noqa: BLE001 - network errors are expected
                path = None
            if path is not None:
                GLib.idle_add(self._cover_ready, game_row_id, str(path))

        threading.Thread(target=work, name="cover", daemon=True).start()

    def _cover_ready(self, game_id: int, path: str) -> bool:
        fresh = db.get_game(game_id)
        if fresh is not None and not fresh.cover_path:
            fresh.cover_path = path
            db.update_game(fresh)
            self.refresh_library_later()
            if self.window is not None:
                self.window.refresh_cover(game_id, path)
        return False

    # -------------------------------------------------------------- launch
    def play(self, game: db.Game, on_line=None, on_exit=None) -> bool:
        if game.id is None:
            return False
        if self.is_running(game.id):
            return False

        plan = runner.LaunchPlan.from_game(game, self.settings)
        if not game.prefix_path:
            game.prefix_path = plan.prefix
            db.update_game(game)

        def line_callback(line: str) -> None:
            if on_line is not None:
                GLib.idle_add(on_line, line)

        def exit_callback(code: int, duration: float) -> None:
            if game.id is not None:
                db.add_playtime(game.id, int(duration))
                self.runners.pop(game.id, None)
            if on_exit is not None:
                GLib.idle_add(on_exit, code, duration)
            # Called from the log-reader thread: hop to the main loop.
            GLib.idle_add(self.refresh_library_later, 300)

        process = runner.GameProcess(plan, on_line=line_callback, on_exit=exit_callback)
        try:
            process.start()
        except runner.LaunchError as exc:
            self.toast(str(exc))
            return False
        except OSError as exc:
            self.toast(str(exc))
            return False

        self.runners[game.id] = process
        self.toast(_("Launching %s…") % game.title)
        self.refresh_library_later(1200)
        return True

    def stop(self, game_id: int | None) -> None:
        if game_id is None:
            return
        process = self.runners.get(game_id)
        if process is None:
            return
        process.stop()
        self.toast(_("Stopping game…"))
        self.refresh_library_later(1500)

    def is_running(self, game_id: int | None) -> bool:
        if game_id is None:
            return False
        process = self.runners.get(game_id)
        return bool(process and process.running)

    def latest_log(self, game: db.Game) -> Path | None:
        slug = config.slugify(game.title)
        candidates = sorted(config.LOGS_DIR.glob(f"{slug}-*.log"))
        return candidates[-1] if candidates else None

    def proton_builds(self) -> list[protons.ProtonBuild]:
        return protons.discover()
