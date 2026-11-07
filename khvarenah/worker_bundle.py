"""Local worker-bundle discovery/validation and preflight diagnostics."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

# Candidate locations for the edgetunnel _worker.js, searched in order.
_DEFAULTS = [
    Path(__file__).resolve().parent.parent / "_worker.js",        # <project>/_worker.js
    Path(__file__).resolve().parent / "_worker.js",
    Path.home() / "Projects" / "cf-worker-proxy" / "_worker.js",
    Path.home() / "Projects" / "cf-worker-proxy" / "edgetunnel_worker.js",
]


def find_worker_js(explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    for cand in _DEFAULTS:
        if cand.is_file():
            return cand
    return None


def validate_worker_js(path: Path) -> tuple[bool, str]:
    """Return (ok, message). Cheap sanity checks, not a full JS parse."""
    try:
        data = path.read_bytes()
    except OSError as e:
        return False, f"Cannot read worker file: {e}"
    blob = data[:200_000].decode("utf-8", errors="replace")
    if "WebSocket" not in blob and "upgrade" not in blob.lower() and "fetch" not in blob:
        return False, "Worker file does not look like a worker (no fetch/WebSocket handler)."
    if b"export default" in data or b"export {" in data or b"addEventListener" in data:
        return True, f"OK — {len(data):,} bytes, worker layout detected"
    return False, "Worker file has no export/fetch handler (not a module or service worker)."


def default_manifest() -> dict:
    return {
        "compatibility_date": "2026-07-01",
        "compatibility_flags": ["nodejs_compat"],
    }


def safe_worker_name(raw: str) -> str:
    """Normalize a worker name to CF's slug rules."""
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:64] or "cf-worker-proxy"


def generate_uuid() -> str:
    import uuid
    return str(uuid.uuid4())
