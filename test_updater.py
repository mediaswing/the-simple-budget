"""Unit tests for the pure/deterministic parts of updater.py: version
parsing/compare and the GitHub Releases response -> ReleaseInfo mapping.
No network access -- ``urllib.request.urlopen`` is stubbed.

Run with:  python3 -m unittest -v test_updater
"""
import io
import json
import os
import unittest
from unittest import mock

import updater


def fake_response(payload: dict):
    """A context-manager stub that behaves enough like the object
    urllib.request.urlopen returns for json.load(resp) to work."""
    body = json.dumps(payload).encode("utf-8")
    return mock.MagicMock(
        __enter__=mock.Mock(return_value=io.BytesIO(body)),
        __exit__=mock.Mock(return_value=False),
    )


class ParseVersionTests(unittest.TestCase):
    def test_leading_v(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))

    def test_no_leading_v(self):
        self.assertEqual(updater.parse_version("0.5.2"), (0, 5, 2))

    def test_compares_as_expected(self):
        self.assertLess(updater.parse_version("0.5.2"), updater.parse_version("0.5.3"))
        self.assertLess(updater.parse_version("0.5.2"), updater.parse_version("0.10.0"))

    def test_prerelease_suffix_is_dropped_not_merged(self):
        self.assertEqual(updater.parse_version("v1.2.3-rc1"), (1, 2, 3))


class CompareVersionsTests(unittest.TestCase):
    def test_pads_shorter_tuple_before_comparing(self):
        self.assertEqual(updater._compare_versions((1, 3), (1, 3, 0)), 0)
        self.assertEqual(updater._compare_versions((1, 3, 0), (1, 3)), 0)

    def test_still_orders_correctly(self):
        self.assertEqual(updater._compare_versions((1, 3, 1), (1, 3)), 1)
        self.assertEqual(updater._compare_versions((1, 2), (1, 3)), -1)


class CheckLatestReleaseTests(unittest.TestCase):
    def test_no_update_when_already_current(self):
        payload = {"tag_name": "v0.5.2", "body": "", "assets": []}
        with mock.patch("urllib.request.urlopen", return_value=fake_response(payload)):
            self.assertIsNone(updater.check_latest_release("0.5.2"))

    def test_no_update_when_remote_is_older(self):
        payload = {"tag_name": "v0.5.0", "body": "", "assets": []}
        with mock.patch("urllib.request.urlopen", return_value=fake_response(payload)):
            self.assertIsNone(updater.check_latest_release("0.5.2"))

    def test_update_available_with_matching_asset(self):
        payload = {
            "tag_name": "v0.6.0",
            "body": "New stuff",
            "assets": [
                {"name": "TheSimpleBudget-macos.zip",
                 "browser_download_url": "https://example.com/macos.zip"},
                {"name": "TheSimpleBudget-windows.zip",
                 "browser_download_url": "https://example.com/windows.zip"},
            ],
        }
        with mock.patch("urllib.request.urlopen", return_value=fake_response(payload)), \
             mock.patch("updater.sys") as fake_sys:
            fake_sys.platform = "darwin"
            release = updater.check_latest_release("0.5.2")
        self.assertIsNotNone(release)
        self.assertEqual(release.version, "0.6.0")
        self.assertEqual(release.version_tuple, (0, 6, 0))
        self.assertEqual(release.notes, "New stuff")
        self.assertEqual(release.asset_url, "https://example.com/macos.zip")

    def test_update_available_without_matching_asset(self):
        payload = {
            "tag_name": "v0.6.0",
            "body": "",
            "assets": [{"name": "TheSimpleBudget-windows.zip",
                        "browser_download_url": "https://example.com/windows.zip"}],
        }
        with mock.patch("urllib.request.urlopen", return_value=fake_response(payload)), \
             mock.patch("updater.sys") as fake_sys:
            fake_sys.platform = "darwin"
            release = updater.check_latest_release("0.5.2")
        self.assertIsNotNone(release)
        self.assertIsNone(release.asset_url)

    def test_no_releases_yet(self):
        with mock.patch("urllib.request.urlopen", return_value=fake_response({})):
            self.assertIsNone(updater.check_latest_release("0.5.2"))

    def test_network_error_returns_none(self):
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                         side_effect=urllib.error.URLError("offline")):
            self.assertIsNone(updater.check_latest_release("0.5.2"))


class SafeExtractTests(unittest.TestCase):
    def test_extracts_normal_archive(self):
        import tempfile
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "update.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("TheSimpleBudget/file.txt", "hello")
            dest = os.path.join(tmp, "out")
            updater._safe_extract(zip_path, dest)
            with open(os.path.join(dest, "TheSimpleBudget", "file.txt")) as f:
                self.assertEqual(f.read(), "hello")

    def test_rejects_path_traversal_entry(self):
        import tempfile
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "evil.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("../../evil.txt", "pwned")
            dest = os.path.join(tmp, "out")
            with self.assertRaises(OSError):
                updater._safe_extract(zip_path, dest)


if __name__ == "__main__":
    unittest.main()
