"""SQLite storage for the game library."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from . import config

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    exe_path     TEXT NOT NULL,
    workdir      TEXT NOT NULL DEFAULT '',
    prefix_path  TEXT NOT NULL DEFAULT '',
    proton_path  TEXT NOT NULL DEFAULT '',
    game_id      TEXT NOT NULL DEFAULT 'umu-default',
    store        TEXT NOT NULL DEFAULT '',
    launch_args  TEXT NOT NULL DEFAULT '[]',
    env          TEXT NOT NULL DEFAULT '{}',
    gamescope    TEXT NOT NULL DEFAULT '{}',
    mangohud     INTEGER NOT NULL DEFAULT 0,
    cover_path   TEXT NOT NULL DEFAULT '',
    steam_appid  INTEGER,
    created_at   TEXT NOT NULL DEFAULT '',
    last_played  TEXT NOT NULL DEFAULT '',
    playtime_sec INTEGER NOT NULL DEFAULT 0
);
"""

JSON_FIELDS = ("launch_args", "env", "gamescope")


@dataclass
class Game:
    id: int | None = None
    title: str = ""
    exe_path: str = ""
    workdir: str = ""
    prefix_path: str = ""
    proton_path: str = ""
    game_id: str = "umu-default"
    store: str = ""
    launch_args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    gamescope: dict[str, Any] = field(default_factory=dict)
    mangohud: bool = False
    cover_path: str = ""
    steam_appid: int | None = None
    created_at: str = ""
    last_played: str = ""
    playtime_sec: int = 0

    @property
    def gamescope_enabled(self) -> bool:
        return bool(self.gamescope.get("enabled"))

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Game":
        data: dict[str, Any] = dict(row)
        for name in JSON_FIELDS:
            raw = data.get(name)
            try:
                data[name] = json.loads(raw) if raw else ([] if name == "launch_args" else {})
            except ValueError:
                data[name] = [] if name == "launch_args" else {}
        data["mangohud"] = bool(data.get("mangohud"))
        return cls(**data)

    def to_params(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("id")
        for name in JSON_FIELDS:
            data[name] = json.dumps(data[name], ensure_ascii=False)
        data["mangohud"] = int(bool(self.mangohud))
        return data


def db_path() -> Path:
    return config.DB_PATH


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(path: Path | None = None) -> None:
    with session(path) as conn:
        conn.executescript(SCHEMA)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def list_games(path: Path | None = None) -> list[Game]:
    with session(path) as conn:
        rows = conn.execute("SELECT * FROM games ORDER BY title COLLATE NOCASE").fetchall()
    return [Game.from_row(row) for row in rows]


def get_game(game_id: int, path: Path | None = None) -> Game | None:
    with session(path) as conn:
        row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    return Game.from_row(row) if row else None


def add_game(game: Game, path: Path | None = None) -> Game:
    if not game.created_at:
        game.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    params = game.to_params()
    columns = ", ".join(params)
    placeholders = ", ".join("?" for _ in params)
    with session(path) as conn:
        cursor = conn.execute(
            f"INSERT INTO games ({columns}) VALUES ({placeholders})",
            tuple(params.values()),
        )
        game.id = int(cursor.lastrowid)
    return game


def update_game(game: Game, path: Path | None = None) -> None:
    if game.id is None:
        raise ValueError("cannot update a game without id")
    params = game.to_params()
    assignments = ", ".join(f"{name} = ?" for name in params)
    with session(path) as conn:
        conn.execute(
            f"UPDATE games SET {assignments} WHERE id = ?",
            (*params.values(), game.id),
        )


def delete_game(game_id: int, path: Path | None = None) -> None:
    with session(path) as conn:
        conn.execute("DELETE FROM games WHERE id = ?", (game_id,))


def add_playtime(game_id: int, seconds: int, path: Path | None = None) -> None:
    seconds = max(0, int(seconds))
    with session(path) as conn:
        conn.execute(
            "UPDATE games SET playtime_sec = playtime_sec + ?, last_played = ? WHERE id = ?",
            (seconds, time.strftime("%Y-%m-%dT%H:%M:%S"), game_id),
        )
