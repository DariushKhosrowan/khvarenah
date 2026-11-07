"""Self-update for Khvarenah.

Checks GitHub for the latest release and upgrades the installed package in
place (via pip).  Used by the GUI's "auto-update" checkbox and the headless
`khvarenah upgrade` command.

Design notes:
  * Version source of truth is the installed distribution metadata
    (importlib.metadata) with a fallback to ``khvarenah.__version__``.
  * Updating runs ``pip install --upgrade --force-reinstall`` with the
    current interpreter.  When Khvarenah was installed through ``install.sh``
    the venv lives under ``~/.local/share/khvarenah`` and is user-writable,
    so no sudo is needed; system-wide installs may require elevated rights
    (we surface the pip error and a hint).
  * Per-user settings (auto-update flag …) live in ``~/.khvarenah/config.json``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

OWNER = "DariushKhosrowan"
REPO = "khvarenah"
GITHUB_API = "https://api.github.com"
RELEASE_LATEST_URL = f"{GITHUB_API}/repos/{OWNER}/{REPO}/releases/latest"
TARBALL_URL = f"https://github.com/{OWNER}/{REPO}/archive/refs/tags"


# ---------------------------------------------------------------------------
# Per-user settings
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".khvarenah"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULTS = {"auto_update": True}


def load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**DEFAULTS, **data}
    except Exception:  # noqa: BLE001
        pass
    return dict(DEFAULTS)


def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps({**DEFAULTS, **cfg}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:  # pragma: no cover
        print(f"[warn] could not save config: {e}", file=sys.stderr)


def get_setting(name: str, default=None):
    return load_config().get(name, default)


def set_setting(name: str, value) -> None:
    cfg = load_config()
    cfg[name] = value
    save_config(cfg)


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?")


def _normalize_version(v: str):
    """Return a comparable tuple of ints from a version-like string."""
    m = _VERSION_RE.match((v or "0").strip().lstrip("vV"))
    if not m:
        return (0, 0, 0)
    return tuple(int(m.group(i) or 0) for i in (1, 2, 3))


def current_version() -> str:
    """Version of the installed Khvarenah package."""
    try:
        from importlib.metadata import version as _pkg_version
        return _pkg_version("khvarenah")
    except Exception:  # noqa: BLE001
        pass
    try:
        from khvarenah import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "0.0.0"


def _latest_release_payload(timeout: int = 20) -> dict:
    req = urllib.request.Request(RELEASE_LATEST_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{REPO}-updater",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_release(timeout: int = 20) -> dict:
    """Return {tag, version, tarball_url} for the newest GitHub release.

    Returns an empty dict if no release exists or the network call fails.
    """
    try:
        payload = _latest_release_payload(timeout)
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return {}
    tag = payload.get("tag_name") or ""
    if not tag:
        return {}
    return {
        "tag": tag,
        "version": _normalize_version(tag),
        "tarball_url": f"{TARBALL_URL}/{tag}.tar.gz",
    }


def is_update_available() -> tuple[bool, dict]:
    """Return (available, release) comparing installed vs latest."""
    rel = latest_release()
    if not rel:
        return False, {}
    return rel["version"] > _normalize_version(current_version()), rel


# ---------------------------------------------------------------------------
# Applying an update
# ---------------------------------------------------------------------------

def apply_update(timeout: int = 600) -> tuple[bool, str]:
    """Download + install the latest release in place.

    Returns (ok, message).  ok=True means a newer version is now installed.
    """
    ok, rel = is_update_available()
    if not ok:
        return False, "Already on the latest version."
    url = rel["tarball_url"]
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install",
             "--upgrade", "--force-reinstall", url],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001
        return False, f"Update failed to start: {e}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-600:]
        hint = ("Run it again with elevated permissions (e.g. `sudo khvarenah upgrade`) "
                "if this was a system-wide install.")
        return False, f"pip failed:\n{tail}\n{hint}"
    return True, f"Updated to {rel['tag']} — restart Khvarenah to use it."
