import unittest

from umulauncher.core import config


class SlugifyTest(unittest.TestCase):
    def test_spaces_become_dashes(self):
        self.assertEqual(config.slugify("The Long Dark"), "the-long-dark")

    def test_keeps_cyrillic(self):
        self.assertEqual(config.slugify("Моя Игра"), "моя-игра")

    def test_strips_punctuation(self):
        self.assertEqual(config.slugify("Cyberpunk 2077™: Ultimate!"), "cyberpunk-2077-ultimate")

    def test_fallback(self):
        self.assertEqual(config.slugify("!!!"), "game")
        self.assertEqual(config.slugify("", fallback="umu-default"), "umu-default")

    def test_path_traversal_is_neutralised(self):
        self.assertNotIn("/", config.slugify("../../etc/passwd"))
        self.assertNotIn("..", config.slugify("../../etc/passwd"))


class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        settings = config.Settings()
        self.assertEqual(settings.language, "system")
        self.assertFalse(settings.debug_logs)
        self.assertTrue(settings.steam_cdn_fallback)

    def test_prefix_root_expands_home(self):
        settings = config.Settings(prefix_root="~/Games/umu")
        self.assertTrue(str(settings.prefix_root_path).startswith("/"))


if __name__ == "__main__":
    unittest.main()
