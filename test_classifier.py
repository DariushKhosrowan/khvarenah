"""Unit tests for the Khvarenah error classifier and guard logic.

Run:  .venv/bin/python -m pytest test_classifier.py -q
(or: python -m unittest test_classifier.py)
"""
import sys
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from khvarenah.deploy_wrangler import _classify  # noqa: E402
from khvarenah.worker_bundle import safe_worker_name  # noqa: E402
from khvarenah.vless import VlessProfile  # noqa: E402


class ClassifyTests(unittest.TestCase):
    def assert_hint(self, raw, fragment):
        msg = _classify(raw).lower()
        self.assertIn(fragment.lower(), msg, f"expected {fragment!r} in {msg!r}")

    def test_1101_is_worker_exception_not_permission(self):
        self.assert_hint("error 1101: Worker threw exception", "worker")
        self.assertNotIn("permission", _classify("error 1101").lower())

    def test_permission(self):
        self.assert_hint("permission denied 6003", "permission")

    def test_auth(self):
        self.assert_hint("Authentication failed 401", "invalid/expired")

    def test_rate_limit(self):
        self.assert_hint("Too many requests 429", "rate-limited")

    def test_network(self):
        self.assert_hint("ECONNRESET", "network")

    def test_no_route(self):
        self.assert_hint("No route 10404", "no route")

    def test_syntax(self):
        self.assert_hint("SyntaxError: Unexpected token", "bundle")


class NameTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(safe_worker_name("My VPN!"), "my-vpn")
        self.assertEqual(safe_worker_name("UPPER Case"), "upper-case")

    def test_truncate(self):
        self.assertEqual(len(safe_worker_name("a" * 80)), 64)

    def test_empty_default(self):
        self.assertEqual(safe_worker_name("   "), "cf-worker-proxy")


class VlessTests(unittest.TestCase):
    BRAND_DOMAIN = "khosrowan.ir"
    BRAND_PRODUCT = "khvarenah"
    FULL_HOST = "vpn." + BRAND_DOMAIN

    def setUp(self):
        self.p = VlessProfile(
            uuid="123e4567-e89b-12d3-a456-426614174000",
            address=self.FULL_HOST, name=self.BRAND_PRODUCT,
        )

    def test_share_link_shape(self):
        link = self.p.share_link()
        self.assertTrue(link.startswith("vless://"))
        self.assertIn(f"@{self.FULL_HOST}:443", link)
        self.assertIn("encryption=none", link)

    def test_advertises_both_brands(self):
        """The generated config must advertise both the Khosrowan domain and
        the Khvarenah product brand."""
        link = self.p.share_link()
        self.assertIn("khosrowan.ir", link)
        self.assertIn("khvarenah", link)
        self.assertIn(f"#{self.BRAND_PRODUCT}", link)

    def test_encryption_none_present(self):
        self.assertIn("encryption=none", self.p.share_link())

    def test_xray_encryption_none(self):
        self.assertIn('"encryption": "none"', self.p.xray_client_json())

    def test_xray_uses_khosrowan_domain(self):
        xray = self.p.xray_client_json()
        self.assertIn("khosrowan.ir", xray)
        self.assertIn(f"\"address\": \"{self.FULL_HOST}\"", xray)
        self.assertIn(f"\"serverName\": \"{self.FULL_HOST}\"", xray)


if __name__ == "__main__":
    unittest.main()
