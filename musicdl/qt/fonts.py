"""Qt font handling: family resolution and per-role ``QFont`` construction.

The family preference lists live in :mod:`musicdl.qt.families` because they
are shared with the Tk side. This module adds the two things that are
genuinely Qt-specific:

* availability, via ``QFontDatabase`` rather than a toolkit round-trip
* tabular figures, which Qt supports properly with
  ``QFont::setFeature("tnum")`` - so this side does not need the monospace
  workaround the Tk side is stuck with

Widgets ask for a role by name (:func:`font`) rather than building a font
tuple, so sizes stay in :mod:`musicdl.ui.tokens` and the type scale has one
definition.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication

from . import families
from ..ui import tokens

__all__ = ["font", "family_name", "mono_family_name", "reset_cache"]

_resolved: dict = {}


def _installed() -> set[str]:
    """Installed family names, or an empty set if there is no GUI yet.

    ``QFontDatabase`` aborts the process rather than raising when it is
    reached without a ``QGuiApplication``, so the check has to happen first.
    Returning an empty set is the honest answer: it means "nothing is known
    yet", and both callers already treat that as "use the platform default"
    rather than as an error.
    """
    if QGuiApplication.instance() is None:
        return set()
    return set(QFontDatabase.families())


def _resolve(key: str, chooser) -> str | None:
    """Resolve a family once and cache it, including the None result.

    The empty pre-GUI answer is deliberately *not* cached: it means "not known
    yet", and caching it would leave the app permanently on the fallback font
    even after the GUI came up.
    """
    if key in _resolved:
        return _resolved[key]
    installed = _installed()
    if not installed and QGuiApplication.instance() is None:
        return None
    _resolved[key] = chooser(installed)
    return _resolved[key]


def family_name() -> str:
    """The app's UI family, or an empty string for the platform default.

    An empty string is Qt's own "use the default" signal, which is the right
    answer when no preference is installed - better than naming a family that
    is missing and silently falling back anyway.
    """
    return _resolve("ui", families.ui_family) or ""


def mono_family_name() -> str:
    """The app's fixed-pitch family, or an empty string for the default."""
    return _resolve("mono", families.mono_family) or ""


def reset_cache() -> None:
    """Forget the resolved families, for a test or a font-install event."""
    _resolved.clear()


def font(role: str = "body") -> QFont:
    """A ``QFont`` for a named type role.

    Numeric roles get Qt's real ``tnum`` feature, so digits are fixed-width
    without the log pane and the status column having to be monospaced. That
    is the one place Qt is strictly better than the Tk side, and it is why the
    two UIs do not look identical in the log pane.
    """
    qf = QFont(family_name())
    size = families.TYPE_SCALE.get(role, tokens.FONT_SIZE_BODY)
    qf.setPointSize(size)
    if families.is_numeric(role):
        qf.setFeature("tnum", 1)
    if role in ("title", "section", "body_bold", "caption_bold",
                "numeric_bold"):
        qf.setWeight(QFont.Weight.DemiBold)
    return qf


def mono_font(role: str = "log") -> QFont:
    """A fixed-pitch ``QFont`` for the log pane."""
    qf = QFont(mono_family_name() or "monospace")
    qf.setPointSize(families.TYPE_SCALE.get(role, tokens.FONT_SIZE_LOG))
    return qf
