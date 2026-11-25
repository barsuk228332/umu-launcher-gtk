"""Formatting helpers used by the UI."""

from __future__ import annotations

from ..core.i18n import _


def format_playtime(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return _("never played")
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    parts: list[str] = []
    if hours:
        parts.append(_("%d h") % hours)
    if minutes or not hours:
        parts.append(_("%d min") % minutes)
    return " ".join(parts)


def initials(title: str) -> str:
    words = [word for word in title.split() if word]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def short_path(path: str, limit: int = 64) -> str:
    if not path:
        return ""
    home = str(__import__("pathlib").Path.home())
    display = path.replace(home, "~", 1) if path.startswith(home) else path
    if len(display) <= limit:
        return display
    keep = max(8, (limit - 3) // 2)
    return display[:keep] + "…" + display[-keep:]
