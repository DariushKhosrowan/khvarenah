"""Persistent memory for Khvarenah.

Records every generated vless config and every saved API token so the user
can revisit past setups — a lightweight, human-readable history stored under
``~/.khvarenah/``.

Storage layout (all JSON, UTF-8, 0o600 for anything that holds tokens):

  ~/.khvarenah/history.json     -> list of generated vless profiles
  ~/.khvarenah/tokens.json      -> saved API tokens (account -> token)
  ~/.khvarenah/config.json      -> user settings (auto-update, …)

Every function is defensive: if a file is missing or corrupt it returns a
sensible default rather than raising, so the app never breaks because of a
bad memory file.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid as _uuid
from pathlib import Path
from typing import List, Optional

MEM_DIR = Path.home() / ".khvarenah"
HISTORY_FILE = MEM_DIR / "history.json"
TOKENS_FILE = MEM_DIR / "tokens.json"
CONFIG_FILE = MEM_DIR / "config.json"
ACCOUNTS_FILE = MEM_DIR / "accounts.json"

_lock = threading.Lock()


def _ensure_dir() -> None:
    try:
        MEM_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(MEM_DIR, 0o700)
    except OSError:
        pass


def _read_json(path: Path, default):
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data is not None:
                return data
    except Exception:  # noqa: BLE001
        pass
    return default


def _write_json(path: Path, data, *, private: bool = True) -> None:
    try:
        _ensure_dir()
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        if private:
            os.chmod(path, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# vless history
# ---------------------------------------------------------------------------

def remember_vless(profile, *, clean_ip: bool = False,
                   note: str = "") -> dict:
    """Record a generated vless profile.  Returns the stored record.

    ``profile`` is a :class:`khvarenah.vless.VlessProfile` (or any object
    exposing ``uuid``/``address``/``port``/``name``/``share_link``).
    """
    record = {
        "id": _uuid.uuid4().hex[:12],
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": time.time(),
        "uuid": getattr(profile, "uuid", ""),
        "address": getattr(profile, "address", ""),
        "port": getattr(profile, "port", 443),
        "name": getattr(profile, "name", ""),
        "clean_ip": bool(clean_ip),
        "link": _safe_share_link(profile),
        "note": note,
    }
    with _lock:
        history = _read_json(HISTORY_FILE, [])
        history.append(record)
        # cap history to the most recent 500 entries
        history = history[-500:]
        _write_json(HISTORY_FILE, history, private=False)
    return record


def list_vless(limit: int = 50) -> List[dict]:
    history = _read_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        return []
    # newest first
    history = sorted(history, key=lambda r: r.get("epoch", 0), reverse=True)
    return history[:limit]


def clear_history() -> int:
    with _lock:
        history = _read_json(HISTORY_FILE, [])
        n = len(history) if isinstance(history, list) else 0
        _write_json(HISTORY_FILE, [], private=False)
    return n


def _safe_share_link(profile) -> str:
    try:
        return profile.share_link()
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------

def save_token(token: str, account_id: str = "") -> None:
    """Persist an API token keyed by a display label.

    Tokens are stored in a 0o600 file.  Tokens are sensitive; we only ever
    expose them back to the user via an explicit ``history tokens`` command,
    never in the GUI/TUI by default.
    """
    if not token or not token.strip():
        return
    with _lock:
        tokens = _read_json(TOKENS_FILE, {})
        if not isinstance(tokens, dict):
            tokens = {}
        label = account_id or "default"
        tokens[label] = {"token": token.strip(),
                         "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        _write_json(TOKENS_FILE, tokens, private=True)


def stored_tokens() -> dict:
    tokens = _read_json(TOKENS_FILE, {})
    return tokens if isinstance(tokens, dict) else {}


def get_token(label: str = "default") -> Optional[str]:
    t = stored_tokens().get(label)
    return t.get("token") if isinstance(t, dict) else None


def clear_tokens() -> None:
    with _lock:
        _write_json(TOKENS_FILE, {}, private=True)


# ---------------------------------------------------------------------------
# Account registry (so the user never re-types account IDs / names)
# ---------------------------------------------------------------------------

def remember_account(account_id: str, name: str = "", subdomain: str = "") -> None:
    """Persist a Cloudflare account so future runs can reuse it."""
    if not account_id:
        return
    with _lock:
        accs = _read_json(ACCOUNTS_FILE, {})
        acc = accs.get(account_id, {})
        if name:
            acc["name"] = name
        if subdomain:
            acc["subdomain"] = subdomain
        accs[account_id] = acc
        _write_json(ACCOUNTS_FILE, accs, private=True)


def list_accounts() -> dict:
    accs = _read_json(ACCOUNTS_FILE, {})
    return accs if isinstance(accs, dict) else {}


def get_account(account_id: str) -> dict:
    return list_accounts().get(account_id, {})


def account_label(account_id: str) -> str:
    acc = get_account(account_id)
    return acc.get("name") or account_id


def clear_accounts() -> None:
    with _lock:
        _write_json(ACCOUNTS_FILE, {}, private=True)


# ---------------------------------------------------------------------------
# Convenience — combine memory + config
# ---------------------------------------------------------------------------

def memory_summary() -> str:
    """A short human-readable summary for the UI (no tokens)."""
    hv = list_vless()
    tok = stored_tokens()
    accs = list_accounts()
    lines = []
    if hv:
        lines.append(f"🧠 {len(hv)} saved vless config(s)")
        for r in hv[:3]:
            tag = "clean-IP" if r.get("clean_ip") else "workers.dev"
            lines.append(f"   • {r.get('name') or r.get('address')} [{tag}] "
                         f"{r.get('ts')}")
    if tok:
        lines.append(f"🔑 {len(tok)} saved token(s)")
    if accs:
        names = [a.get("name") or aid for aid, a in list(accs.items())[:3]]
        lines.append(f"☁️ {len(accs)} saved account(s): {', '.join(names)}")
    if not lines:
        lines.append("No saved configs yet.")
    return "\n".join(lines)
