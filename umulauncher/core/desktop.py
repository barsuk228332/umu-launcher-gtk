"""Export games as .desktop entries so they show up in the desktop menu."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import config
from .db import Game

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def launcher_command(game_id: int) -> list[str]:
    console_script = shutil.which("umulauncher")
    if console_script:
        return [console_script, "--run", str(game_id)]
    return [
        "env",
        f"PYTHONPATH={PROJECT_ROOT}",
        sys.executable,
        "-m",
        "umulauncher",
        "--run",
        str(game_id),
    ]


def quote_exec(argument: str) -> str:
    """"Quote an Exec= argument following the Desktop Entry Specification."""
    if argument and not any(ch in argument for ch in ' \t\n"\'\\><~|&;$*?#()`'):
        return argument
    escaped = argument.replace("\\", "\\\\")
    for char in ('"', "`", "$"):
        escaped = escaped.replace(char, "\\" + char)
    return f'"{escaped}"'


def desktop_path(game_id: int) -> Path:
    return config.APPLICATIONS_DIR / f"umulauncher-{game_id}.desktop"


def export(game: Game, icon: str | None = None) -> Path:
    if game.id is None:
        raise ValueError("game must be saved before exporting a shortcut")
    config.APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

    command = " ".join(quote_exec(part) for part in launcher_command(int(game.id)))
    icon_name = icon or game.cover_path or "applications-games"
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={game.title}",
        f"Comment={game.exe_path}",
        f"Exec={command}",
        f"Icon={icon_name}",
        "Terminal=false",
        "StartupNotify=false",
        "Categories=Game;",
        "Keywords=umu;wine;proton;game;",
    ]
    if game.workdir and Path(game.workdir).is_dir():
        lines.append(f"Path={game.workdir}")

    target = desktop_path(int(game.id))
    tmp = target.with_suffix(".desktop.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o755)
    tmp.replace(target)
    return target


def remove(game_id: int) -> bool:
    target = desktop_path(game_id)
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False
