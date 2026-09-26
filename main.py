#!/usr/bin/env python3
"""Music Downloader - launch script.

Kept at the repo root so the app can be started with ``python main.py`` and
frozen with PyInstaller using this file as the entry point.
"""

import os
import sys

# Allow running from a source checkout without installing the package.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    if "--tk" in sys.argv:
        sys.argv.remove("--tk")
        from musicdl.ui.app import run
    else:
        from musicdl.qt.app import run

    return run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
