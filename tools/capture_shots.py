#!/usr/bin/env python3
"""Capture perfect SVG screenshots of every Khvarenah TUI screen.

Uses Textual's built-in `save_screenshot()` so the renders are pixel-perfect
(vector) — not fuzzy terminal-scrape captures. Mock state is seeded so the
non-network screens (account/worker/deploy/config/done) render fully.

Usage:  python3 tools/capture_shots.py OUT_DIR
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from khvarenah.tui import APP, CfConsoleApp
from khvarenah.vless import VlessProfile

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/shots")

# --- seed mock state so every screen renders a realistic, full UI ------
APP.accounts = [
    {"id": "a1", "name": "Khosrowan", "type": "standard", "status": "active"},
    {"id": "a2", "name": "Dariush",    "type": "standard", "status": "active"},
    {"id": "a3", "name": "worker-team", "type": "enterprise", "status": "active"},
]
APP.account_id = "a1"
APP.name = "vpn-edge"
APP.uuid = "550e8400-e29b-41d4-a716-446655440000"
APP.host = "vpn-edge.khosrowan.workers.dev"
APP.prof = VlessProfile(uuid=APP.uuid, address=APP.host, name=APP.name)

SIZE = (118, 34)
SHOTS = [
    ("welcome", "welcome"),
    ("token", "token"),
    ("account", "account"),
    ("worker", "worker"),
    ("deploy", "deploy"),
    ("config", "config"),
    ("done", "done"),
]


async def capture(screen: str, name: str) -> None:
    app = CfConsoleApp()
    async with app.run_test(size=SIZE) as pilot:
        if screen != "welcome":
            await app.switch_screen(screen)
        app.refresh()
        await pilot.pause()
        out = OUT / f"{name}.svg"
        app.save_screenshot(str(out))
        print(f"  ✓ {name}.svg ({out.stat().st_size} bytes)")


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Capturing {len(SHOTS)} TUI screens -> {OUT}")
    for screen, name in SHOTS:
        try:
            await capture(screen, name)
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {name}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
