"""Offscreen tests for the Khvarenah desktop GUI autopilot fix.

Verifies that autopilot on the Worker page sets STATE.name (and UUID) before
advancing to deploy — the root cause of the "provide the name of your worker"
wrangler error. Runs headless via QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from khvarenah.gui import (KhvarenahWindow, STATE,  # noqa: E402
                           safe_worker_name)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def win(app):
    w = KhvarenahWindow()
    STATE.autopilot = False
    STATE.name = ""
    STATE.uuid = ""
    w.show()
    yield w
    STATE.autopilot = False


def test_autopilot_sets_name_before_deploy(win):
    worker = win._pages["worker"]
    # simulate autopilot: flip the flag then enter the worker page
    STATE.autopilot = True
    worker.on_enter()
    # name must be set (non-empty) so deploy has a worker name to send
    assert STATE.name
    assert STATE.name == safe_worker_name(STATE.name)
    assert worker.name_edit.text() == STATE.name
    # uuid must be set automatically
    assert STATE.uuid
    assert worker.uuid_edit.text() == STATE.uuid


def test_autopilot_worker_page_sets_name_field(win):
    worker = win._pages["worker"]
    STATE.autopilot = True
    worker.on_enter()
    assert worker.name_edit.text() == "vpn-edge"
