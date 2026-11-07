#!/usr/bin/env bash
# Cross-platform launcher. On Windows run `python run.py` directly.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "creating venv (first run)…"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet textual requests pyperclip
fi
exec .venv/bin/python run.py "$@"
