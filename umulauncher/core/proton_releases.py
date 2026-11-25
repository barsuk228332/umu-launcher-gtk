"""List, download and install Proton builds from GitHub and Forgejo releases.

Only the standard library is used: the archives are streamed into the cache,
verified with the SHA512 file published next to each release and unpacked into
``~/.local/share/umu/compatibilitytools`` (or ``$UMU_FOLDERS_PATH``).
"""

from __future__ import annotations

import hashlib
import http.client
import json
import platform
import shutil
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config

USER_AGENT = f"umulauncher/{__import__('umulauncher').__version__}"
ARCHIVE_SUFFIXES = (".tar.gz", ".tar.xz")
CHUNK_SIZE = 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_CHECKSUM_BYTES = 256 * 1024

ProgressCallback = Callable[[int, int], None]


class ProtonError(RuntimeError):
    """A release could not be listed, downloaded or installed."""


class DownloadCancelled(ProtonError):
    """The user cancelled the download; the partial file is kept for resume."""


@dataclass(frozen=True)
class ProtonSource:
    """A place that publishes Proton builds and the naming it uses for assets."""

    label: str
    repo: str
    releases_url: str
    asset_prefix: str


SOURCES: tuple[ProtonSource, ...] = (
    ProtonSource(
        label="GE-Proton",
        repo="GloriousEggroll/proton-ge-custom",
        releases_url="https://api.github.com/repos/{repo}/releases?per_page={limit}",
        asset_prefix="GE-Proton",
    ),
    ProtonSource(
        label="UMU-Proton",
        repo="Open-Wine-Components/umu-proton",
        releases_url="https://api.github.com/repos/{repo}/releases?per_page={limit}",
        asset_prefix="UMU-Proton",
    ),
    ProtonSource(
        label="Proton-CachyOS",
        repo="CachyOS/proton-cachyos",
        releases_url="https://api.github.com/repos/{repo}/releases?per_page={limit}",
        asset_prefix="proton-cachyos",
    ),
    ProtonSource(
        label="DWProton",
        repo="dawn-winery/dwproton",
        releases_url="https://dawn.wine/api/v1/repos/{repo}/releases?limit={limit}",
        asset_prefix="dwproton",
    ),
    ProtonSource(
        label="Proton Salkim",
        repo="nanomatters/proton-salkim",
        releases_url="https://api.github.com/repos/{repo}/releases?per_page={limit}",
        asset_prefix="proton-wineland",
    ),
)


@dataclass(frozen=True)
class ProtonRelease:
    source: str
    name: str
    tag: str
    archive_name: str
    archive_url: str
    checksum_url: str = ""
    size: int = 0
    published: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} ({self.source})"


# --------------------------------------------------------------- discovery
def _is_arm(machine: str | None = None) -> bool:
    return (machine or platform.machine()).lower() in ("aarch64", "arm64")


