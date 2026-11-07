#!/usr/bin/env bash
# Build a standalone .deb for Khvarenah.
#
# PyInstaller bundles Python + all deps into a single binary, so the resulting
# package installs with `sudo apt install ./khvarenah_*.deb` — no pip, no
# venv, no PEP 668 errors. Perfect for non-programmers.
#
# Requires: python3-venv (installed by install.sh if needed), dpkg-deb.

set -euo pipefail
cd "$(dirname "$0")"

# Version is read from pyproject.toml so release assets always match the tag.
VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' pyproject.toml | head -1)"
[ -n "$VERSION" ] || VERSION="0.1.0"
ARCH="amd64"
VENV=".venv"
PY="$VENV/bin/python"
PYI="$VENV/bin/pyinstaller"
BUILD="build/deb"
ROOT="$BUILD/root"
DEBIAN="$ROOT/DEBIAN"
BIN="$ROOT/usr/local/bin"
SHARE="$ROOT/usr/share/khvarenah"
DOC="$ROOT/usr/share/doc/khvarenah"

echo "⟡ Building khvarenah_${VERSION}_${ARCH}.deb"

# 1. Ensure PyInstaller is available.
if [ ! -x "$PYI" ]; then
  echo "  installing pyinstaller..."
  "$PY" -m pip install --quiet pyinstaller
fi

# 2. Build the standalone binary (onefile).
echo "  pyinstaller → standalone binary..."
rm -rf build/pyinstaller
"$PYI" \
  --noconfirm --clean --onefile \
  --name khvarenah \
  --collect-all textual \
  --add-data "khvarenah/assets/golden.png:khvarenah/assets" \
  launcher.py

# 3. Assemble the .deb directory layout.
echo "  assembling deb tree..."
rm -rf "$BUILD/root"
mkdir -p "$BIN" "$SHARE" "$DOC" "$DEBIAN"

cp dist/khvarenah "$BIN/khvarenah"
chmod 755 "$BIN/khvarenah"
cp LICENSE "$DOC/copyright"
cp README.md "$DOC/README.md"
cp -r docs "$SHARE/docs" 2>/dev/null || true

INSTALLED=$(du -sk "$ROOT" | cut -f1)

cat > "$DEBIAN/control" <<EOF
Package: khvarenah
Version: $VERSION
Section: net
Priority: optional
Architecture: $ARCH
Maintainer: Dariush Khosrowan <dariush@khosrowan.ir>
Installed-Size: $INSTALLED
Depends: libc6 (>= 2.17)
Description: Khvarenah — Cloudflare-Worker VLESS VPN console
 A terminal console that creates and controls a Cloudflare Workers VLESS
 proxy from zero to one hundred: verify token, pick account, deploy the
 worker, and get a ready-to-copy vless:// config. Friendly error
 explanations. Cross-platform (Linux/Windows), interactive TUI + CLI.
 .
 Brand: Khvarenah (خوَرنه) — the Avestan royal glory.
EOF

cat > "$DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
echo "  Khvarenah installed. Run 'khvarenah' to start (TUI) or 'khvarenah cli --help' for the headless CLI."
EOF
chmod 755 "$DEBIAN/postinst"

# 4. Build the .deb.
fakeroot dpkg-deb --build --root-owner-group "$ROOT" "build/khvarenah_${VERSION}_${ARCH}.deb" >/dev/null

echo "  ✓ build/khvarenah_${VERSION}_${ARCH}.deb"
