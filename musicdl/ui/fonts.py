"""Font resolution and the app's type styles.

Two jobs:

* **Resolve real font families.** ``TkDefaultFont`` is the right *default* but
  it is a named font, not a family, so it cannot be combined with a size. This
  module picks the best available UI family and monospace family for the
  running platform, caching the result.
* **Expose named styles.** Widgets ask for ``fonts.body`` rather than building
  a font tuple, so sizes live in :mod:`musicdl.ui.tokens` and stay consistent.

Tabular numerals
----------------
Any number that changes while the user is looking at it must be
fixed-width, or the column jitters on every tick. Tk exposes no
``font-variant-numeric`` equivalent, so the workaround is to render progress,
speed, and percentages in a monospace family, where digits are fixed-width by
construction. :func:`numeric` builds that style and
:func:`progress_text` formats into it.
"""

from __future__ import annotations

import tkinter.font as tkfont

from . import tokens

# Platform-preferred UI families, best first. Resolved once at startup; if none
# exist we fall back to Tk's own default rather than naming a family that is
# not installed, which would render in a silent fallback anyway.
_UI_FAMILIES = {
    "Windows": ("Segoe UI Variable Text", "Segoe UI", "Tahoma", "Verdana"),
    "Darwin": (".AppleSystemUIFont", "Helvetica Neue", "Helvetica", "Arial"),
    "Linux": ("Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans", "FreeSans"),
}

# Monospace families, best first. These are used for the log pane and for every
# number that changes in place.
_MONO_FAMILIES = {
    "Windows": ("Cascadia Mono", "Consolas", "Cascadia Code", "Courier New"),
    "Darwin": ("SF Mono", "Menlo", "Monaco", "Courier New"),
    "Linux": ("JetBrains Mono", "DejaVu Sans Mono", "Liberation Mono",
              "Noto Sans Mono", "Courier New"),
}

# Fallbacks used when nothing in the preference list is installed.
_UI_FALLBACK = "TkDefaultFont"
_MONO_FALLBACK = "TkFixedFont"

_resolved: dict = {}

# Live references to every named font we create. Tk unregisters a named font
# when its last Python reference is garbage-collected, so these must be held
# for the lifetime of the process or widgets already pointing at a style would
# silently revert to the default face.
_registered: dict = {}


def _first_available(candidates, fallback: str) -> str:
    """Return the first installed family in ``candidates``, else ``fallback``."""
    families = set(tkfont.families())
    for name in candidates:
        if name in families:
            return name
    return fallback


def ui_family() -> str:
    """The best available UI family for this platform."""
    if "ui" not in _resolved:
        import sys

        key = "Windows" if sys.platform.startswith("win") else (
            "Darwin" if sys.platform == "darwin" else "Linux")
        _resolved["ui"] = _first_available(_UI_FAMILIES[key], _UI_FALLBACK)
    return _resolved["ui"]


def mono_family() -> str:
    """The best available fixed-pitch family for this platform."""
    if "mono" not in _resolved:
        import sys

        key = "Windows" if sys.platform.startswith("win") else (
            "Darwin" if sys.platform == "darwin" else "Linux")
        _resolved["mono"] = _first_available(_MONO_FAMILIES[key], _MONO_FALLBACK)
    return _resolved["mono"]


def reset_cache() -> None:
    """Forget resolved families. Used by tests, and after a font install."""
    _resolved.clear()


