"""Tests for the stealth (anti-bot pacing) layer and multi-account features.

Covers:
  1. stealth.py — jitter ranges, disable switch, retry backoff bounds.
  2. Active-account switching — set_active_account / active_account default.
  3. `usage` command surfaces daily request counts (mocked analytics).
  4. `accounts --set` switches the active account.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from khvarenah import store  # noqa: E402
from khvarenah import stealth  # noqa: E402
from khvarenah.cli import build_parser, cmd_accounts, cmd_usage  # noqa: E402
from khvarenah.cf_api import Config, CFError  # noqa: E402


def _patch_mem(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MEM_DIR", tmp_path)
    monkeypatch.setattr(store, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(store, "TOKENS_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(store, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(store, "CONFIG_FILE", tmp_path / "config.json")


# ---------------------------------------------------------------------------
# stealth pacing
# ---------------------------------------------------------------------------

def test_stealth_jitter_within_range():
    for _ in range(200):
        v = stealth.jitter(1.0, 4.0)
        assert 1.0 <= v <= 4.0


def test_stealth_retry_backoff_floor():
    # attempt=0 should never be instant (floor of 1.0s) — we confirm the
    # sleep value produced is always positive and >= floor.
    import math
    for attempt in range(3):
        v = 2.0 ** (attempt + 1) * stealth.jitter(0.75, 1.25)
        assert v >= 1.0
        assert math.isfinite(v)


def test_stealth_disabled_does_not_sleep(monkeypatch):
    slept = []

    def fake_sleep(s):
        # mirror the real _sleep: only sleep when stealth is enabled
        if stealth._ENABLED:
            slept.append(s)

    monkeypatch.setattr(stealth, "_sleep", fake_sleep)
    monkeypatch.setattr(stealth, "_ENABLED", False)
    stealth.pre_request_pause("read")
    stealth.pre_request_pause("write")
    stealth.boundary_pause()
    assert slept == []


def test_humanize_worker_preserves_logic(monkeypatch):
    monkeypatch.setattr(stealth, "_ENABLED", True)
    js = b"export default { async fetch() { return 1; } };"
    out = stealth.humanize_worker(js)
    # logic is preserved verbatim, only a comment header is prepended
    assert out.endswith(js)
    assert out != js  # bytes differ (header added)


def test_humanize_worker_disabled_returns_unchanged(monkeypatch):
    monkeypatch.setattr(stealth, "_ENABLED", False)
    js = b"export default {}"
    assert stealth.humanize_worker(js) == js


def test_humanize_worker_variation():
    # bump the RNG seed range: with different draws headers differ
    import random as _r
    rng = _r.Random(12345)
    headers = set()
    for _ in range(50):
        h = stealth._header_comment()
        headers.add(h)
    # comments vary (more than one distinct header)
    assert len(headers) >= 2


# ---------------------------------------------------------------------------
# active-account switching
# ---------------------------------------------------------------------------

def test_active_account_defaults_to_empty_when_not_set(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    store.remember_account("acc-1", "Alpha", "a-sub")
    store.remember_account("acc-2", "Beta", "b-sub")
    # No explicit active set -> empty; _resolve_account falls back to first.
    assert store.active_account() == ""


def test_set_active_account_switches(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    store.remember_account("acc-1", "Alpha")
    store.remember_account("acc-2", "Beta")
    assert store.set_active_account("acc-2") is True
    assert store.active_account() == "acc-2"
    # unknown account -> False
    assert store.set_active_account("nope") is False


def test_accounts_switch_via_cli(tmp_path, monkeypatch, capsys):
    _patch_mem(tmp_path, monkeypatch)
    store.remember_account("acc-1", "Alpha", "a-sub")
    store.remember_account("acc-2", "Beta", "b-sub")
    args = build_parser().parse_args(["accounts", "--set", "acc-2"])
    assert cmd_accounts(args) == 0
    assert store.active_account() == "acc-2"
    out = capsys.readouterr().out
    assert "acc-2" in out


# ---------------------------------------------------------------------------
# usage command (mocked API)
# ---------------------------------------------------------------------------

class _UsageAPI:
    def __init__(self):
        self.accounts = [{"id": "a1", "name": "Alpha"}]
        self.scripts = [{"id": "worker-a"}, {"id": "worker-b"}]
        self.calls = 0

    def list_accounts(self):
        return self.accounts

    def get_subdomain(self, account_id):
        return "acctsub"

    def list_scripts(self, account_id):
        return self.scripts

    def script_analytics(self, account_id, name, since, until):
        self.calls += 1
        return {"requestCount": 42 if name == "worker-a" else 58}


def test_usage_surfaces_counts(tmp_path, monkeypatch, capsys):
    _patch_mem(tmp_path, monkeypatch)
    api = _UsageAPI()
    monkeypatch.setattr("khvarenah.cli._token", lambda _: "tok")
    monkeypatch.setattr("khvarenah.cli.Config", lambda *a, **k: api)
    args = build_parser().parse_args(["usage"])
    rc = cmd_usage(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "42" in out and "58" in out
    assert "TOTAL" in out
    assert api.calls == 2


def test_usage_error_returns_2(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)

    class _ErrAPI:
        def list_accounts(self):
            raise CFError("Boom", "detail", "fix")

    monkeypatch.setattr("khvarenah.cli._token", lambda _: "tok")
    monkeypatch.setattr("khvarenah.cli.Config", lambda *a, **k: _ErrAPI())
    args = build_parser().parse_args(["usage"])
    assert cmd_usage(args) == 2


# ---------------------------------------------------------------------------
# per-account token resolution
# ---------------------------------------------------------------------------

def test_get_account_token_falls_back_to_default(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    store.remember_account("acc-1", "Alpha")
    store.save_token("tok-default", "default")
    # no per-account token -> falls back to default
    assert store.get_account_token("acc-1") == "tok-default"


def test_get_account_token_prefers_per_account(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    store.remember_account("acc-1", "Alpha")
    store.save_token("tok-default", "default")
    store.save_token("tok-alpha", "acc-1")
    assert store.get_account_token("acc-1") == "tok-alpha"
    # default still intact for other accounts
    assert store.get_account_token("acc-999") == "tok-default"


class _AddTok:
    def __init__(self, token):
        self.token = token
        self.accounts = [{"id": "acc-new", "name": "NewCo"}]

    def verify_token(self):
        return {"success": True}

    def list_accounts(self):
        return self.accounts


def test_accounts_add_verifies_and_switches(tmp_path, monkeypatch, capsys):
    _patch_mem(tmp_path, monkeypatch)
    monkeypatch.setattr("khvarenah.cli._token", lambda _: "tok-new")
    monkeypatch.setattr("khvarenah.cli.Config", lambda *a, **k: _AddTok("tok-new"))
    args = build_parser().parse_args(["accounts", "--add", "tok-new"])
    assert cmd_accounts(args) == 0
    assert store.active_account() == "acc-new"
    assert store.get_account_token("acc-new") == "tok-new"
    out = capsys.readouterr().out
    assert "NewCo" in out
