"""Entry point: ``python -m musicdl`` or ``python main.py``."""

import sys


def main() -> int:
    """Launch the GUI. Returns a process exit code."""
    if "--tk" in sys.argv:
        sys.argv.remove("--tk")
        from .ui.app import run
    else:
        from .qt.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