def _strip_archive_suffix(name: str) -> str:
    for suffix in ARCHIVE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def clean_build_name(name: str) -> str:
    """Drop the architecture suffix so ``GE-Proton11-14-x86_64`` becomes ``GE-Proton11-14``."""
    for suffix in ("-x86_64_v3", "-x86_64_wow64", "-x86_64", "-aarch64", "-arm64"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _is_arm_asset(name: str) -> bool:
    return "-aarch64" in name or "-arm64" in name


def _matches_arch(name: str, machine: str | None) -> bool:
    if _is_arm(machine):
        return _is_arm_asset(name)
    return not _is_arm_asset(name)


def _select_archive(assets: list[dict], asset_prefix: str, machine: str | None) -> dict | None:
    candidates: list[dict] = []
    for asset in assets:
        name = asset.get("name") or ""
        url = asset.get("browser_download_url") or ""
        if not name.startswith(asset_prefix) or not name.endswith(ARCHIVE_SUFFIXES) or not url:
            continue
        if not _matches_arch(name, machine):
            continue
        candidates.append(asset)
    if not candidates:
        return None
    arm = _is_arm(machine)

    def sort_key(asset: dict) -> tuple:
        name = asset["name"].lower()
        arch_hit = _is_arm_asset(name) if arm else "-x86_64" in name
        # Generic x86_64 builds are safer than the _v3/_wow64 variants.
        variant = 1 if "_v3" in name or "_wow64" in name else 0
        return (0 if arch_hit else 1, variant, len(name), name)

    candidates.sort(key=sort_key)
    return candidates[0]


def _select_checksum(assets: list[dict], archive_name: str, machine: str | None) -> dict | None:
    expected = _strip_archive_suffix(archive_name) + ".sha512sum"
    fallback: dict | None = None
    for asset in assets:
        name = asset.get("name") or ""
        url = asset.get("browser_download_url") or ""
        if not name.endswith(".sha512sum") or not url:
            continue
        if name == expected:
            return asset
        if fallback is None and _matches_arch(name, machine):
            fallback = asset
    return fallback


def resolve_source(source: str | ProtonSource) -> ProtonSource:
    if isinstance(source, ProtonSource):
        return source
    for candidate in SOURCES:
        if source in (candidate.label, candidate.asset_prefix):
            return candidate
    return ProtonSource(
        label=str(source),
        repo="",
        releases_url="",
        asset_prefix=str(source),
    )


def parse_releases(
    payload: object,
    source: str | ProtonSource,
    machine: str | None = None,
) -> list[ProtonRelease]:
    """Convert a GitHub/Forgejo releases payload into installable releases."""
    spec = resolve_source(source)
    if not isinstance(payload, list):
        raise ProtonError(f"unexpected release response for {spec.label}")

    releases: list[ProtonRelease] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("draft") or item.get("prerelease"):
            continue
        assets = [asset for asset in item.get("assets") or [] if isinstance(asset, dict)]
        archive = _select_archive(assets, spec.asset_prefix, machine)
        if archive is None:
            continue
        archive_name = str(archive["name"])
        name = clean_build_name(_strip_archive_suffix(archive_name))
        checksum = _select_checksum(assets, archive_name, machine)
        releases.append(
            ProtonRelease(
                source=spec.label,
                name=name,
                tag=str(item.get("tag_name") or name),
                archive_name=archive_name,
                archive_url=str(archive["browser_download_url"]),
                checksum_url=str(checksum["browser_download_url"]) if checksum else "",
                size=int(archive.get("size") or 0),
                published=str(item.get("published_at") or ""),
            )
        )
    return releases


def _fetch_json(url: str, timeout: float) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_JSON_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProtonError(_explain(exc)) from exc
    if len(payload) > MAX_JSON_BYTES:
        raise ProtonError("release response is too large")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtonError("release host returned malformed JSON") from exc


def fetch_releases(
    source: str | ProtonSource,
    limit: int = 8,
    timeout: float = 20.0,
) -> list[ProtonRelease]:
    spec = resolve_source(source)
    if not spec.releases_url:
        raise ProtonError(f"unknown Proton source: {spec.label}")
    per_page = max(1, min(int(limit), 30))
    url = spec.releases_url.format(repo=spec.repo, limit=per_page)
    payload = _fetch_json(url, timeout)
    return parse_releases(payload, spec)


def fetch_by_source(
    limit: int = 4,
    timeout: float = 20.0,
) -> list[tuple[ProtonSource, list[ProtonRelease], str]]:
    """Newest releases per source, in :data:`SOURCES` order.

    The sources are queried in parallel so one slow host does not block the
    whole list. Each item is ``(source, releases, error)``; a failed host has
    an empty list and a non-empty error string.
    """
    results: dict[str, tuple[list[ProtonRelease], str]] = {}
    lock = threading.Lock()

    def load(source: ProtonSource) -> None:
        try:
            items = fetch_releases(source, limit=limit, timeout=timeout)
            error = ""
        except ProtonError as exc:
            items = []
            error = str(exc)
        with lock:
            results[source.label] = (items, error)

    threads = [
        threading.Thread(target=load, args=(source,), name=f"proton-releases-{index}", daemon=True)
        for index, source in enumerate(SOURCES)
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout + 5.0
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))

    ordered: list[tuple[ProtonSource, list[ProtonRelease], str]] = []
    with lock:
        for source in SOURCES:
            items, error = results.get(source.label, ([], "request timed out"))
            ordered.append((source, items, error))
    return ordered


def fetch_available(limit: int = 4, timeout: float = 20.0) -> list[ProtonRelease]:
    """Newest releases from every source; partial failures are skipped."""
    releases: list[ProtonRelease] = []
    errors: list[str] = []
    for source, items, error in fetch_by_source(limit=limit, timeout=timeout):
        releases.extend(items)
        if error:
            errors.append(f"{source.label}: {error}")
    if not releases:
        if errors:
            raise ProtonError("; ".join(errors))
        raise ProtonError("could not reach the release hosts")
    return releases


# ---------------------------------------------------------------- checksum
def checksum_value(text: str, archive_name: str) -> str:
    """Pick the SHA512 for ``archive_name`` from a .sha512sum file."""
    fallback = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        digest = parts[0]
        if not fallback:
            fallback = digest
        if parts[-1].lstrip("*") == archive_name:
            return digest
    return fallback


