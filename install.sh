#!/usr/bin/env bash
# Khvarenah installer — safe for non-programmers.
#
# Creates a dedicated virtualenv (avoids the PEP 668 "externally-managed
# environment" error on modern Ubuntu/Debian) and installs Khvarenah into it.
# Then runs `khvarenah` for you.
#
# Usage:
#   ./install.sh              # install + launch the TUI wizard
#   ./install.sh cli --help   # install + run a headless CLI command
#
# Safe to run more than once (it reuses the existing venv, reinstalling
# the package to pick up updates).

set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"
BIN="$VENV/bin"
PY="$BIN/python"
PIP="$BIN/pip"
CMD="$BIN/khvarenah"

echo "⟡ Khvarenah installer"
echo "  creating virtualenv: $VENV"

# Create the venv if it does not exist yet.
if [ ! -x "$PY" ]; then
  # Try to make sure python3-venv is present (needed on Debian/Ubuntu).
  if ! python3 -c "import ensurepip, venv" >/dev/null 2>&1; then
    echo "  installing python3-venv (needs sudo, one-time)..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3-venv python3-full
  fi
  python3 -m venv "$VENV"
fi

echo "  installing/updating Khvarenah + dependencies..."
"$PIP" install --quiet --upgrade pip >/dev/null
"$PIP" install --quiet -e . >/dev/null

echo "  installed. —"
echo
if [ $# -eq 0 ]; then
  exec "$CMD"
else
  exec "$CMD" "$@"
fi
