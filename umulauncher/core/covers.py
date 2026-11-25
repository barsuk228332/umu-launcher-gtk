"""Cover art lookup: SteamGridDB (API key) with Steam CDN as optional fallback."""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import config

SGDB_API = "https://www.steamgriddb.com/api/v2"
STEAM_SEARCH = "https://store.steampowered.com/api/storesearch/"
STEAM_CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"

THROTTLE_SECONDS = 0.8
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_last_request = 0.0


def _throttle() -> None:
    global _last_request
    delta = time.monotonic() - _last_request
    if delta < THROTTLE_SECONDS:
        time.sleep(THROTTLE_SECONDS - delta)
    _last_request = time.monotonic()


def _request(url: str, key: str = "", accept: str = "application/json") -> bytes:
    _throttle()
    headers = {
        "User-Agent": f"umulauncher/{__import__('umulauncher').__version__}",
        "Accept": accept,
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(MAX_IMAGE_BYTES + 1)


def _json(url: str, key: str = "") -> dict:
    try:
        payload = _request(url, key)
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def steam_search(title: str) -> tuple[int | None, str]:
    """Resolve a title to a Steam AppID (no API key needed)."""
    query = urllib.parse.urlencode({"term": title, "l": "english", "cc": "us"})
    data = _json(f"{STEAM_SEARCH}?{query}")
    items = data.get("items") or []
    if not items:
        return None, ""
    needle = re.sub(r"[^0-9a-zа-яё]+", "", title.lower())
    best = None
    best_score = 0.0
    for item in items[:10]:
        name = (item.get("name") or "").lower()
        candidate = re.sub(r"[^0-9a-zа-яё]+", "", name)
        if not candidate:
            continue
        import difflib

        score = difflib.SequenceMatcher(None, needle, candidate).ratio()
        if score > best_score:
            best_score = score
            best = item
    if best is None or best_score < 0.5:
        return None, ""
    return int(best.get("id")), best.get("name", "")


def sgdb_game_id(title: str, key: str) -> int | None:
    query = urllib.parse.quote(title)
    data = _json(f"{SGDB_API}/search/autocomplete/{query}", key)
    items = data.get("data") or []
    if not items:
        return None
    return int(items[0].get("id"))


def sgdb_grid_urls(title: str, key: str, appid: int | None = None) -> list[str]:
    if not key:
        return []
    endpoints: list[str] = []
    if appid:
        endpoints.append(f"{SGDB_API}/grids/steam/{appid}?dimensions=600x900&types=static&nsfw=false&humor=false")
    game_id = sgdb_game_id(title, key)
    if game_id:
        endpoints.append(f"{SGDB_API}/grids/game/{game_id}?dimensions=600x900&types=static&nsfw=false&humor=false")
    for endpoint in endpoints:
        data = _json(endpoint, key)
        entries = data.get("data") or []
        urls = [entry.get("url") for entry in entries if entry.get("url")]
        if urls:
            return urls
    return []


def download(url: str, dest: Path) -> Path | None:
    try:
        payload = _request(url, accept="image/*")
    except Exception:
        return None
    if len(payload) < 1024 or len(payload) > MAX_IMAGE_BYTES:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".jpg"
    target = dest.with_suffix(suffix)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(target)
    return target


def fetch_cover(
    title: str,
    game_row_id: int,
    key: str = "",
    appid: int | None = None,
    allow_cdn: bool = True,
) -> Path | None:
    """Download a 600x900 cover for ``title``; returns the saved path or None."""
    config.ensure_dirs()
    dest = config.COVERS_DIR / f"{game_row_id}.jpg"

    resolved_appid = appid
    if resolved_appid is None:
        resolved_appid, _name = steam_search(title)

    for url in sgdb_grid_urls(title, key, resolved_appid):
        saved = download(url, dest)
        if saved:
            return saved

    if allow_cdn and resolved_appid:
        saved = download(STEAM_CDN.format(appid=resolved_appid), dest)
        if saved:
            return saved

    return None


def save_local_cover(source: Path, game_row_id: int) -> Path:
    config.ensure_dirs()
    suffix = source.suffix.lower() if source.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
    target = config.COVERS_DIR / f"{game_row_id}{suffix}"
    target.write_bytes(source.read_bytes())
    return target
