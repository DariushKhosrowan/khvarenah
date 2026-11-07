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


if __name__ == "__main__":
    unittest.main()
