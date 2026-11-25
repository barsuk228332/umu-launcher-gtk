import tempfile
import unittest
from pathlib import Path
from unittest import mock

from umulauncher.core import desktop
from umulauncher.core.db import Game


class QuoteExecTest(unittest.TestCase):
    def test_simple_argument_is_not_quoted(self):
        self.assertEqual(desktop.quote_exec("/usr/bin/umulauncher"), "/usr/bin/umulauncher")

    def test_spaces_are_quoted(self):
        self.assertEqual(desktop.quote_exec("/games/My Game/game.exe"), '"/games/My Game/game.exe"')

    def test_special_characters_are_escaped(self):
        self.assertEqual(desktop.quote_exec('a$b"c'), '"a\\$b\\"c"')

    def test_empty_argument(self):
        self.assertEqual(desktop.quote_exec(""), '""')


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.apps = Path(self.tmp.name)
        self.game = Game(
            id=7,
            title="The Long Dark",
            exe_path="/games/tld.exe",
            workdir="/games",
            cover_path="/covers/7.jpg",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_creates_desktop_file(self):
        with mock.patch.object(desktop.config, "APPLICATIONS_DIR", self.apps), \
             mock.patch.object(desktop.shutil, "which", return_value=None):
            path = desktop.export(self.game)
        self.assertTrue(path.is_file())
        content = path.read_text()
        self.assertIn("Type=Application", content)
        self.assertIn("Name=The Long Dark", content)
        self.assertIn("Icon=/covers/7.jpg", content)
        self.assertIn("--run", content)
        self.assertIn("PYTHONPATH=", content)
        self.assertIn("Categories=Game;", content)

    def test_uses_console_script_when_available(self):
        with mock.patch.object(desktop.config, "APPLICATIONS_DIR", self.apps), \
             mock.patch.object(desktop.shutil, "which", return_value="/usr/bin/umulauncher"):
            path = desktop.export(self.game)
        exec_line = next(line for line in path.read_text().splitlines() if line.startswith("Exec="))
        self.assertEqual(exec_line, "Exec=/usr/bin/umulauncher --run 7")

    def test_remove(self):
        with mock.patch.object(desktop.config, "APPLICATIONS_DIR", self.apps):
            path = desktop.export(self.game)
            self.assertTrue(desktop.remove(7))
            self.assertFalse(path.exists())
            self.assertFalse(desktop.remove(7))


if __name__ == "__main__":
    unittest.main()
