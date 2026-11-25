"""Window that shows live or saved umu output."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..core.i18n import _  # noqa: E402

MAX_LINES = 5000


class LogWindow(Adw.Window):
    def __init__(self, parent: Gtk.Window, title: str, log_path: Path | None = None) -> None:
        super().__init__(transient_for=parent, modal=False)
        self.set_title(_("Log: %s") % title)
        self.set_default_size(900, 600)
        self.log_path = log_path

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_button.set_tooltip_text(_("Copy all"))
        copy_button.connect("clicked", self._on_copy)
        header.pack_end(copy_button)

        clear_button = Gtk.Button(icon_name="edit-clear-symbolic")
        clear_button.set_tooltip_text(_("Clear view"))
        clear_button.connect("clicked", lambda _b: self.buffer.set_text(""))
        header.pack_end(clear_button)

        open_button = Gtk.Button(icon_name="folder-open-symbolic")
        open_button.set_tooltip_text(_("Open log folder"))
        open_button.connect("clicked", self._on_open_folder)
        header.pack_end(open_button)

        toolbar.add_top_bar(header)

        self.text_view = Gtk.TextView()
        self.text_view.set_editable(False)
        self.text_view.set_monospace(True)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text_view.set_left_margin(8)
        self.text_view.set_right_margin(8)
        self.text_view.set_top_margin(8)
        self.text_view.set_bottom_margin(8)
        self.buffer = self.text_view.get_buffer()

        scroller = Gtk.ScrolledWindow()
        scroller.set_child(self.text_view)
        scroller.set_vexpand(True)
        toolbar.set_content(scroller)

        self.set_content(toolbar)

        if log_path and log_path.is_file():
            try:
                content = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            self.buffer.set_text(content)
            self.scroll_to_end()

    def append(self, line: str) -> None:
        end = self.buffer.get_end_iter()
        if self.buffer.get_line_count() > MAX_LINES:
            start = self.buffer.get_start_iter()
            cut = self.buffer.get_iter_at_line(self.buffer.get_line_count() - MAX_LINES)
            self.buffer.delete(start, cut)
        self.buffer.insert(end, line + "\n")
        self.scroll_to_end()

    def scroll_to_end(self) -> None:
        GLib.idle_add(self._scroll_idle)

    def _scroll_idle(self) -> bool:
        end = self.buffer.get_end_iter()
        mark = self.buffer.create_mark(None, end, False)
        self.text_view.scroll_mark_onscreen(mark)
        self.buffer.delete_mark(mark)
        return False

    def _on_copy(self, _button) -> None:
        start, end = self.buffer.get_bounds()
        text = self.buffer.get_text(start, end, True)
        clipboard = self.get_clipboard()
        clipboard.set(text)

    def _on_open_folder(self) -> None:
        import subprocess

        folder = self.log_path.parent if self.log_path else Path.home()
        subprocess.Popen(["xdg-open", str(folder)], start_new_session=True)
