"""Font family resolution, shared by both toolkits.

The preference lists and the type scale are toolkit-independent, so they live
here rather than being duplicated in :mod:`musicdl.ui.fonts` (Tk) and a Qt
equivalent. Each toolkit supplies its own availability check; only that
differs.

Tabular numerals
----------------
Any number that changes while the user is looking at it must be
fixed-width, or the column jitters on every tick. Tk has no
``font-variant-numeric`` equivalent, so the Tk side works around it by
rendering those numbers in a monospace family, where digits are fixed-width
by construction. Qt has real support, so the Qt side sets the feature
directly - but both agree on which numbers need it.
"""

from __future__ import annotations

import sys

from ..ui import tokens

__all__ = [
    "UI_FAMILIES", "MONO_FAMILIES", "ui_family", "mono_family",
    "is_numeric", "TYPE_SCALE",
]

# Platform-preferred UI families, best first. If none exist, the caller falls
# back to the platform's own default rather than naming a family that is not
# installed, which would render in a silent fallback anyway.
UI_FAMILIES = {
    "Windows": ("Segoe UI Variable Text", "Segoe UI", "Tahoma", "Verdana"),
    "Darwin": (".AppleSystemUIFont", "Helvetica Neue", "Helvetica", "Arial"),
    "Linux": ("Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans", "FreeSans"),
}

# Monospace families, best first. Used for the log pane and for any number
# that changes in place.
MONO_FAMILIES = {
    "Windows": ("Cascadia Mono", "Consolas", "Cascadia Code", "Courier New"),
    "Darwin": ("SF Mono", "Menlo", "Monaco", "Courier New"),
    "Linux": ("JetBrains Mono", "DejaVu Sans Mono", "Liberation Mono",
              "Noto Sans Mono", "Courier New"),
}

# The type scale, by role name. The stylesheet and the widgets both read sizes
# from here, so a scale change is one edit rather than a hunt.
TYPE_SCALE = {
    "title": tokens.FONT_SIZE_TITLE,
    "section": tokens.FONT_SIZE_SECTION,
    "body": tokens.FONT_SIZE_BODY,
    "body_bold": tokens.FONT_SIZE_BODY,
    "secondary": tokens.FONT_SIZE_SECONDARY,
    "caption": tokens.FONT_SIZE_CAPTION,
    "caption_bold": tokens.FONT_SIZE_CAPTION,
    "log": tokens.FONT_SIZE_LOG,
    "numeric": tokens.FONT_SIZE_CAPTION,
    "numeric_bold": tokens.FONT_SIZE_CAPTION,
}

# Roles whose digits must not move. Anything that updates while the user is
# watching it is in this set.
NUMERIC_ROLES = frozenset({"numeric", "numeric_bold"})


def platform_key() -> str:
    """The current platform, in the form the family tables are keyed by."""
    if sys.platform.startswith("win"):
        return "Windows"
    if sys.platform == "darwin":
        return "Darwin"
    return "Linux"


def is_numeric(role: str) -> bool:
    """True when a type role must be rendered with tabular figures."""
    return role in NUMERIC_ROLES


def ui_family(available: set[str] | None = None) -> str | None:
    """The best available UI family for this platform.

    ``available`` is the set of installed family names. Returning ``None``
    rather than a made-up name matters: naming a family that is not installed
    produces a silent fallback, so the caller is better served knowing that no
    preference matched and can use the platform default instead.
    """
    if available is None:
        return None
    for name in UI_FAMILIES[platform_key()]:
        if name in available:
            return name
    return None


def mono_family(available: set[str] | None = None) -> str | None:
    """The best available fixed-pitch family, or ``None`` if none match."""
    if available is None:
        return None
    for name in MONO_FAMILIES[platform_key()]:
        if name in available:
            return name
    return None
