"""Khvarenah console entry point.

Replicates the old ``run.py`` dispatch: by default launch the interactive TUI
wizard; pass ``cli`` as the first argument for the headless CLI.

Examples::

    khvarenah                  # 0→100 TUI wizard
    khvarenah cli check
    khvarenah cli deploy --token $CF_TOKEN --name my-vpn
"""

from __future__ import annotations

import sys

from .tui import main as tui_main
from .cli import main as cli_main


def entrypoint() -> int:
    args = sys.argv[1:]
    if args and args[0] == "cli":
        return cli_main(args[1:])
    # Top-level --version / -h route to the CLI parser without launching the TUI
    if args and args[0] in ("--version", "-V"):
        return cli_main(["--version"])
    if args and args[0] in ("--help", "-h"):
        return cli_main(["--help"])
    tui_main()
    return 0


if __name__ == "__main__":
    sys.exit(entrypoint())