def sha512_file(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_checksum(release: ProtonRelease, timeout: float = 20.0) -> str:
    if not release.checksum_url:
        return ""
    request = urllib.request.Request(
        release.checksum_url,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_CHECKSUM_BYTES)
    except (urllib.error.URLError, TimeoutError, OSError):
        return ""
    return checksum_value(payload.decode("utf-8", errors="replace"), release.archive_name)


# ---------------------------------------------------------------- download
def download_cache_dir() -> Path:
    return config.CACHE_DIR / "proton-downloads"


def _explain(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 403:
            return "release host API rate limit reached, try again later"
        return f"release host returned HTTP {exc.code}"
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _response_total(response, offset: int, expected_size: int) -> int:
    content_range = response.headers.get("Content-Range") or ""
    if "/" in content_range:
        tail = content_range.rsplit("/", 1)[1].strip()
        if tail.isdigit():
            return int(tail)
    length = response.headers.get("Content-Length") or ""
    if length.isdigit():
        return offset + int(length)
    return expected_size or 0


def _download_file(
    url: str,
    dest: Path,
    expected_size: int,
    on_progress: ProgressCallback | None,
    cancel: threading.Event | None,
    timeout: float,
) -> None:
    offset = dest.stat().st_size if dest.is_file() else 0
    headers = {"User-Agent": USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)

    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and offset:
            dest.unlink(missing_ok=True)
            return _download_file(url, dest, expected_size, on_progress, cancel, timeout)
        raise ProtonError(_explain(exc)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProtonError(_explain(exc)) from exc

    with response:
        status = getattr(response, "status", 200)
        if offset and status != 206:
            # The server ignored our Range header; start over.
            offset = 0
            dest.unlink(missing_ok=True)
        total = _response_total(response, offset, expected_size)
        done = offset
        if on_progress is not None:
            on_progress(done, total)
        try:
            with dest.open("ab" if offset else "wb") as handle:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled("download cancelled")
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done, total)
        except DownloadCancelled:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            raise ProtonError(_explain(exc)) from exc

    if expected_size > 0 and dest.stat().st_size != expected_size:
        raise ProtonError(
            f"incomplete download: {dest.stat().st_size} of {expected_size} bytes"
        )


def _safe_members(members: list[tarfile.TarInfo], root: Path) -> list[tarfile.TarInfo]:
    root = root.resolve()
    safe: list[tarfile.TarInfo] = []
    for member in members:
        try:
            destination = (root / member.name).resolve()
            if destination != root and root not in destination.parents:
                raise ProtonError(f"archive contains an unsafe path: {member.name}")
            if member.isdev() or member.isfifo():
                raise ProtonError(f"archive contains a special file: {member.name}")
            if member.issym():
                link = (destination.parent / member.linkname).resolve()
                if link != root and root not in link.parents:
                    raise ProtonError(f"archive contains an unsafe symlink: {member.name}")
            elif member.islnk():
                link = (root / member.linkname).resolve()
                if link != root and root not in link.parents:
                    raise ProtonError(f"archive contains an unsafe hardlink: {member.name}")
        except (OSError, RuntimeError) as exc:
            raise ProtonError(f"invalid archive entry: {member.name}") from exc
        safe.append(member)
    return safe


def _safe_extract(archive: Path, root: Path) -> None:
    try:
        with tarfile.open(archive, "r:*") as tar:
            members = _safe_members(tar.getmembers(), root)
            params = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            tar.extractall(root, members=members, **params)
    except ProtonError:
        raise
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ProtonError(f"failed to extract {archive.name}: {exc}") from exc


def _extracted_root(workdir: Path, name: str) -> Path:
    entries = list(workdir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    staging = workdir / name
    staging.mkdir()
    for entry in entries:
        shutil.move(str(entry), str(staging / entry.name))
    return staging


def download_install(
    release: ProtonRelease,
    install_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    timeout: float = 60.0,
) -> Path:
    """Download, verify and install ``release``; returns the build directory."""
    target_dir = Path(install_dir).expanduser() if install_dir else config.PROTONS_DIR
    target = target_dir / release.name
    if target.exists():
        raise ProtonError(f"{release.name} is already installed")
    target_dir.mkdir(parents=True, exist_ok=True)

    expected = fetch_checksum(release, timeout=timeout)
    cache = download_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    part = cache / (release.archive_name + ".part")

    _download_file(release.archive_url, part, release.size, on_progress, cancel, timeout)

    if expected:
        actual = sha512_file(part)
        if actual.lower() != expected.lower():
            part.unlink(missing_ok=True)
            raise ProtonError(f"checksum mismatch for {release.archive_name}")

    workdir = Path(tempfile.mkdtemp(prefix="extract-", dir=cache))
    installed = False
    try:
        _safe_extract(part, workdir)
        source = _extracted_root(workdir, release.name)
        if target.exists():
            raise ProtonError(f"{release.name} is already installed")
        shutil.move(str(source), str(target))
        installed = True
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if installed:
        part.unlink(missing_ok=True)
    return target
