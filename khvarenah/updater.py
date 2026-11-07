"""Self-update for Khvarenah.

Checks GitHub for the latest release and upgrades the installed package in
place (via pip).  Used by the GUI's "auto-update" checkbox and the headless
`khvarenah upgrade` command.

Design notes:
  * Version source of truth is the installed distribution metadata
    (importlib.metadata) with a fallback to ``khvarenah.__version__``.
  * Updates are *instant*: the release is published with a prebuilt wheel
    asset, so updating just downloads that wheel and pip-installs it in place.
    No sdist download, no build step.  If a wheel is missing (e.g. a very
    early release) we fall back to installing from the source tarball.
  * The version check is a single GitHub API call (one round-trip).  The GUI
    runs it in a background thread so it never blocks the first paint.
  * Per-user settings (auto-update flag …) live in ``~/.khvarenah/config.json``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


# ---------------------------------------------------------------------------
# GitHub release lookup
# ---------------------------------------------------------------------------

def _github_get(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{REPO}-updater",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _latest_release_payload(timeout: int = 12) -> dict:
    return json.loads(_github_get(RELEASE_LATEST_URL, timeout).decode("utf-8"))


def latest_release(timeout: int = 12) -> dict:
    """Return {tag, version, tarball_url, assets} for the newest GitHub release.

    Returns an empty dict if no release exists or the network call fails.
    ``assets`` is a list of {name, url} for the release's binary artifacts
    (notably the prebuilt wheel, which makes updates instant).
    """
    try:
        payload = _latest_release_payload(timeout)
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return {}
    tag = payload.get("tag_name") or ""
    if not tag:
        return {}
    assets = []
    for a in payload.get("assets") or []:
        name = a.get("name") or ""
        if name:
            assets.append({"name": name, "url": a.get("browser_download_url") or ""})
    return {
        "tag": tag,
        "version": _normalize_version(tag),
        "tarball_url": f"{TARBALL_URL}/{tag}.tar.gz",
        "assets": assets,
    }


def is_update_available() -> tuple[bool, dict]:
    """Return (available, release) comparing installed vs latest."""
    rel = latest_release()
    if not rel:
        return False, {}
    return rel["version"] > _normalize_version(current_version()), rel


def _pick_wheel_asset(assets: list[dict]):
    """Pick the prebuilt wheel asset (prefer the universal pure-Python wheel)."""
    wheels = [a for a in assets if a.get("name", "").endswith(".whl")]
    if not wheels:
        return None
    return next((a for a in wheels if "-py3-none-any" in a["name"]), wheels[0])


# ---------------------------------------------------------------------------
# Applying an update
# ---------------------------------------------------------------------------

def _download_to_temp(url: str, timeout: int) -> str:
    """Stream ``url`` to a temp file and return its path (caller deletes)."""
    fd, path = tempfile.mkstemp(suffix=os.path.splitext(url or ".bin")[1] or ".bin")
    try:
        with urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": f"{REPO}-updater"}),
                timeout=timeout) as resp, os.fdopen(fd, "wb") as fh:
            shutil.copyfileobj(resp, fh)
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def _pip_install(source: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pip", "install",
         "--upgrade", "--force-reinstall", source],
        capture_output=True, text=True, timeout=timeout,
    )


def _install_release(rel: dict, timeout: int = 600) -> tuple[bool, str]:
    """Download + install the given release.

    Prefers the prebuilt wheel asset (fast, no build).  Falls back to the
    source tarball when the release carries no wheel.
    """
    wheel = _pick_wheel_asset(rel.get("assets") or [])
    tmp = None
    try:
        if wheel:
            tmp = _download_to_temp(wheel["url"], min(timeout, 120))
            source = tmp
        else:
            source = rel["tarball_url"]
        proc = _pip_install(source, timeout)
    except Exception as e:  # noqa: BLE001
        return False, f"Update failed to start: {e}"
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-600:]
        hint = ("Run it again with elevated permissions (e.g. `sudo khvarenah upgrade`) "
                "if this was a system-wide install.")
        return False, f"pip failed:\n{tail}\n{hint}"
    return True, f"Updated to {rel['tag']} — restart Khvarenah to use it."


def check_and_apply(timeout: int = 600) -> tuple[bool, str]:
    """One round-trip: fetch latest release, compare, and apply if newer.

    Returns (ok, message).  ok=True means a newer version is now installed.
    This is the single entry point used by the GUI and CLI.
    """
    rel = latest_release()
    if not rel:
        return False, "Could not reach GitHub to check for updates."
    if not rel["version"] > _normalize_version(current_version()):
        return False, "Already on the latest version."
    return _install_release(rel, timeout)


def apply_update(timeout: int = 600) -> tuple[bool, str]:
    """Backwards-compatible alias for :func:`check_and_apply`."""
    return check_and_apply(timeout)
