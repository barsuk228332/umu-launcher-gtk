import tempfile
import unittest
from pathlib import Path

from umulauncher.core import db
from umulauncher.core.db import Game


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "library.db"
        db.init(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_list_get(self):
        game = db.add_game(
            Game(
                title="The Long Dark",
                exe_path="/games/tld.exe",
                game_id="umu-3050",
                store="gog",
                launch_args=["-windowed"],
                env={"DXVK_HUD": "fps"},
                gamescope={"enabled": True, "width": 1920, "height": 1080},
                mangohud=True,
            ),
            self.path,
        )
        self.assertIsNotNone(game.id)

        games = db.list_games(self.path)
        self.assertEqual(len(games), 1)
        loaded = games[0]
        self.assertEqual(loaded.title, "The Long Dark")
        self.assertEqual(loaded.launch_args, ["-windowed"])
        self.assertEqual(loaded.env, {"DXVK_HUD": "fps"})
        self.assertTrue(loaded.gamescope_enabled)
        self.assertTrue(loaded.mangohud)
        self.assertEqual(loaded.game_id, "umu-3050")

    def test_update_and_delete(self):
        game = db.add_game(Game(title="A", exe_path="/a.exe"), self.path)
        game.title = "B"
        game.mangohud = True
        db.update_game(game, self.path)

        fresh = db.get_game(game.id, self.path)
        self.assertEqual(fresh.title, "B")
        self.assertTrue(fresh.mangohud)

        db.delete_game(game.id, self.path)
        self.assertIsNone(db.get_game(game.id, self.path))

    def test_playtime_accumulates(self):
        game = db.add_game(Game(title="A", exe_path="/a.exe"), self.path)
        db.add_playtime(game.id, 60, self.path)
        db.add_playtime(game.id, 120, self.path)
        fresh = db.get_game(game.id, self.path)
        self.assertEqual(fresh.playtime_sec, 180)
        self.assertTrue(fresh.last_played)

    def test_sorted_by_title(self):
        db.add_game(Game(title="Zeta", exe_path="/z.exe"), self.path)
        db.add_game(Game(title="alpha", exe_path="/a.exe"), self.path)
        titles = [game.title for game in db.list_games(self.path)]
        self.assertEqual(titles, ["alpha", "Zeta"])


if __name__ == "__main__":
    unittest.main()
