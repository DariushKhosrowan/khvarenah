"""Unit tests for the Khvarenah self-updater and clean-IP profile rewriting."""

from __future__ import annotations

import unittest

from khvarenah import updater
from khvarenah.vless import VlessProfile


class VersionComparisonTest(unittest.TestCase):
    def test_normalize_simple(self):
        self.assertEqual(updater._normalize_version("0.1.0"), (0, 1, 0))
        self.assertEqual(updater._normalize_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater._normalize_version("2.0"), (2, 0, 0))
        self.assertEqual(updater._normalize_version(""), (0, 0, 0))

    def test_comparison(self):
        self.assertTrue(updater._normalize_version("1.0.0") >
                        updater._normalize_version("0.9.9"))
        self.assertFalse(updater._normalize_version("0.1.0") >
                         updater._normalize_version("0.1.0"))
        self.assertTrue(updater._normalize_version("1.10.0") >
                        updater._normalize_version("1.9.0"))


class CleanEndpointTest(unittest.TestCase):
    def setUp(self):
        self.prof = VlessProfile(uuid="11111111-2222-3333-4444-555555555555",
                                  address="my-vpn.myacc.workers.dev",
                                  name="vpn-edge")

    def test_share_link_uses_works(self):
        link = self.prof.share_link()
        self.assertTrue(link.startswith("vless://"))
        self.assertIn("my-vpn.myacc.workers.dev:443", link)


class WheelAssetTest(unittest.TestCase):
    def test_prefers_universal_wheel(self):
        assets = [
            {"name": "khvarenah-0.1.0-py3-none-any.whl", "url": "u1"},
            {"name": "khvarenah-0.1.0-cp312-cp312-linux_x86_64.whl", "url": "u2"},
        ]
        picked = updater._pick_wheel_asset(assets)
        self.assertEqual(picked["url"], "u1")

    def test_falls_back_to_any_wheel(self):
        assets = [
            {"name": "khvarenah-0.1.0-cp312-cp312-win_amd64.whl", "url": "u3"},
        ]
        picked = updater._pick_wheel_asset(assets)
        self.assertEqual(picked["url"], "u3")

    def test_no_wheel_returns_none(self):
        assets = [{"name": "khvarenah-0.1.0.tar.gz", "url": "u4"}]
        self.assertIsNone(updater._pick_wheel_asset(assets))


class CheckAndApplyTest(unittest.TestCase):
    def test_up_to_date(self):
        updater.latest_release = lambda *a, **k: {
            "tag": "v0.1.0", "version": (0, 1, 0),
            "tarball_url": "t", "assets": [],
        }
        updater.current_version = lambda: "0.1.0"
        ok, msg = updater.check_and_apply()
        self.assertFalse(ok)
        self.assertIn("Already on the latest version", msg)

    def test_no_release(self):
        updater.latest_release = lambda *a, **k: {}
        ok, msg = updater.check_and_apply()
        self.assertFalse(ok)
        self.assertIn("Could not reach GitHub", msg)

    def test_install_used_when_newer(self):
        updater.latest_release = lambda *a, **k: {
            "tag": "v0.2.0", "version": (0, 2, 0),
            "tarball_url": "t", "assets": [],
        }
        updater.current_version = lambda: "0.1.0"
        installed = {}
        updater._install_release = lambda rel, timeout=600: (
            installed.update(rel=rel, timeout=timeout) or (True, "Updated to v0.2.0"))
        ok, msg = updater.check_and_apply()
        self.assertTrue(ok)
        self.assertEqual(installed["rel"]["tag"], "v0.2.0")


if __name__ == "__main__":
    unittest.main()