# --------------------------------------------------------------- font builders
def _named(base: str, size: int, weight: str = tokens.WEIGHT_REGULAR) -> str:
    """Register (or reconfigure) a named font and return its Tk name.

    Naming the fonts means a widget references a style rather than carrying a
    tuple, and the sizes stay resolved in this one place. Reconfiguring an
    existing font rather than recreating it matters: a live font object is what
    Tk measures widgets against, so replacing it would leave them sized against
    a stale metric.

    Note the fallback branch: when family resolution yields one of Tk's *named*
    fonts (``TkDefaultFont`` / ``TkFixedFont``) it cannot be passed as a
    ``family`` - Tk rejects naming a font inside a font. In that case only the
    size is set, and Tk keeps its own face, which is the correct degradation.
    """
    name = f"musicdl.{base}"
    family = mono_family() if base.startswith(("log", "numeric")) else ui_family()
    # `name` is accepted by the constructor but not by configure(), so the two
    # option sets are kept separate.
    options = {"size": size, "weight": weight}
    if family not in (_UI_FALLBACK, _MONO_FALLBACK):
        options["family"] = family
    if name in _registered:
        _registered[name].configure(**options)
    else:
        # The Font object must be kept alive here. Tk deletes a named font once
        # its last Python reference is collected, which would leave every widget
        # already pointing at it silently falling back to the default face.
        _registered[name] = tkfont.Font(name=name, **options)
    return name


# ------------------------------------------------------------------ type scale
# Each style is a *named* Tk font. Registering them once means the sizes are
# resolved in one place, and a widget can reference a style without carrying
# its own tuple.
def title() -> str:
    """App name. Semibold at the top of the scale."""
    return _named("title", tokens.FONT_SIZE_TITLE, tokens.WEIGHT_BOLD)


def section() -> str:
    """Section headers."""
    return _named("section", tokens.FONT_SIZE_SECTION, tokens.WEIGHT_BOLD)


def body() -> str:
    """Primary row text and control labels. The desktop 'normal' size."""
    return _named("body", tokens.FONT_SIZE_BODY)


def body_bold() -> str:
    """Emphasis within body text - the only weight step we use."""
    return _named("bodybold", tokens.FONT_SIZE_BODY, tokens.WEIGHT_BOLD)


def secondary() -> str:
    """Supporting text: artist names, hints, counts."""
    return _named("secondary", tokens.FONT_SIZE_SECONDARY)


def caption() -> str:
    """Column headers and status text."""
    return _named("caption", tokens.FONT_SIZE_CAPTION)


def caption_bold() -> str:
    return _named("captionbold", tokens.FONT_SIZE_CAPTION, tokens.WEIGHT_BOLD)


def log() -> str:
    """The log pane. Monospace so timestamps and rates stay aligned."""
    return _named("log", tokens.FONT_SIZE_LOG)


def numeric() -> str:
    """Numbers that change in place: percentage, speed, counts.

    Monospace gives fixed-width digits, which is what stops the progress
    column from shimmering on every yt-dlp tick.
    """
    return _named("numeric", tokens.FONT_SIZE_CAPTION)


def numeric_bold() -> str:
    return _named("numericbold", tokens.FONT_SIZE_CAPTION, tokens.WEIGHT_BOLD)


#: Every style this module registers, for tests and for a theme sweep.
ALL_STYLES = {
    "title": title, "section": section, "body": body, "body_bold": body_bold,
    "secondary": secondary, "caption": caption, "caption_bold": caption_bold,
    "log": log, "numeric": numeric, "numeric_bold": numeric_bold,
}


# ------------------------------------------------------------------ formatting
def progress_text(percent: int, speed: str = "", eta: str = "") -> str:
    """Format a live progress reading at a fixed width.

    The percentage is right-aligned into a 4-character field and the separators
    are fixed, so a row's status text does not change width as the numbers
    change. Combined with :func:`numeric`'s monospace digits, the column holds
    still instead of twitching on every yt-dlp tick.
    """
    parts = [f"{max(0, min(100, int(percent))):>3}%"]
    if speed and speed != "--":
        parts.append(speed)
    if eta and eta != "--":
        parts.append(f"ETA {eta}")
    return " · ".join(parts)


def tick_text(done: int, active: int, total: int) -> str:
    """Format the 'x/y done' counter at a fixed width."""
    return f"{done:>{len(str(max(total, 1)))}}/{total} done · {active} active"
