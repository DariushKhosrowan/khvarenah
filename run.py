#!/usr/bin/env python3
"""Entry point: TUI by default, `cli` subcommand for headless use.

Examples:
    python run.py                 # launch the 0→100 TUI
    python run.py cli check --token $CF_TOKEN
    python run.py cli deploy --token $CF_TOKEN --name khosrowan
    python run.py cli config --token $CF_TOKEN --name khosrowan --uuid ...
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from khvarenah.tui import main as tui_main  # noqa: E402
from khvarenah.cli import main as cli_main    # noqa: E402


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        return cli_main(sys.argv[2:])
    return tui_main()


if __name__ == "__main__":
    sys.exit(main())
