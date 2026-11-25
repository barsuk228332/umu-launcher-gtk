import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from umulauncher.core import runner


class FakeUmuRunTest(unittest.TestCase):
    """End-to-end test of GameProcess using a stub umu-run on PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()

        self.umu = self.bin / "umu-run"
        self.umu.write_text(
            "#!/bin/sh\n"
            'echo "ARGS:$@"\n'
            'echo "PREFIX:$WINEPREFIX"\n'
            'echo "GAMEID:$GAMEID"\n'
            'echo "STORE:$STORE"\n'
            'echo "MANGOHUD:$MANGOHUD"\n'
            'echo "STEAMAPP:$SteamAppId"\n'
            'echo "COMPAT:$STEAM_COMPAT_DATA_PATH"\n'
            "exit 7\n"
        )
        os.chmod(self.umu, 0o755)

        self.exe = self.dir / "game.exe"
        self.exe.write_text("MZ")
        self.log = self.dir / "run.log"

        self._old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{self._old_path}"
        os.environ["SteamAppId"] = "123"
        os.environ["STEAM_COMPAT_DATA_PATH"] = "/steam/compat"

    def tearDown(self):
        os.environ["PATH"] = self._old_path
        os.environ.pop("SteamAppId", None)
        os.environ.pop("STEAM_COMPAT_DATA_PATH", None)
        self.tmp.cleanup()

    def test_streams_output_and_reports_exit_code(self):
        plan = runner.LaunchPlan(
            exe=str(self.exe),
            prefix=str(self.dir / "pfx"),
            game_id="umu-42",
            store="gog",
            args=["--windowed"],
            mangohud=True,
            title="Fake Game",
        )
        lines: list[str] = []
        result: dict[str, object] = {}
        finished = threading.Event()

        def on_exit(code: int, duration: float) -> None:
            result["code"] = code
            result["duration"] = duration
            finished.set()

        process = runner.GameProcess(plan, on_line=lines.append, on_exit=on_exit, log_path=self.log)
        process.start()
        self.assertTrue(finished.wait(20), "process did not finish")
        process.wait()

        self.assertEqual(result["code"], 7)
        joined = "\n".join(lines)
        self.assertIn("--windowed", joined)
        self.assertIn("PREFIX:" + str(self.dir / "pfx"), joined)
        self.assertIn("GAMEID:umu-42", joined)
        self.assertIn("STORE:gog", joined)
        self.assertIn("MANGOHUD:1", joined)
        # Steam container variables must not leak into umu.
        self.assertIn("STEAMAPP:", joined)
        self.assertNotIn("STEAMAPP:123", joined)
        self.assertIn("COMPAT:", joined)
        self.assertNotIn("COMPAT:/steam", joined)

        log_text = self.log.read_text()
        self.assertIn("# exit code: 7", log_text)
        self.assertIn(str(self.exe), log_text)

    def test_missing_executable_raises(self):
        plan = runner.LaunchPlan(exe=str(self.dir / "nope.exe"), prefix=str(self.dir / "pfx"))
        process = runner.GameProcess(plan, log_path=self.log)
        with self.assertRaises(runner.LaunchError):
            process.start()

    def test_missing_umu_raises(self):
        plan = runner.LaunchPlan(exe=str(self.exe), prefix=str(self.dir / "pfx"))
        process = runner.GameProcess(plan, log_path=self.log)
        with mock.patch.object(runner.shutil, "which", return_value=None):
            with self.assertRaises(runner.LaunchError):
                process.start()


if __name__ == "__main__":
    unittest.main()
