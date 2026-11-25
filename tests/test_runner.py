import unittest

from umulauncher.core import config, runner
from umulauncher.core.db import Game


class SanitizeEnvTest(unittest.TestCase):
    def test_removes_steam_and_container_variables(self):
        base = {
            "HOME": "/home/user",
            "PATH": "/usr/bin",
            "SteamAppId": "123",
            "STEAM_COMPAT_DATA_PATH": "/tmp/x",
            "STEAM_RUNTIME": "/tmp/runtime",
            "PRESSURE_VESSEL_BWRAP": "/usr/bin/bwrap",
            "LD_PRELOAD": "/steam/libgameoverlayrenderer.so",
            "LD_LIBRARY_PATH": "/home/user/.steam/root/lib",
            "MYVAR": "keep",
        }
        env = runner.sanitize_env(base)
        for key in ("SteamAppId", "STEAM_COMPAT_DATA_PATH", "STEAM_RUNTIME", "PRESSURE_VESSEL_BWRAP"):
            self.assertNotIn(key, env)
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("LD_LIBRARY_PATH", env)
        self.assertEqual(env["MYVAR"], "keep")
        self.assertEqual(env["HOME"], "/home/user")

    def test_keeps_unrelated_ld_library_path(self):
        env = runner.sanitize_env({"LD_LIBRARY_PATH": "/opt/mygame/lib"})
        self.assertEqual(env["LD_LIBRARY_PATH"], "/opt/mygame/lib")


class BuildEnvTest(unittest.TestCase):
    def plan(self, **kwargs):
        defaults = dict(
            exe="/games/game.exe",
            prefix="/games/prefix",
            proton="/opt/GE-Proton9-20",
            game_id="umu-123",
            store="gog",
        )
        defaults.update(kwargs)
        return runner.LaunchPlan(**defaults)

    def test_core_variables(self):
        env = runner.build_env(self.plan(), base={"HOME": "/home/user", "STORE": "stale", "PROTONPATH": "/old"})
        self.assertEqual(env["WINEPREFIX"], "/games/prefix")
        self.assertEqual(env["GAMEID"], "umu-123")
        self.assertEqual(env["STORE"], "gog")
        self.assertEqual(env["PROTONPATH"], "/opt/GE-Proton9-20")
        self.assertNotIn("UMU_LOG", env)
        self.assertNotIn("MANGOHUD", env)

    def test_auto_proton_unsets_protonpath(self):
        env = runner.build_env(self.plan(proton=""), base={"PROTONPATH": "/old"})
        self.assertNotIn("PROTONPATH", env)

    def test_debug_and_mangohud(self):
        env = runner.build_env(self.plan(debug=True, mangohud=True), base={})
        self.assertEqual(env["UMU_LOG"], "1")
        self.assertEqual(env["MANGOHUD"], "1")

    def test_per_game_env_wins(self):
        env = runner.build_env(self.plan(env={"MANGOHUD": "0", "DXVK_HUD": "fps"}), base={})
        self.assertEqual(env["MANGOHUD"], "0")
        self.assertEqual(env["DXVK_HUD"], "fps")

    def test_game_id_default(self):
        env = runner.build_env(self.plan(game_id=""), base={})
        self.assertEqual(env["GAMEID"], "umu-default")


class ArgvTest(unittest.TestCase):
    def test_plain_command(self):
        plan = runner.LaunchPlan(exe="/games/game.exe", prefix="/p", args=["-windowed", "x y"])
        argv = runner.build_argv(plan, "umu-run")
        self.assertEqual(argv, ["umu-run", "/games/game.exe", "-windowed", "x y"])

    def test_gamescope_wrapping(self):
        gamescope = {"enabled": True, "width": 2560, "height": 1440, "fps": 60, "fullscreen": True, "extra": ["--fsr"]}
        plan = runner.LaunchPlan(exe="/games/game.exe", prefix="/p", gamescope=gamescope)
        argv = runner.build_argv(plan, "umu-run")
        self.assertEqual(
            argv,
            [
                "gamescope",
                "-W",
                "2560",
                "-H",
                "1440",
                "-r",
                "60",
                "-f",
                "--fsr",
                "--",
                "umu-run",
                "/games/game.exe",
            ],
        )

    def test_gamescope_without_fps(self):
        gamescope = {"enabled": True, "width": 1280, "height": 720, "fps": 0, "fullscreen": False}
        plan = runner.LaunchPlan(exe="/g.exe", prefix="/p", gamescope=gamescope)
        self.assertEqual(
            runner.build_argv(plan, "umu-run"),
            ["gamescope", "-W", "1280", "-H", "720", "--", "umu-run", "/g.exe"],
        )

    def test_disabled_gamescope_is_ignored(self):
        plan = runner.LaunchPlan(exe="/g.exe", prefix="/p", gamescope={"enabled": False})
        self.assertEqual(runner.build_argv(plan, "umu-run"), ["umu-run", "/g.exe"])


class EffectiveWorkdirTest(unittest.TestCase):
    def test_defaults_to_exe_folder(self):
        self.assertEqual(runner.effective_workdir("/games/tld/tld.exe"), "/games/tld")

    def test_explicit_workdir_wins(self):
        self.assertEqual(runner.effective_workdir("/games/tld/tld.exe", "/data"), "/data")


class PlanFromGameTest(unittest.TestCase):
    def test_defaults(self):
        settings = config.Settings(prefix_root="/tmp/prefixes", debug_logs=True)
        game = Game(title="My Game", exe_path="/games/mygame.exe", game_id="umu-7")
        plan = runner.LaunchPlan.from_game(game, settings)
        self.assertEqual(plan.prefix, "/tmp/prefixes/umu-7")
        self.assertTrue(plan.debug)
        self.assertEqual(plan.game_id, "umu-7")

    def test_explicit_prefix_wins(self):
        settings = config.Settings(prefix_root="/tmp/prefixes")
        game = Game(title="X", exe_path="/x.exe", prefix_path="/custom/prefix")
        plan = runner.LaunchPlan.from_game(game, settings)
        self.assertEqual(plan.prefix, "/custom/prefix")


if __name__ == "__main__":
    unittest.main()
