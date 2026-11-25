import unittest

from umulauncher.core import umudb

CSV_FIXTURE = """TITLE,STORE,CODENAME,UMU_ID,COMMON ACRONYM (Optional),NOTE (Optional),EXE_STRINGS (Optional)
The Long Dark,gog,longdark,umu-3050,tld,,tld.exe
The Long Dark,steam,longdark,umu-3050,tld,,
Cyberpunk 2077,gog,cyberpunk,umu-1091500,cp77,,
Disco Elysium,egs,disco,umu-632470,de,,
Star Citizen,,starcitizen,umu-starcitizen,sc,Rsi Launcher,
"""


class UmuDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.entries = umudb.load_text(CSV_FIXTURE)

    def test_parse(self):
        self.assertEqual(len(self.entries), 5)
        first = self.entries[0]
        self.assertEqual(first.title, "The Long Dark")
        self.assertEqual(first.umu_id, "umu-3050")
        self.assertEqual(first.store, "gog")
        self.assertEqual(first.acronym, "tld")

    def test_search_exact(self):
        results = umudb.search("The Long Dark", self.entries)
        self.assertEqual(results[0].umu_id, "umu-3050")

    def test_search_case_and_punctuation(self):
        results = umudb.search("the long dark", self.entries)
        self.assertEqual(results[0].umu_id, "umu-3050")

    def test_search_acronym(self):
        results = umudb.search("cp77", self.entries)
        self.assertEqual(results[0].title, "Cyberpunk 2077")

    def test_search_empty(self):
        self.assertEqual(umudb.search("", self.entries), [])

    def test_best_match(self):
        best = umudb.best_match("Disco Elysium", self.entries)
        self.assertEqual(best.umu_id, "umu-632470")

    def test_no_match(self):
        self.assertEqual(umudb.search("Totally Unknown Game", self.entries), [])

    def test_match_by_exe(self):
        results = umudb.match_by_exe("TLD.exe", self.entries)
        self.assertTrue(results)
        self.assertEqual(results[0].umu_id, "umu-3050")

    def test_label(self):
        self.assertEqual(self.entries[0].label, "The Long Dark [gog]")


if __name__ == "__main__":
    unittest.main()
