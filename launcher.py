"""PyInstaller bootstrap: import the khvarenah package and run it.

Used by build-deb.sh / build-windows.yml so the frozen binary launches the
real package (avoids the "relative import with no known parent" error that
happens when main.py is executed directly as a script).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from khvarenah.main import entrypoint  # noqa: E402

if __name__ == "__main__":
    sys.exit(entrypoint())
