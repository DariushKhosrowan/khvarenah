"""Offscreen smoke test for the Khvarenah desktop GUI.

Runs headless (QT_QPA_PLATFORM=offscreen), constructs the window, and
exercises the navigation + the worker-page defaults, so CI can verify the
GUI builds without a display.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from khvarenah.gui import KhvarenahWindow, STEPS, STATE  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    win = KhvarenahWindow()
    win.show()

    # 1. Window + sidebar stepper exist
    assert win.stack.count() == 8, f"expected 8 pages, got {win.stack.count()}"
    assert win._pages["welcome"] is not None

    # 2. Welcome is initially shown
    assert win.stack.currentWidget() is win._pages["welcome"]

    # 3. Navigate to token (allowed)
    win.goto("token")
    assert win.stack.currentWidget() is win._pages["token"]
    assert win._pages["token"].token_edit is not None

    # 4. Worker page defaults (no network needed)
    win.goto("worker")
    assert win.stack.currentWidget() is win._pages["worker"]
    STATE.uuid = ""
    win._pages["worker"].on_enter()
    assert STATE.uuid, "worker page should auto-generate a UUID"
    assert win._pages["worker"].uuid_edit.text() == STATE.uuid

    # 5. Stepper sync: current step checked
    win.goto("deploy")
    assert win._step_buttons["deploy"].isChecked()

    # 6. Done page shows summarized state even empty
    win.goto("done")
    assert win._pages["done"].summary is not None

    # 7. CleanIP utility page reachable
    win.goto("cleanip")
    assert win.stack.currentWidget() is win._pages["cleanip"]

    print("ALL GUI SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
