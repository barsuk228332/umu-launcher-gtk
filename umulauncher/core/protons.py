"""Discover Proton builds installed on the machine."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import config

AUTO_UMU = ""
CODEGEN_GE = "GE-Proton"

# Virtual entries that umu knows how to download/resolve itself.
AUTO_BUILDS = [
    ("UMU-Proton (default)", ""),
    ("GE-Proton (latest, auto-download)", CODEGEN_GE),
]


@dataclass
class ProtonBuild:
    name: str
    path: str = ""
    source: str = ""
    codename: str = ""

    @property
    def is_auto(self) -> bool:
        return self.path == ""

    def env_value(self) -> str | None:
        """Value for PROTONPATH, or None when umu should use its default."""
        if self.path:
            return self.path
        return self.codename or None


def steam_roots() -> list[Path]:
    home = Path.home()
    candidates = [
        Path(os.environ.get("STEAM_COMPAT_CLIENT_INSTALL_PATH", "")) if os.environ.get("STEAM_COMPAT_CLIENT_INSTALL_PATH") else None,
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        Path("/usr/share/steam"),
        Path("/usr/local/share/steam"),
    ]
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None or not candidate.is_dir():
            continue
        try:
            key = str(candidate.resolve())
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        roots.append(candidate)
    return roots


def _library_paths_from_vdf(steam_root: Path) -> list[Path]:
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    paths: list[Path] = []
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        raw = match.group(1).replace("\\\\", "\\")
        path = Path(raw)
        if path.is_dir():
            paths.append(path)
    return paths


def library_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key not in seen and path.is_dir():
            seen.add(key)
            roots.append(path)

    for steam_root in steam_roots():
        add(steam_root)
        for lib in _library_paths_from_vdf(steam_root):
            add(lib)
    add(Path.home() / ".local/share/Steam")
    return roots


def _looks_like_proton(path: Path) -> bool:
    return (path / "proton").is_file() or (path / "files" / "bin" / "wine").is_file()


def is_usable(path: Path) -> bool:
    """A build without a default prefix template cannot create new prefixes."""
    if (path / "files" / "share" / "default_pfx").is_dir():
        return True
    if (path / "files" / "share" / "default_pfx_arm64").is_dir():
        return True
    # Some very old builds have no template but still work with existing prefixes.
    return False


def extra_proton_dirs() -> list[Path]:
    return [
        config.PROTONS_DIR,
        config.STEAM_COMPAT_DIR,
        config.UMU_DATA_DIR,
        Path.home() / ".local/share/umu",
        Path.home() / ".local/share/Steam/compatibilitytools.d",
        Path.home() / ".steam/steam/compatibilitytools.d",
    ]


def discover(include_incomplete: bool = False) -> list[ProtonBuild]:
    """Return auto entries first, then installed builds sorted by name."""
    builds: list[ProtonBuild] = [
        ProtonBuild(name=name, path="", source="auto", codename=codename)
        for name, codename in AUTO_BUILDS
    ]

    def usable(entry: Path) -> bool:
        return is_usable(entry) or include_incomplete

    seen: set[str] = set()
    for root in library_roots():
        for compat_dir in (root / "compatibilitytools.d", root / "steamapps" / "common"):
            if not compat_dir.is_dir():
                continue
            try:
                entries = sorted(compat_dir.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                continue
            for entry in entries:
                if not entry.is_dir() or not _looks_like_proton(entry):
                    continue
                if not usable(entry):
                    continue
                try:
                    key = str(entry.resolve())
                except OSError:
                    key = str(entry)
                if key in seen:
                    continue
                seen.add(key)
                builds.append(
                    ProtonBuild(
                        name=entry.name,
                        path=str(entry),
                        source="compatibilitytools.d" if compat_dir.name == "compatibilitytools.d" else "steamapps/common",
                    )
                )

    # Extra locations used by umu itself and by ProtonUp-Qt style tools.
    extra_dirs = extra_proton_dirs()
    for base in extra_dirs:
        if not base.is_dir():
            continue
        try:
            entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or not _looks_like_proton(entry):
                continue
            if not usable(entry):
                continue
            try:
                key = str(entry.resolve())
            except OSError:
                key = str(entry)
            if key in seen:
                continue
            seen.add(key)
            builds.append(ProtonBuild(name=entry.name, path=str(entry), source="umu"))

    return builds


def find_build(builds: list[ProtonBuild], proton_path: str) -> ProtonBuild | None:
    if not proton_path:
        return builds[0] if builds else None
    for build in builds:
        if build.path == proton_path:
            return build
    return None


def installed(include_incomplete: bool = True) -> list[ProtonBuild]:
    """Installed builds only, without the virtual auto-download entries."""
    return [build for build in discover(include_incomplete=include_incomplete) if not build.is_auto]


def removable_dirs() -> list[Path]:
    """Folders where the launcher is allowed to delete a Proton build."""
    candidates = [config.PROTONS_DIR, config.STEAM_COMPAT_DIR]
    for root in library_roots():
        candidates.append(root / "compatibilitytools.d")
    for extra in extra_proton_dirs():
        if extra.name == "compatibilitytools.d":
            candidates.append(extra)

    dirs: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate)
        if key not in seen:
            seen.add(key)
            dirs.append(candidate)
    return dirs


def is_removable(path: str | Path, roots: list[Path] | None = None) -> bool:
    """True when ``path`` is a build directory directly inside a compatibility folder."""
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    if not resolved.is_dir():
        return False
    for root in roots if roots is not None else removable_dirs():
        try:
            if resolved.parent == Path(root).expanduser().resolve():
                return True
        except OSError:
            continue
    return False


def remove_build(path: str | Path, roots: list[Path] | None = None) -> None:
    if not is_removable(path, roots):
        raise ValueError(f"refusing to remove a non-compatibility folder: {path!r}")
    shutil.rmtree(Path(path).expanduser())
