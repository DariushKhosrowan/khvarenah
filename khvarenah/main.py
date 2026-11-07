"""Khvarenah console entry point.

By default launch the modern desktop GUI (PySide6). Pass ``cli`` as the first
argument for the headless CLI, or ``tui`` to force the terminal UI.

Examples::

    khvarenah                  # 0→100 desktop GUI (default)
    khvarenah tui              # terminal TUI wizard
    khvarenah cli check
    khvarenah cli deploy --token $CF_TOKEN --name khosrowan
"""

from __future__ import annotations

import sys

from .cli import main as cli_main


def entrypoint() -> int:
    args = sys.argv[1:]
    if args and args[0] == "cli":
        return cli_main(args[1:])
    if args and args[0] == "tui":
        from .tui import main as tui_main
        tui_main()
        return 0
    # Top-level CLI subcommands (so `khvarenah upgrade`, `khvarenah scan`, …)
    # work directly, not just behind the `cli` prefix.
    _CMDS = {"check", "deploy", "config", "status", "scan",
             "clean", "autopilot", "upgrade", "history", "accounts"}
    if args and args[0] in _CMDS:
        return cli_main(args)
    # Top-level --version / -h route to the CLI parser without launching a UI
    if args and args[0] in ("--version", "-V"):
        return cli_main(["--version"])
    if args and args[0] in ("--help", "-h"):
        return cli_main(["--help"])
    try:
        from .gui import main as gui_main
    except Exception as e:  # pragma: no cover - no Qt fallback
        print(f"Khvarenah GUI requires PySide6 (pip install PySide6): {e}",
              file=sys.stderr)
        return 1
    return gui_main()


if __name__ == "__main__":
    sys.exit(entrypoint())
