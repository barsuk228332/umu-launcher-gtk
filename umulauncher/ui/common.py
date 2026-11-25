"""Shared UI choices and small helpers."""

from __future__ import annotations

import subprocess

from ..core import protons
from ..core.i18n import _

STORES: list[tuple[str, str]] = [
    ("", _("none")),
    ("egs", "Epic Games"),
    ("gog", "GOG"),
    ("battlenet", "Battle.net"),
    ("amazon", "Amazon Games"),
    ("humble", "Humble Bundle"),
    ("itchio", "itch.io"),
    ("ubisoft", "Ubisoft Connect"),
]

LANGUAGES: list[tuple[str, str]] = [
    ("system", _("System language")),
    ("ru", "Русский"),
    ("en", "English"),
]

RESOLUTIONS: list[tuple[int, int]] = [
    (1280, 720),
    (1600, 900),
    (1920, 1080),
    (2560, 1440),
    (3440, 1440),
    (3840, 2160),
]

FPS_CHOICES: list[int] = [0, 30, 60, 75, 120, 144, 165, 240]


def proton_options() -> tuple[list[str], list[str]]:
    """(labels, stored values) for Proton combo rows."""
    labels: list[str] = []
    values: list[str] = []
    for build in protons.discover():
        labels.append(build.name)
        values.append(build.path or build.codename)
    if not labels:
        labels.append("UMU-Proton (default)")
        values.append("")
    return labels, values


def store_options() -> tuple[list[str], list[str]]:
    return [label for _value, label in STORES], [value for value, _label in STORES]


def resolution_labels() -> list[str]:
    return [f"{width} × {height}" for width, height in RESOLUTIONS]


def notify(summary: str, body: str = "") -> None:
    """Best-effort desktop notification, used by the headless CLI."""
    if not subprocess.os.environ.get("DISPLAY") and not subprocess.os.environ.get("WAYLAND_DISPLAY"):
        return
    try:
        subprocess.Popen(
            ["notify-send", "-a", "umulauncher", summary, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def open_folder(path: str) -> None:
    try:
        subprocess.Popen(["xdg-open", path], start_new_session=True)
    except OSError:
        pass
