"""Tests for the autopilot UUID threading + account-name worker naming + memory regressions.

Covers the fixes for:
  1. `khvarenah autopilot` previously generated a fresh UUID inside deploy and
     never passed it to the clean/scan step → "—uuid required" scanner error.
  2. Worker name should default to the CF account name (never a "vpn" label).
  3. Memory now remembers accounts so accounts are never re-typed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from khvarenah import store  # noqa: E402
from khvarenah import worker_bundle as wb  # noqa: E402
from khvarenah.cli import (  # noqa: E402
    _resolve_account, cmd_autopilot, cmd_clean, build_parser)
from khvarenah.cf_api import CFError  # noqa: E402
from khvarenah.vless import VlessProfile  # noqa: E402


# ---------------------------------------------------------------------------
# worker naming (account name → worker name)
# ---------------------------------------------------------------------------

def test_worker_name_from_account():
    assert wb.worker_name_from_account({"name": "Dariush Khosrowan"}) == "dariush-khosrowan"
    assert wb.worker_name_from_account({"name": "Amir"}) == "amir"
    # account names are used verbatim (normalized) — incl. non-ascii stripped
    assert wb.worker_name_from_account({"name": "Khovarenah"}) == "khovarenah"


def _patch_mem(tmp_path, monkeypatch, store=store):
    """Point every store file constant at tmp_path (they're computed at import)."""
    monkeypatch.setattr(store, "MEM_DIR", tmp_path)
    monkeypatch.setattr(store, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(store, "TOKENS_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(store, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(store, "CONFIG_FILE", tmp_path / "config.json")


def test_worker_name_falls_back_to_registry(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    store.remember_account("acc-1", "MyCloudAccount", "acctsub")
    assert wb.worker_name_from_account(None) == "mycloudaccount"


def test_worker_name_fallback_never_vpn(monkeypatch):
    # No accounts at all → fallback default must be non-empty and never a
    # "vpn" label.
    import khvarenah.store as store_mod
    monkeypatch.setattr(store_mod, "MEM_DIR", Path("/nonexistent-mem"))
    name = wb.worker_name_from_account(None)
    assert name
    assert "vpn" not in name


# ---------------------------------------------------------------------------
# memory / accounts
# ---------------------------------------------------------------------------

def test_remember_and_list_accounts(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    store.remember_account("acc-1", "Alpha", "a-sub")
    store.remember_account("acc-2", "Beta", "b-sub")
    accs = store.list_accounts()
    assert accs["acc-1"]["name"] == "Alpha"
    assert accs["acc-1"]["subdomain"] == "a-sub"
    assert accs["acc-2"]["subdomain"] == "b-sub"
    assert store.account_label("acc-1") == "Alpha"


def test_history_caps_at_500(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    for i in range(510):
        store.remember_vless(
            VlessProfile(uuid=f"u{i}", address="h", name=f"w{i}"))
    assert len(store.list_vless(limit=1000)) == 500


# ---------------------------------------------------------------------------
# autopilot threads the SAME uuid into deploy + clean (the scanner-error fix)
# ---------------------------------------------------------------------------

class _C:
    def __init__(self, accounts):
        self._accounts = accounts
        self.token = "tok"

    def list_accounts(self):
        return self._accounts

    def get_subdomain(self, account_id):
        return "acctsub"


def test_resolve_account_matches_by_id_or_name(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    c = _C([{"id": "a1", "name": "Alpha"}, {"id": "a2", "name": "Beta"}])
    assert _resolve_account(c, "a2")[0] == "a2"
    assert _resolve_account(c, "Beta")[0] == "a2"
    assert _resolve_account(c, "")[0] == "a1"


def test_resolve_account_remembers(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    c = _C([{"id": "a1", "name": "Alpha"}])
    aid, acc = _resolve_account(c, "")
    assert store.get_account(aid)["name"] == "Alpha"


def test_resolve_account_unknown_raises(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    c = _C([{"id": "a1", "name": "Alpha"}])
    with pytest.raises(CFError):
        _resolve_account(c, "nope")


def test_autopilot_builds_clean_args_with_uuid(monkeypatch):
    # Instead of hitting real CF, patch cmd_deploy/cmd_clean to capture the
    # args they receive and assert both got the same UUID.
    seen = {}

    def fake_deploy(a):
        seen["deploy_uuid"] = a.uuid
        seen["deploy_name"] = a.name
        return 0

    def fake_clean(a):
        seen["clean_uuid"] = a.uuid
        seen["clean_name"] = a.name
        return 0

    monkeypatch.setattr("khvarenah.cli.cmd_deploy", fake_deploy)
    monkeypatch.setattr("khvarenah.cli.cmd_clean", fake_clean)
    monkeypatch.setattr("khvarenah.cli._token", lambda _: "tok")
    monkeypatch.setattr("khvarenah.cli.Config", lambda *a, **k: _C(
        [{"id": "a1", "name": "Alpha"}]))
    # fix uuid generation so we can assert it propagated
    monkeypatch.setattr("khvarenah.cli.wb.generate_uuid", lambda: "fixed-uuid-1234")

    args = build_parser().parse_args(["autopilot"])
    rc = cmd_autopilot(args)
    assert rc == 0
    assert seen["deploy_uuid"] == "fixed-uuid-1234"
    assert seen["clean_uuid"] == "fixed-uuid-1234"
    assert seen["deploy_name"] == "alpha"
    assert seen["clean_name"] == "alpha"


# ---------------------------------------------------------------------------
# clean end-to-end (mocked scanner) — best IP, --all, memory recording
# ---------------------------------------------------------------------------

class _CleanResult:
    def __init__(self, endpoints):
        self.ok = True
        self.endpoints = endpoints
        self.message = f"Found {len(endpoints)} clean endpoint(s)."


def test_clean_end_to_end_remembers_and_all(tmp_path, monkeypatch):
    _patch_mem(tmp_path, monkeypatch)
    monkeypatch.setattr("khvarenah.cli._token", lambda _: "tok")
    monkeypatch.setattr("khvarenah.cli.Config", lambda *a, **k: _C(
        [{"id": "a1", "name": "Alpha"}]))

    endpoints = [f"104.16.{i}.1:443" for i in range(1, 9)]
    monkeypatch.setattr("khvarenah.cli.find_clean_ips",
                        lambda *a, **k: _CleanResult(endpoints))

    # default respects --top (explicitly 3 here)
    args = build_parser().parse_args(["clean", "--uuid", "u-1", "--top", "3"])
    rc = cmd_clean(args)
    assert rc == 0
    hist = store.list_vless(limit=100)
    assert all(r["clean_ip"] for r in hist)
    assert len(hist) == 3  # only top 3 remembered

    # --all: every endpoint remembered
    store.clear_history()
    args = build_parser().parse_args(["clean", "--uuid", "u-1", "--all"])
    rc = cmd_clean(args)
    assert rc == 0
    hist = store.list_vless(limit=100)
    assert len(hist) == 8
    # configs file lists one per endpoint
    txt = Path("clean-configs.txt").read_text()
    assert txt.count("vless://") == 8
