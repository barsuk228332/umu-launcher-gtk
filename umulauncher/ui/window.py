"""Main window and library grid."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, Pango  # noqa: E402

from ..core import config, db  # noqa: E402
from ..core.i18n import _, ngettext  # noqa: E402
from .format import format_playtime  # noqa: E402
from .game_page import GamePage  # noqa: E402
from .proton_manager import ProtonManagerDialog  # noqa: E402
from .widgets import GameCard  # noqa: E402


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app) -> None:
        super().__init__(application=app)
        self.app = app
        self.set_title("umulauncher")
        self.set_default_size(app.settings.window_width, app.settings.window_height)

        self.toasts = Adw.ToastOverlay()
        self.navigation = Adw.NavigationView()
        self.library_page = LibraryPage(self)
        self.navigation.push(self.library_page)
        self.toasts.set_child(self.navigation)
        self.set_content(self.toasts)

        self.connect("close-request", self._on_close)

    def toast(self, text: str) -> None:
        toast = Adw.Toast.new(text)
        toast.set_timeout(4)
        self.toasts.add_toast(toast)

    def show_game(self, game: db.Game) -> None:
        page = GamePage(self, game)
        self.navigation.push(page)

    def pop_game_page(self, page: GamePage) -> None:
        if self.navigation.get_visible_page() is page:
            self.navigation.pop()

    def refresh_library(self) -> None:
        self.library_page.rebuild()

    def refresh_cover(self, game_id: int, path: str) -> None:
        page = self.navigation.get_visible_page()
        if isinstance(page, GamePage) and page.game.id == game_id:
            page.apply_cover(path)

    def show_settings(self) -> None:
        self.app.show_settings(self)

    def _on_close(self, *_args) -> bool:
        width = self.get_width()
        height = self.get_height()
        if width > 400 and height > 300:
            self.app.settings.window_width = width
            self.app.settings.window_height = height
            config.save(self.app.settings)

        for game_id, process in list(self.app.runners.items()):
            if process.running:
                self.app.toast(_("Games keep running after the window is closed"))
                break
        return False


class LibraryPage(Adw.NavigationPage):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(title=_("Library"))
        self.window = window
        self.app = window.app
        self._query = ""

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        self.title_widget = Adw.WindowTitle(title=_("Library"), subtitle="")
        header.set_title_widget(self.title_widget)

        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.set_tooltip_text(_("Add a game"))
        add_button.connect("clicked", lambda _b: self.app.add_game(self.window))
        header.pack_start(add_button)

        header.pack_end(self._build_menu())

        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text(_("Search library"))
        self.search_entry.set_margin_top(6)
        self.search_entry.set_margin_bottom(6)
        self.search_entry.set_margin_start(12)
        self.search_entry.set_margin_end(12)
        self.search_entry.connect("search-changed", self._on_search_changed)
        content.append(self.search_entry)

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_homogeneous(True)
        self.flowbox.set_max_children_per_line(20)
        self.flowbox.set_min_children_per_line(2)
        self.flowbox.set_column_spacing(6)
        self.flowbox.set_row_spacing(6)
        self.flowbox.set_margin_top(6)
        self.flowbox.set_margin_bottom(18)
        self.flowbox.set_margin_start(12)
        self.flowbox.set_margin_end(12)
        self.flowbox.set_valign(Gtk.Align.START)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.flowbox)
        self.stack.add_named(scroller, "grid")

        empty_button = Gtk.Button(label=_("Add a game"))
        empty_button.add_css_class("suggested-action")
        empty_button.add_css_class("pill")
        empty_button.set_halign(Gtk.Align.CENTER)
        empty_button.connect("clicked", lambda _b: self.app.add_game(self.window))

        status = Adw.StatusPage()
        status.set_icon_name("applications-games-symbolic")
        status.set_title(_("No games yet"))
        status.set_description(_("Add a Windows game executable and launch it through umu-run."))
        status.set_child(empty_button)
        self.stack.add_named(status, "empty")

        content.append(self.stack)
        toolbar.set_content(content)
        self.set_child(toolbar)

        self.rebuild()

    def _build_menu(self) -> Gtk.MenuButton:
        button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        button.set_tooltip_text(_("Menu"))
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        proton_button = Gtk.Button(label=_("Proton builds"))
        proton_button.add_css_class("flat")
        proton_button.connect(
            "clicked",
            lambda _b: (popover.popdown(), ProtonManagerDialog(self.app).present(self.window)),
        )
        box.append(proton_button)

        settings_button = Gtk.Button(label=_("Settings"))
        settings_button.add_css_class("flat")
        settings_button.connect("clicked", lambda _b: (popover.popdown(), self.app.show_settings(self.window)))
        box.append(settings_button)

        data_button = Gtk.Button(label=_("Open data folder"))
        data_button.add_css_class("flat")
        data_button.connect(
            "clicked",
            lambda _b: (
                popover.popdown(),
                __import__("subprocess").Popen(["xdg-open", str(config.DATA_DIR)], start_new_session=True),
            ),
        )
        box.append(data_button)

        about_button = Gtk.Button(label=_("About"))
        about_button.add_css_class("flat")
        about_button.connect("clicked", lambda _b: (popover.popdown(), self.app.show_about(self.window)))
        box.append(about_button)

        popover.set_child(box)
        button.set_popover(popover)
        return button

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._query = entry.get_text().strip().lower()
        self.rebuild()

    def rebuild(self) -> None:
        self.flowbox.remove_all()
        games = db.list_games()
        visible = [game for game in games if not self._query or self._query in game.title.lower()]
        for game in visible:
            self.flowbox.append(GameCard(game, self._on_game_activated))

        playing = sum(1 for game in games if game.id and self.app.is_running(game.id))
        subtitle = ngettext("%d game", "%d games", len(games)) % len(games)
        if playing:
            subtitle += " · " + (_("%d running") % playing)
        if self._query and len(visible) != len(games):
            subtitle = _("%d of %d") % (len(visible), len(games))
        self.title_widget.set_subtitle(subtitle)

        if games:
            self.stack.set_visible_child_name("grid")
        else:
            self.stack.set_visible_child_name("empty")

    def _on_game_activated(self, game: db.Game) -> None:
        fresh = db.get_game(game.id) if game.id else None
        self.window.show_game(fresh or game)
