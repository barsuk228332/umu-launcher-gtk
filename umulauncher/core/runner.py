"""Build the launch environment and run games through umu-run."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import config
from .db import Game

DROP_EXACT = {
    "SteamAppId",
    "SteamGameId",
    "SteamOverlayGameId",
    "SteamOS",
    "STEAM_RUNTIME",
    "STEAM_RUNTIME_LIBRARY_PATH",
    "STEAM_RUNTIME_PREFIX",
    "LD_PRELOAD",
}

DROP_PREFIXES = ("STEAM_COMPAT_", "PRESSURE_VESSEL_")

STOP_GRACE_SECONDS = 10.0


class LaunchError(RuntimeError):
    pass


@dataclass
class LaunchPlan:
    exe: str
    prefix: str
    proton: str = ""
    game_id: str = "umu-default"
    store: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    gamescope: dict = field(default_factory=dict)
    mangohud: bool = False
    debug: bool = False
    workdir: str = ""
    title: str = ""
    umu_run: str = "umu-run"

    @classmethod
    def from_game(cls, game: Game, settings: config.Settings | None = None) -> "LaunchPlan":
        settings = settings or config.get()
        prefix = game.prefix_path or str(
            settings.prefix_root_path / config.slugify(game.game_id or game.title)
        )
        return cls(
            exe=game.exe_path,
            prefix=prefix,
            proton=game.proton_path,
            game_id=game.game_id or "umu-default",
            store=game.store,
            args=list(game.launch_args),
            env=dict(game.env),
            gamescope=dict(game.gamescope),
            mangohud=bool(game.mangohud),
            debug=bool(settings.debug_logs),
            workdir=game.workdir,
            title=game.title,
        )


def sanitize_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Remove Steam/pressure-vessel variables so umu can start its own runtime."""
    env = dict(os.environ if base is None else base)
    for key in list(env):
        if key in DROP_EXACT or key.startswith(DROP_PREFIXES):
            env.pop(key, None)
    for key in ("LD_LIBRARY_PATH", "LD_AUDIT", "PYTHONHOME"):
        value = env.get(key, "")
        if key == "PYTHONHOME" or "steam" in value.lower() or "pressure-vessel" in value.lower():
            env.pop(key, None)
    return env


def build_env(plan: LaunchPlan, base: dict[str, str] | None = None) -> dict[str, str]:
    env = sanitize_env(base)

    env["WINEPREFIX"] = plan.prefix
    env["GAMEID"] = plan.game_id or "umu-default"

    if plan.store:
        env["STORE"] = plan.store
    else:
        env.pop("STORE", None)

    if plan.proton:
        env["PROTONPATH"] = plan.proton
    else:
        env.pop("PROTONPATH", None)

    if plan.debug:
        env["UMU_LOG"] = "1"
    else:
        env.pop("UMU_LOG", None)

    if plan.mangohud:
        env["MANGOHUD"] = "1"
    else:
        env.pop("MANGOHUD", None)

    # Per-game overrides win over everything above.
    env.update({str(k): str(v) for k, v in plan.env.items()})
    return env


def gamescope_argv(gamescope: dict) -> list[str]:
    if not gamescope or not gamescope.get("enabled"):
        return []
    width = int(gamescope.get("width") or 1920)
    height = int(gamescope.get("height") or 1080)
    fps = int(gamescope.get("fps") or 0)
    argv = ["gamescope", "-W", str(width), "-H", str(height)]
    if fps > 0:
        argv += ["-r", str(fps)]
    if gamescope.get("fullscreen", True):
        argv.append("-f")
    for extra in gamescope.get("extra") or []:
        argv.append(str(extra))
    argv.append("--")
    return argv


def build_argv(plan: LaunchPlan, umu_run: str | None = None) -> list[str]:
    umu = umu_run or plan.umu_run or "umu-run"
    argv = [umu, plan.exe]
    argv.extend(str(arg) for arg in plan.args)
    return gamescope_argv(plan.gamescope) + argv


