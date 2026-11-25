"""Wine prefix helpers built on top of umu-run."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .runner import ensure_umu, sanitize_env


def _umu_env(prefix: str, proton: str, debug: bool = True) -> dict[str, str]:
    env = sanitize_env()
    env["WINEPREFIX"] = str(Path(prefix).expanduser())
    if proton:
        env["PROTONPATH"] = proton
    else:
        env.pop("PROTONPATH", None)
    env["GAMEID"] = "umu-default"
    if debug:
        env["UMU_LOG"] = "1"
    return env


def is_safe_prefix(prefix: str) -> bool:
    """Refuse to delete anything that is obviously not a game prefix."""
    if not prefix:
        return False
    path = Path(prefix).expanduser()
    if not path.is_absolute():
        return False
    try:
        resolved = path.resolve()
    except OSError:
        return False
    forbidden = {Path("/"), Path.home().resolve(), Path.home().resolve() / "Games"}
    if resolved in forbidden:
        return False
    return len(resolved.parts) >= 4


def _is_valid_prefix(prefix_path: Path) -> bool:
    system_reg = prefix_path / "system.reg"
    user_reg = prefix_path / "user.reg"
    try:
        return system_reg.stat().st_size > 1024 and user_reg.is_file()
    except OSError:
        return False


def _terminate_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        proc.terminate()
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def create(
    prefix: str,
    proton: str = "",
    on_line: Callable[[str], None] | None = None,
    timeout: float = 300.0,
) -> tuple[int, str]:
    """Create a prefix with ``umu-run ""``.

    umu/proton keeps running after wineboot finished (there is no executable to
    run), so we wait until the registry is populated and then stop the process
    group ourselves.
    """
    umu = ensure_umu()
    prefix_path = Path(prefix).expanduser()
    prefix_path.parent.mkdir(parents=True, exist_ok=True)
    command = [umu, ""]
    env = _umu_env(str(prefix_path), proton)
    collected: list[str] = []

    proc = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        bufsize=1,
        start_new_session=True,
    )
    assert proc.stdout is not None

    def read_output() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            collected.append(line)
            if on_line:
                on_line(line)

    reader = threading.Thread(target=read_output, name="prefix-create-log", daemon=True)
    reader.start()

    deadline = time.monotonic() + timeout
    last_size = -1
    status = 1
    while True:
        if proc.poll() is not None:
            status = 0 if _is_valid_prefix(prefix_path) else (proc.returncode or 1)
            break
        if _is_valid_prefix(prefix_path):
            try:
                size = (prefix_path / "system.reg").stat().st_size
            except OSError:
                size = -1
            if size == last_size and size > 1024:
                status = 0
                break
            last_size = size
        if time.monotonic() > deadline:
            status = 1
            break
        time.sleep(1.0)

    _terminate_group(proc)
    reader.join(timeout=5)

    if status == 0 and not _is_valid_prefix(prefix_path):
        status = 1
    return status, "\n".join(collected)


def size_bytes(prefix: str) -> int:
    path = Path(prefix).expanduser()
    if not path.is_dir():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TiB"


def remove(prefix: str) -> None:
    if not is_safe_prefix(prefix):
        raise ValueError(f"refusing to remove suspicious prefix: {prefix!r}")
    shutil.rmtree(Path(prefix).expanduser())


def winetricks(
    prefix: str,
    proton: str = "",
    verbs: list[str] | None = None,
    on_line: Callable[[str], None] | None = None,
) -> int:
    umu = ensure_umu()
    command = [umu, "winetricks", *(verbs or [])]
    env = _umu_env(prefix, proton)
    proc = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
        start_new_session=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if on_line:
            on_line(line.rstrip("\n"))
    return proc.wait()


def open_in_file_manager(prefix: str) -> None:
    path = Path(prefix).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    for opener in ("xdg-open", "dolphin", "nautilus", "thunar"):
        if shutil.which(opener):
            subprocess.Popen([opener, str(path)], start_new_session=True)
            return
