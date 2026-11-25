import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from umulauncher.core import proton_releases


def _asset(name: str, size: int = 100, url: str | None = None) -> dict:
    return {
        "name": name,
        "size": size,
        "browser_download_url": url or f"https://example.invalid/{name}",
    }


def _release(tag: str, assets: list[dict], **extra) -> dict:
    item = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "published_at": "2026-11-20T12:00:00Z",
        "assets": assets,
    }
    item.update(extra)
    return item


class ParseReleasesTest(unittest.TestCase):
    def payload(self) -> list[dict]:
        return [
            _release(
                "GE-Proton11-14",
                [
                    _asset("GE-Proton11-14-aarch64.sha512sum", 160),
                    _asset("GE-Proton11-14-aarch64.tar.gz", 682442196),
                    _asset("GE-Proton11-14-x86_64.sha512sum", 159),
                    _asset("GE-Proton11-14-x86_64.tar.gz", 598620532),
                ],
            )
        ]

    def test_picks_host_architecture_and_clean_name(self):
        releases = proton_releases.parse_releases(self.payload(), "GE-Proton", machine="x86_64")
        self.assertEqual(len(releases), 1)
        release = releases[0]
        self.assertEqual(release.name, "GE-Proton11-14")
        self.assertEqual(release.archive_name, "GE-Proton11-14-x86_64.tar.gz")
        self.assertEqual(release.size, 598620532)
        self.assertIn("x86_64.sha512sum", release.checksum_url)

    def test_picks_aarch64(self):
        releases = proton_releases.parse_releases(self.payload(), "GE-Proton", machine="aarch64")
        release = releases[0]
        self.assertEqual(release.name, "GE-Proton11-14")
        self.assertEqual(release.archive_name, "GE-Proton11-14-aarch64.tar.gz")

    def test_skips_drafts_prereleases_and_releases_without_assets(self):
        payload = [
            _release("draft", [_asset("GE-Proton1.tar.gz")], draft=True),
            _release("pre", [_asset("GE-Proton2.tar.gz")], prerelease=True),
            _release("nofiles", [_asset("GE-Proton3.sha512sum")]),
            _release("ok", [_asset("GE-Proton4.tar.gz")]),
        ]
        releases = proton_releases.parse_releases(payload, "GE-Proton", machine="x86_64")
        self.assertEqual([release.name for release in releases], ["GE-Proton4"])

    def test_rejects_non_list_payload(self):
        with self.assertRaises(proton_releases.ProtonError):
            proton_releases.parse_releases({}, "GE-Proton")


class MultiSourceTest(unittest.TestCase):
    def test_cachyos_prefers_generic_x86_64_over_v3_and_arm64(self):
        payload = [
            _release(
                "cachyos-11.0-20261015-slr",
                [
                    _asset("proton-cachyos-11.0-20261015-slr-arm64.sha512sum"),
                    _asset("proton-cachyos-11.0-20261015-slr-arm64.tar.xz"),
                    _asset("proton-cachyos-11.0-20261015-slr-x86_64.sha512sum"),
                    _asset("proton-cachyos-11.0-20261015-slr-x86_64.tar.xz"),
                    _asset("proton-cachyos-11.0-20261015-slr-x86_64_v3.tar.xz"),
                ],
            )
        ]
        releases = proton_releases.parse_releases(payload, "Proton-CachyOS", machine="x86_64")
        self.assertEqual(len(releases), 1)
        release = releases[0]
        self.assertEqual(release.source, "Proton-CachyOS")
        self.assertEqual(release.name, "proton-cachyos-11.0-20261015-slr")
        self.assertEqual(release.archive_name, "proton-cachyos-11.0-20261015-slr-x86_64.tar.xz")

    def test_salkim_uses_wineland_asset_names(self):
        payload = [
            _release(
                "wineland-11.0-20261124",
                [
                    _asset("proton-wineland-11.0-20261124-x86_64.sha512sum"),
                    _asset("proton-wineland-11.0-20261124-x86_64.tar.xz"),
                    _asset("proton-wineland-11.0-20261124-x86_64_wow64.tar.xz"),
                ],
            )
        ]
        releases = proton_releases.parse_releases(payload, "Proton Salkim", machine="x86_64")
        self.assertEqual(releases[0].source, "Proton Salkim")
        self.assertEqual(releases[0].name, "proton-wineland-11.0-20261124")
        self.assertTrue(releases[0].archive_name.endswith("-x86_64.tar.xz"))

    def test_dwproton_assets(self):
        payload = [
            _release(
                "dwproton-11.0-17",
                [
                    _asset("dwproton-11.0-17-x86_64.sha512sum"),
                    _asset("dwproton-11.0-17-x86_64.tar.xz"),
                    _asset("dwproton-11.0-17-x86_64.tar.xz.torrent"),
                ],
            )
        ]
        releases = proton_releases.parse_releases(payload, "DWProton", machine="x86_64")
        self.assertEqual(releases[0].name, "dwproton-11.0-17")

    def test_forgejo_release_url_is_used(self):
        with mock.patch.object(proton_releases, "_fetch_json", return_value=[]) as fetch:
            proton_releases.fetch_releases("DWProton", limit=3)
        url = fetch.call_args.args[0]
        self.assertIn("dawn.wine/api/v1/repos/dawn-winery/dwproton", url)
        self.assertIn("limit=3", url)

    def test_github_release_url_is_used(self):
        with mock.patch.object(proton_releases, "_fetch_json", return_value=[]) as fetch:
            proton_releases.fetch_releases("Proton-CachyOS", limit=3)
        url = fetch.call_args.args[0]
        self.assertIn("api.github.com/repos/CachyOS/proton-cachyos", url)
        self.assertIn("per_page=3", url)

    def _fake_fetch(self, source, limit=4, timeout=20.0):
        spec = proton_releases.resolve_source(source)
        if spec.label == "DWProton":
            raise proton_releases.ProtonError("host is down")
        return [
            proton_releases.ProtonRelease(
                source=spec.label,
                name=spec.label,
                tag=spec.label,
                archive_name=f"{spec.label}.tar.gz",
                archive_url="https://example.invalid/build.tar.gz",
            )
        ]

    def test_fetch_available_keeps_source_order_and_skips_failures(self):
        with mock.patch.object(
            proton_releases, "fetch_releases", side_effect=self._fake_fetch
        ):
            releases = proton_releases.fetch_available(limit=1)
        self.assertEqual(
            [release.source for release in releases],
            ["GE-Proton", "UMU-Proton", "Proton-CachyOS", "Proton Salkim"],
        )

    def test_fetch_by_source_keeps_failed_source_visible(self):
        with mock.patch.object(
            proton_releases, "fetch_releases", side_effect=self._fake_fetch
        ):
            results = proton_releases.fetch_by_source(limit=1)
        self.assertEqual(
            [source.label for source, _items, _error in results],
            [source.label for source in proton_releases.SOURCES],
        )
        errors = {source.label: error for source, _items, error in results}
        self.assertEqual(errors["DWProton"], "host is down")
        self.assertEqual(errors["GE-Proton"], "")


