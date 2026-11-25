"""Paths, settings and small filesystem helpers."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

APP_NAME = "umulauncher"
APP_ID = "io.github.umulauncher.Umulauncher"
APP_TITLE = "umulauncher"


def xdg_dir(env_var: str, fallback: str) -> Path:
    value = os.environ.get(env_var)
    if value:
        return Path(value)
    return Path.home() / fallback


CONFIG_DIR = xdg_dir("XDG_CONFIG_HOME", ".config") / APP_NAME
DATA_DIR = xdg_dir("XDG_DATA_HOME", ".local/share") / APP_NAME
CACHE_DIR = xdg_dir("XDG_CACHE_HOME", ".cache") / APP_NAME

CONFIG_PATH = CONFIG_DIR / "config.json"
DB_PATH = DATA_DIR / "library.db"
COVERS_DIR = DATA_DIR / "covers"
LOGS_DIR = DATA_DIR / "logs"
APPLICATIONS_DIR = xdg_dir("XDG_DATA_HOME", ".local/share") / "applications"


@dataclass
class Settings:
    language: str = "system"
    sgdb_key: str = ""
    steam_cdn_fallback: bool = True
    default_proton: str = ""
    prefix_root: str = str(Path.home() / "Games" / "umu")
    debug_logs: bool = False
    window_width: int = 1100
    window_height: int = 760

    @property
    def prefix_root_path(self) -> Path:
        return Path(os.path.expanduser(self.prefix_root or "~/Games/umu"))


_settings: Settings | None = None


def ensure_dirs() -> None:
    for path in (CONFIG_DIR, DATA_DIR, COVERS_DIR, LOGS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load() -> Settings:
    """Load settings once and cache them."""
    global _settings
    if _settings is not None:
        return _settings

    settings = Settings()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        for field_name in Settings.__dataclass_fields__:
            if field_name in raw:
                setattr(settings, field_name, raw[field_name])
    _settings = settings
    return settings


def get() -> Settings:
    return _settings if _settings is not None else load()


def save(settings: Settings | None = None) -> None:
    global _settings
    if settings is not None:
        _settings = settings
    current = _settings or load()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(current), indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_PATH)


def slugify(text: str, fallback: str = "game") -> str:
    """Filesystem friendly slug that keeps unicode letters where possible."""
    text = (text or "").replace("™", "").replace("®", "").replace("©", "")
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = re.sub(r"[^\w\s.-]+", "", text, flags=re.UNICODE)
    text = re.sub(r"[\s_]+", "-", text).strip("-.")
    return text or fallback


def default_prefix_for(title: str, game_id: str = "") -> str:
    settings = get()
    name = slugify(game_id or title)
    return str(settings.prefix_root_path / name)
