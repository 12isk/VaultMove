"""Launcher used by PyInstaller and for running from source: python run_vaultmove.py"""

import sys

from vaultmove.app.main import main

if __name__ == "__main__":
    sys.exit(main())
