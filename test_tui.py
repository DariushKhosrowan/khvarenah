"""Tests for the TUI: boot, autopilot navigation, and modern styling.

These run under the plain pytest runner (no pytest-asyncio dependency) by
driving the asyncio event loop explicitly inside sync test functions.
"""

import asyncio

from khvarenah.tui import CfConsoleApp


def _run(coro):
    return asyncio.run(coro)


def test_tui_boots_to_welcome():
    async def scenario():
        app = CfConsoleApp()
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            assert "WelcomeScreen" in type(app.screen).__name__
            # modern screen: welcome has both Start and Autopilot buttons
            app.screen.query_one("#start")
            app.screen.query_one("#autopilot")

    _run(scenario())


def test_autopilot_button_pushes_token_screen():
    async def scenario():
        app = CfConsoleApp()
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            app.screen.on_button_pressed(
                type("E", (), {"button": type("B", (), {"id": "autopilot"})()})()
            )
            await pilot.pause()
            assert "TokenScreen" in type(app.screen).__name__
            # token screen shows the autopilot label when in autopilot mode
            app.screen.query_one("#ap_label")

    _run(scenario())


def test_tui_constructs_all_screens():
    app = CfConsoleApp()
    expected = {"welcome", "token", "account", "worker", "deploy", "config", "done"}
    assert set(app.SCREENS.keys()) == expected
