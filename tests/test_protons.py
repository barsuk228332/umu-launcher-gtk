import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from umulauncher.core import protons


class ProtonDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.compat = self.root / "compatibilitytools.d"
        self.compat.mkdir()
        self.common = self.root / "steamapps" / "common"
        self.common.mkdir(parents=True)

        self._make_proton(self.compat / "GE-Proton9-20")
        self._make_proton(self.common / "Proton - Experimental")
        (self.compat / "not-a-proton").mkdir()

    def _make_proton(self, path: Path) -> None:
        path.mkdir(parents=True)
        proton = path / "proton"
        proton.write_text("#!/bin/sh\n")
        os.chmod(proton, 0o755)
        (path / "files" / "share" / "default_pfx").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_discover_finds_builds(self):
        with mock.patch.object(protons, "library_roots", return_value=[self.root]), \
             mock.patch.object(protons, "extra_proton_dirs", return_value=[]):
            builds = protons.discover()
        names = [build.name for build in builds]
        self.assertIn("GE-Proton9-20", names)
        self.assertIn("Proton - Experimental", names)
        self.assertNotIn("not-a-proton", names)

    def test_auto_entries_come_first(self):
        with mock.patch.object(protons, "library_roots", return_value=[self.root]), \
             mock.patch.object(protons, "extra_proton_dirs", return_value=[]):
            builds = protons.discover()
        self.assertEqual(builds[0].name, "UMU-Proton (default)")
        self.assertEqual(builds[0].env_value(), None)
        self.assertEqual(builds[1].name, "GE-Proton (latest, auto-download)")
        self.assertEqual(builds[1].env_value(), "GE-Proton")

    def test_no_duplicates(self):
        with mock.patch.object(protons, "library_roots", return_value=[self.root, self.root]), \
             mock.patch.object(protons, "extra_proton_dirs", return_value=[]):
            builds = protons.discover()
        paths = [build.path for build in builds if build.path]
        self.assertEqual(len(paths), len(set(paths)))

    def test_incomplete_build_is_hidden(self):
        incomplete = self.compat / "Broken Proton"
        incomplete.mkdir()
        (incomplete / "proton").write_text("#!/bin/sh\n")
        with mock.patch.object(protons, "library_roots", return_value=[self.root]), \
             mock.patch.object(protons, "extra_proton_dirs", return_value=[]):
            names = [build.name for build in protons.discover()]
            names_all = [build.name for build in protons.discover(include_incomplete=True)]
        self.assertNotIn("Broken Proton", names)
        self.assertIn("Broken Proton", names_all)

    def test_find_build(self):
        with mock.patch.object(protons, "library_roots", return_value=[self.root]), \
             mock.patch.object(protons, "extra_proton_dirs", return_value=[]):
            builds = protons.discover()
        found = protons.find_build(builds, str(self.compat / "GE-Proton9-20"))
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "GE-Proton9-20")
        self.assertIsNone(protons.find_build(builds, "/nope"))


if __name__ == "__main__":
    unittest.main()
