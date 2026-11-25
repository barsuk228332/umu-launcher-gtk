"""Local cache and search over the umu-database (GAMEID / protonfixes ids)."""

from __future__ import annotations

import csv
import difflib
import io
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import config

CSV_URL = "https://raw.githubusercontent.com/Open-Wine-Components/umu-database/main/umu-database.csv"
CACHE_TTL_SECONDS = 7 * 24 * 3600
USER_AGENT = f"umulauncher/{__import__('umulauncher').__version__}"


@dataclass
class UmuEntry:
    title: str
    store: str
    codename: str
    umu_id: str
    acronym: str = ""
    note: str = ""
    exe_strings: str = ""

    @property
    def label(self) -> str:
        parts = [self.title]
        if self.store and self.store != "none":
            parts.append(f"[{self.store}]")
        return " ".join(parts)


def cache_path() -> Path:
    return config.CACHE_DIR / "umu-database.csv"


def _meta_path() -> Path:
    return config.CACHE_DIR / "umu-database.meta.json"


def _read_meta() -> dict:
    try:
        return json.loads(_meta_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_meta(data: dict) -> None:
    try:
        _meta_path().parent.mkdir(parents=True, exist_ok=True)
        _meta_path().write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _download() -> bytes:
    request = urllib.request.Request(CSV_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def update(force: bool = False) -> bool:
    """Refresh the cached CSV. Returns True when the cache was rewritten."""
    meta = _read_meta()
    path = cache_path()
    fresh = path.is_file() and (time.time() - meta.get("fetched_at", 0)) < CACHE_TTL_SECONDS
    if fresh and not force:
        return False

    try:
        raw = _download()
    except Exception:
        return False
    if not raw.strip():
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)
    _write_meta({"fetched_at": time.time(), "size": len(raw)})
    return True


def load_text(text: str) -> list[UmuEntry]:
    entries: list[UmuEntry] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        title = (row.get("TITLE") or "").strip()
        umu_id = (row.get("UMU_ID") or "").strip()
        if not title or not umu_id:
            continue
        entries.append(
            UmuEntry(
                title=title,
                store=(row.get("STORE") or "").strip(),
                codename=(row.get("CODENAME") or "").strip(),
                umu_id=umu_id,
                acronym=(row.get("COMMON ACRONYM (Optional)") or "").strip(),
                note=(row.get("NOTE (Optional)") or "").strip(),
                exe_strings=(row.get("EXE_STRINGS (Optional)") or "").strip(),
            )
        )
    return entries


def load() -> list[UmuEntry]:
    path = cache_path()
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return load_text(text)


def _normalize(text: str) -> str:
    text = text.lower().replace("™", "").replace("®", "")
    return re.sub(r"[^0-9a-zа-яё]+", " ", text).strip()


def _score(query: str, entry: UmuEntry) -> float:
    q = _normalize(query)
    if not q:
        return 0.0
    title = _normalize(entry.title)
    if title == q:
        score = 100.0
    elif title.startswith(q):
        score = 80.0
    elif q in title:
        score = 65.0
    else:
        score = difflib.SequenceMatcher(None, q, title).ratio() * 60.0

    if entry.acronym and _normalize(entry.acronym) == q:
        score = max(score, 90.0)
    codename = _normalize(entry.codename)
    if codename and (codename == q or q in codename):
        score = max(score, 55.0)
    return score


def search(query: str, entries: list[UmuEntry] | None = None, limit: int = 25) -> list[UmuEntry]:
    entries = entries if entries is not None else load()
    if not query.strip():
        return []
    ranked: list[tuple[float, UmuEntry]] = []
    for entry in entries:
        score = _score(query, entry)
        if score >= 40.0:
            ranked.append((score, entry))
    ranked.sort(key=lambda item: (-item[0], item[1].title.lower()))
    return [entry for _score_value, entry in ranked[:limit]]


def best_match(query: str, entries: list[UmuEntry] | None = None) -> UmuEntry | None:
    results = search(query, entries, limit=1)
    return results[0] if results else None


def match_by_exe(exe_name: str, entries: list[UmuEntry] | None = None) -> list[UmuEntry]:
    entries = entries if entries is not None else load()
    needle = exe_name.lower()
    found = [entry for entry in entries if needle in entry.exe_strings.lower()]
    return found[:25]


def is_cache_stale() -> bool:
    meta = _read_meta()
    return (time.time() - meta.get("fetched_at", 0)) > CACHE_TTL_SECONDS
