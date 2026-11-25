import unittest

from umulauncher.core import prefixes
from umulauncher.ui.dialogs import parse_env


class ParseEnvTest(unittest.TestCase):
    def test_basic(self):
        env, errors = parse_env("A=1\nB=two words\n")
        self.assertEqual(env, {"A": "1", "B": "two words"})
        self.assertEqual(errors, [])

    def test_comments_and_blanks(self):
        env, errors = parse_env("# comment\n\nA=1\n")
        self.assertEqual(env, {"A": "1"})
        self.assertEqual(errors, [])

    def test_export_prefix(self):
        env, _errors = parse_env("export DXVK_HUD=fps\n")
        self.assertEqual(env, {"DXVK_HUD": "fps"})

    def test_quotes_are_stripped(self):
        env, _errors = parse_env('A="x y"\nB=\'z\'\n')
        self.assertEqual(env, {"A": "x y", "B": "z"})

    def test_invalid_lines(self):
        env, errors = parse_env("broken\n=value\n1BAD=x\nGOOD=yes\n")
        self.assertEqual(env, {"GOOD": "yes"})
        self.assertEqual(len(errors), 3)

    def test_keeps_equals_in_value(self):
        env, _errors = parse_env("WINEDLLOVERRIDES=d3d11=n,b\n")
        self.assertEqual(env["WINEDLLOVERRIDES"], "d3d11=n,b")


class SafePrefixTest(unittest.TestCase):
    def test_rejects_root_and_home(self):
        self.assertFalse(prefixes.is_safe_prefix("/"))
        self.assertFalse(prefixes.is_safe_prefix(str(__import__("pathlib").Path.home())))
        self.assertFalse(prefixes.is_safe_prefix(""))
        self.assertFalse(prefixes.is_safe_prefix("relative/prefix"))

    def test_accepts_normal_prefix(self):
        self.assertTrue(prefixes.is_safe_prefix("/home/user/Games/umu/tld"))


if __name__ == "__main__":
    unittest.main()
