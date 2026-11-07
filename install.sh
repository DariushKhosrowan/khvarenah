#!/usr/bin/env bash
# Khvarenah self-contained installer — safe for non-programmers, and works
# from ANY directory (including via the one-liner below), because it fetches
# the actual source before installing instead of assuming a local checkout.
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/DariushKhosrowan/khvarenah/main/install.sh | bash
#
# What it does:
#   1. Downloads the project source tarball (main branch) to a stable location
#      under ~/.local/share/khvarenah/.
#   2. Creates a dedicated virtualenv there (avoids the PEP 668
#      "externally-managed environment" error on modern Ubuntu/Debian).
#   3. Installs Khvarenah into it and then launches it.
#
# Safe to run more than once (it re-fetches and reinstalls to pick up updates).

set -euo pipefail

REPO="DariushKhosrowan/khvarenah"
BRANCH="main"
BASE="${HOME}/.local/share/khvarenah"
SRC="${BASE}/src"
VENV="${BASE}/venv"
PY="${VENV}/bin/python"
PIP="${VENV}/bin/pip"
CMD="${VENV}/bin/khvarenah"

echo "⟡ Khvarenah installer"
echo "  install prefix: ${BASE}"

# Ensure python3-venv is present (Debian/Ubuntu split it out).
if ! python3 -c "import ensurepip, venv" >/dev/null 2>&1; then
  echo "  installing python3-venv (needs sudo, one-time)..."
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv python3-full
fi

# Fetch the source tarball (works even where git over SSH/HTTPS is throttled).
echo "  fetching source from GitHub (${BRANCH})..."
mkdir -p "${BASE}"
TARBALL="${BASE}/source.tar.gz"
curl -fsSL "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" -o "${TARBALL}"
rm -rf "${SRC}"
mkdir -p "${SRC}"
tar -xzf "${TARBALL}" -C "${SRC}" --strip-components=1

echo "  creating/reusing virtualenv..."
if [ ! -x "${PY}" ]; then
  python3 -m venv "${VENV}"
fi

echo "  installing/updating Khvarenah + dependencies..."
"${PIP}" install --quiet --upgrade pip >/dev/null
"${PIP}" install --quiet "${SRC}" >/dev/null

# 4. Link `khvarenah` onto PATH so the command works from any directory.
echo "  linking 'khvarenah' onto PATH..."
mkdir -p "${HOME}/.local/bin"
if [[ ":$PATH:" == *":${HOME}/.local/bin:"* ]]; then
  LNK_DIR="${HOME}/.local/bin"
else
  LNK_DIR="/usr/local/bin"
fi
if [ "${LNK_DIR}" = "/usr/local/bin" ] && [ ! -w /usr/local/bin ]; then
  echo "  creating symlink with sudo (one-time)..."
  sudo ln -sf "${CMD}" "${LNK_DIR}/khvarenah"
else
  ln -sf "${CMD}" "${LNK_DIR}/khvarenah"
fi
if command -v khvarenah >/dev/null 2>&1; then
  echo "  ✓ 'khvarenah' is runnable: $(command -v khvarenah)"
else
  echo "  NOTE: ${LNK_DIR} isn't on your PATH. Add: export PATH=\"${LNK_DIR}:\$PATH\""
fi

echo "  installed. —"
echo
if [ $# -eq 0 ]; then
  exec "${CMD}"
else
  exec "${CMD}" "$@"
fi
