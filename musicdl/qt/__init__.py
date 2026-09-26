"""Qt bindings for the app.

The Qt rewrite sits alongside the existing ttkbootstrap UI rather than
replacing it, so both can be developed and reviewed independently. Everything
that does not touch a toolkit - :mod:`musicdl.core`, :mod:`musicdl.naming`,
:mod:`musicdl.cleanup`, :mod:`musicdl.paths`, :mod:`musicdl.config`,
:mod:`musicdl.formatting` and :mod:`musicdl.ui.downloader` - is shared
verbatim between the two.

The design system in :mod:`musicdl.ui.tokens` is likewise shared: it is plain
data with no toolkit imports, so the colours, spacing, radii and type scale
that were designed against libadwaita's palette carry over unchanged.

Submodules are imported lazily. The Qt port is being built in layers, and an
eager ``from .app import ...`` here would make every intermediate state
unimportable - you could not test the theme layer until the whole window
existed.
"""

from __future__ import annotations

from typing import Any

__all__ = ["MainWindow", "run"]


def __getattr__(name: str) -> Any:
    """Import the window lazily, so partial builds stay importable."""
    if name in __all__:
        from . import app

        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
