"""Reusable GTK widgets."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gtk, Pango  # noqa: E402

from ..core.db import Game  # noqa: E402
from .format import initials  # noqa: E402

CSS = """
.cover-frame {
    border-radius: 12px;
    background-color: alpha(@card_bg_color, 0.6);
    box-shadow: 0 2px 10px alpha(black, 0.25);
}
.cover-placeholder {
    background-image: linear-gradient(135deg, alpha(@accent_bg_color, 0.55), alpha(@accent_bg_color, 0.15));
    border-radius: 12px;
}
.cover-placeholder label {
    font-size: 28px;
    font-weight: 800;
    opacity: 0.85;
}
.game-card {
    background: none;
    border: none;
    box-shadow: none;
    padding: 6px;
}
.game-card:hover {
    background-color: alpha(@card_bg_color, 0.7);
    border-radius: 16px;
}
.game-card-title {
    font-weight: 600;
}
.game-card-subtitle {
    font-size: 0.85em;
    opacity: 0.65;
}
.status-pill {
    padding: 2px 10px;
    border-radius: 999px;
    background-color: alpha(@accent_bg_color, 0.25);
    font-size: 0.85em;
}
"""


def install_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


class CoverView(Gtk.Box):
    """600x900-ish cover with rounded corners and an initials placeholder."""

    def __init__(self, width: int = 160, height: int = 240) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.width = width
        self.height = height
        self.set_size_request(width, height)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.add_css_class("cover-frame")
        self._picture: Gtk.Picture | None = None
        self._placeholder: Gtk.Box | None = None
        self.set_placeholder("")

    def set_placeholder(self, title: str) -> None:
        self._clear()
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        placeholder.set_size_request(self.width, self.height)
        placeholder.add_css_class("cover-placeholder")
        label = Gtk.Label(label=initials(title))
        label.set_vexpand(True)
        placeholder.append(label)
        self.append(placeholder)
        self._placeholder = placeholder

    def _clear(self) -> None:
        while (child := self.get_first_child()) is not None:
            self.remove(child)
        self._picture = None
        self._placeholder = None

    def set_cover(self, path: str | None, title: str = "") -> None:
        if path and Path(path).is_file():
            self._clear()
            picture = Gtk.Picture.new_for_filename(path)
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_can_shrink(True)
            picture.set_size_request(self.width, self.height)
            self.append(picture)
            self._picture = picture
        elif not self._placeholder:
            self.set_placeholder(title)


class GameCard(Gtk.FlowBoxChild):
    def __init__(self, game: Game, on_activate) -> None:
        super().__init__()
        self.game = game
        button = Gtk.Button()
        button.add_css_class("game-card")
        button.set_has_frame(False)
        button.connect("clicked", lambda _b: on_activate(game))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(168, -1)
        self.cover = CoverView(168, 252)
        self.cover.set_cover(game.cover_path or None, game.title)
        box.append(self.cover)

        title = Gtk.Label(label=game.title, xalign=0)
        title.add_css_class("game-card-title")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(20)
        box.append(title)

        subtitle = Gtk.Label(label=game.game_id or "umu-default", xalign=0)
        subtitle.add_css_class("game-card-subtitle")
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(subtitle)

        button.set_child(box)
        self.set_child(button)


class StatusPill(Gtk.Label):
    def __init__(self) -> None:
        super().__init__(label="")
        self.add_css_class("status-pill")
        self.set_visible(False)

    def show_text(self, text: str) -> None:
        self.set_label(text)
        self.set_visible(True)

    def clear(self) -> None:
        self.set_visible(False)