def ensure_umu(umu_run: str = "umu-run") -> str:
    found = shutil.which(umu_run)
    if not found:
        raise LaunchError(
            f"'{umu_run}' not found in PATH. Install umu-launcher (pacman -S umu-launcher)."
        )
    return found


def log_path_for(title: str) -> Path:
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return config.LOGS_DIR / f"{config.slugify(title)}-{stamp}.log"


class GameProcess:
    """Runs a launch plan and streams merged stdout/stderr line by line."""

    def __init__(
        self,
        plan: LaunchPlan,
        on_line: Callable[[str], None] | None = None,
        on_exit: Callable[[int, float], None] | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.plan = plan
        self.on_line = on_line
        self.on_exit = on_exit
        self.log_path = log_path or log_path_for(plan.title or "game")
        self.command: list[str] = []
        self.started_at: float = 0.0
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._log_file = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        umu = ensure_umu(self.plan.umu_run)
        self.command = build_argv(self.plan, umu)
        env = build_env(self.plan)
        cwd = self.plan.workdir or str(Path(self.plan.exe).parent)
        if not Path(cwd).is_dir():
            cwd = str(Path.home())

        if not Path(self.plan.exe).is_file() and self.plan.exe:
            raise LaunchError(f"Executable not found: {self.plan.exe}")

        self._log_file = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self._write_log(f"# umulauncher {datetime.now().isoformat(timespec='seconds')}")
        self._write_log(f"# command: {shlex_join(self.command)}")
        self._write_log(f"# prefix: {self.plan.prefix}")
        self._write_log(f"# proton: {self.plan.proton or 'UMU-Proton (default)'}")

        try:
            self._proc = subprocess.Popen(
                self.command,
                env=env,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                errors="replace",
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            self._write_log(f"# failed to start: {exc}")
            if self._log_file is not None:
                try:
                    self._log_file.close()
                except OSError:
                    pass
                self._log_file = None
            raise LaunchError(str(exc)) from exc

        self.started_at = time.monotonic()
        self._reader = threading.Thread(target=self._read_stream, name="umu-log", daemon=True)
        self._reader.start()

    def _write_log(self, line: str) -> None:
        if self._log_file is None:
            return
        try:
            self._log_file.write(line + "\n")
            self._log_file.flush()
        except OSError:
            pass

    def _read_stream(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                self._write_log(line)
                if self.on_line:
                    try:
                        self.on_line(line)
                    except Exception:
                        pass
        finally:
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except OSError:
                pass
            proc.wait()
            duration = time.monotonic() - self.started_at if self.started_at else 0.0
            code = proc.returncode if proc.returncode is not None else -1
            self._write_log(f"# exit code: {code} after {duration:.1f}s")
            if self._log_file:
                try:
                    self._log_file.close()
                except OSError:
                    pass
                self._log_file = None
            if self.on_exit:
                try:
                    self.on_exit(code, duration)
                except Exception:
                    pass

    def stop(self, timeout: float = STOP_GRACE_SECONDS) -> None:
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            pgid = os.getpgid(proc.pid)
        except OSError:
            pgid = proc.pid
        try:
            os.killpg(pgid, signal.SIGTERM)
        except OSError:
            proc.terminate()

        def escalate() -> None:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    return
                time.sleep(0.2)
            if proc.poll() is None:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except OSError:
                    proc.kill()

        threading.Thread(target=escalate, name="umu-kill", daemon=True).start()

    def wait(self) -> int:
        proc = self._proc
        if proc is None:
            return -1
        if self._reader:
            self._reader.join()
        return proc.returncode if proc.returncode is not None else -1


def shlex_join(argv: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(part) for part in argv)


def run_blocking(plan: LaunchPlan, echo: bool = False) -> int:
    def on_line(line: str) -> None:
        if echo:
            print(line, flush=True)

    process = GameProcess(plan, on_line=on_line)
    print(f"[umulauncher] log: {process.log_path}", flush=True)
    process.start()
    return process.wait()