class ChecksumTest(unittest.TestCase):
    def test_matches_archive_name(self):
        text = (
            "aaa  GE-Proton11-14-aarch64.tar.gz\n"
            "bbb  GE-Proton11-14-x86_64.tar.gz\n"
        )
        self.assertEqual(
            proton_releases.checksum_value(text, "GE-Proton11-14-x86_64.tar.gz"),
            "bbb",
        )

    def test_falls_back_to_first_digest(self):
        text = "ccc  some-other-name.tar.gz\n"
        self.assertEqual(
            proton_releases.checksum_value(text, "GE-Proton11-14.tar.gz"),
            "ccc",
        )

    def test_ignores_comments_and_empty_lines(self):
        self.assertEqual(
            proton_releases.checksum_value("# header\n\nddd  file.tar.gz\n", "file.tar.gz"),
            "ddd",
        )


class SafeExtractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_rejects_path_traversal(self):
        member = tarfile.TarInfo("../evil")
        with self.assertRaises(proton_releases.ProtonError):
            proton_releases._safe_members([member], self.root / "extract")

    def test_rejects_absolute_path(self):
        member = tarfile.TarInfo("/etc/passwd")
        with self.assertRaises(proton_releases.ProtonError):
            proton_releases._safe_members([member], self.root / "extract")

    def test_extracts_safe_archive(self):
        archive = self.root / "build.tar.gz"
        payload = self.root / "payload"
        payload.mkdir()
        (payload / "proton").write_text("#!/bin/sh\n")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(payload, arcname="GE-Proton9-9")
        target = self.root / "extract"
        target.mkdir()
        proton_releases._safe_extract(archive, target)
        self.assertTrue((target / "GE-Proton9-9" / "proton").is_file())


class DownloadInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.installed = self.root / "installed"

        self.archive = self.root / "GE-Proton9-9.tar.gz"
        source = self.root / "src" / "GE-Proton9-9"
        (source / "files" / "share" / "default_pfx").mkdir(parents=True)
        (source / "proton").write_text("#!/bin/sh\n")
        with tarfile.open(self.archive, "w:gz") as tar:
            tar.add(source, arcname="GE-Proton9-9")

        digest = proton_releases.sha512_file(self.archive)
        self.checksum = self.root / "GE-Proton9-9.sha512sum"
        self.checksum.write_text(f"{digest}  {self.archive.name}\n")

        self.release = proton_releases.ProtonRelease(
            source="GE-Proton",
            name="GE-Proton9-9",
            tag="GE-Proton9-9",
            archive_name=self.archive.name,
            archive_url=self.archive.as_uri(),
            checksum_url=self.checksum.as_uri(),
            size=self.archive.stat().st_size,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_downloads_verifies_and_installs(self):
        progress: list[tuple[int, int]] = []
        with mock.patch.object(proton_releases.config, "CACHE_DIR", self.cache):
            target = proton_releases.download_install(
                self.release,
                install_dir=self.installed,
                on_progress=lambda done, total: progress.append((done, total)),
            )
        self.assertTrue((target / "proton").is_file())
        self.assertTrue((target / "files" / "share" / "default_pfx").is_dir())
        self.assertFalse((self.cache / "proton-downloads" / (self.archive.name + ".part")).exists())
        self.assertTrue(progress)
        self.assertEqual(progress[-1][0], progress[-1][1])

    def test_refuses_existing_install(self):
        self.installed.mkdir()
        (self.installed / self.release.name).mkdir()
        with mock.patch.object(proton_releases.config, "CACHE_DIR", self.cache):
            with self.assertRaises(proton_releases.ProtonError):
                proton_releases.download_install(self.release, install_dir=self.installed)

    def test_cancel_keeps_partial_file(self):
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(proton_releases.config, "CACHE_DIR", self.cache):
            with self.assertRaises(proton_releases.DownloadCancelled):
                proton_releases.download_install(
                    self.release,
                    install_dir=self.installed,
                    cancel=cancel,
                )
        self.assertTrue(
            (self.cache / "proton-downloads" / (self.archive.name + ".part")).is_file()
        )


if __name__ == "__main__":
    unittest.main()
