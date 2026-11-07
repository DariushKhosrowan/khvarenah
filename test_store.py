"""Unit tests for Khvarenah persistent memory (store module)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from khvarenah import store
from khvarenah.vless import VlessProfile


def _fake_profile(name="cf-worker-edge", host="my-vpn.myacc.workers.dev"):
    return VlessProfile(
        uuid="11111111-2222-3333-4444-555555555555",
        address=host,
        name=name,
    )


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        store.MEM_DIR = Path(self._tmp.name)
        store.HISTORY_FILE = store.MEM_DIR / "history.json"
        store.TOKENS_FILE = store.MEM_DIR / "tokens.json"
        store.CONFIG_FILE = store.MEM_DIR / "config.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_remember_and_list_vless(self):
        store.remember_vless(_fake_profile())
        store.remember_vless(_fake_profile(name="cf-worker-clean"),
                             clean_ip=True)
        entries = store.list_vless()
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0]["link"].startswith("vless://"))
        # newest first
        self.assertGreaterEqual(entries[0]["epoch"], entries[1]["epoch"])

    def test_remember_caps_at_500(self):
        for i in range(505):
            store.remember_vless(_fake_profile(name=f"p{i}"))
        self.assertEqual(len(store.list_vless(limit=10000)), 500)

    def test_token_save_and_get(self):
        store.save_token("CF_TOKEN_123", account_id="acc1")
        self.assertEqual(store.get_token("acc1"), "CF_TOKEN_123")
        # default label
        store.save_token("TOKEN_DEFAULT")
        self.assertEqual(store.get_token(), "TOKEN_DEFAULT")

    def test_last_vless_prefers_deployed_base(self):
        # newest record is a clean-IP entry, older one is the base deployment
        store.remember_vless(_fake_profile(name="base-worker"), clean_ip=False)
        store.remember_vless(_fake_profile(name="clean-worker"),
                             clean_ip=True)
        rec = store.last_vless()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["name"], "base-worker")
        self.assertFalse(rec["clean_ip"])
        # fallback: with only clean-IP entries, return the newest one
        store.clear_history()
        store.remember_vless(_fake_profile(name="clean-worker"),
                             clean_ip=True)
        rec = store.last_vless()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["name"], "clean-worker")
        # empty history -> None
        store.clear_history()
        self.assertIsNone(store.last_vless())

    def test_last_vless_skips_empty_address_records(self):
        # A saved record with an empty host (e.g. wizard saved before the host
        # was known) must never be chosen as the "deployed config" — it can't
        # be scanned and would falsely trigger "No deployed config available".
        store.remember_vless(_fake_profile(name="base-worker"))  # older, valid
        # record an empty-address entry as the NEWEST base (non-clean) record
        empty = VlessProfile(uuid="u-empty", address="", name="empty-saved")
        store.remember_vless(empty)
        rec = store.last_vless()
        self.assertIsNotNone(rec)
        self.assertTrue(rec["address"])
        self.assertEqual(rec["name"], "base-worker")

        # even with prefer_deployed=False, an empty record is never returned
        rec = store.last_vless(prefer_deployed=False)
        self.assertIsNotNone(rec)
        self.assertTrue(rec["address"])

        # only empty-address records exist -> None (restore shows the error)
        store.clear_history()
        store.remember_vless(VlessProfile(uuid="u1", address="", name="a"))
        store.remember_vless(VlessProfile(uuid="u2", address="", name="b"))
        self.assertIsNone(store.last_vless())
        self.assertIsNone(store.last_vless(prefer_deployed=False))

    def test_last_vless_clean_ip_prefers_older_base_over_newer_empty(self):
        # newest is a clean-IP entry, but the only base has an empty address
        # → must fall back to the newest *usable* record (the clean-IP one).
        store.remember_vless(VlessProfile(uuid="u-base", address="", name="base"))
        store.remember_vless(_fake_profile(name="clean-worker"), clean_ip=True)
        rec = store.last_vless()
        self.assertIsNotNone(rec)
        self.assertTrue(rec["address"])
        self.assertEqual(rec["name"], "clean-worker")

    def test_clear(self):
        store.save_token("X")
        store.remember_vless(_fake_profile())
        self.assertEqual(store.clear_tokens(), None)
        self.assertEqual(store.stored_tokens(), {})
        store.clear_history()
        self.assertEqual(store.list_vless(), [])


if __name__ == "__main__":
    unittest.main()
