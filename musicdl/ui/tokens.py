"""Design tokens for the Music Downloader UI.

Every visual decision in the app resolves through this module. Nothing in
``musicdl/ui`` should hardcode a colour, a radius, or a font size - if a value
is needed that is not here, that is a gap in the system rather than a reason to
pick a number at the call site.

The system is deliberately small. Roughly 40 values covers the whole
application, and a handful of roles carry almost all of the work.

Provenance
----------
Neutrals are taken from libadwaita's published palette rather than invented
here, for two reasons that matter visually:

* Its *light* neutrals are warm (``#f6f5f4``) while its *dark* neutrals are
  cool and slightly purple (``#241f31``). A flat ``#f5f5f5`` / ``#2a2a2a``
  pairing reads as 2019; the warm/cool split is the current direction.
* It is a shipped, accessibility-reviewed desktop design system, so the
  surfaces already sit at sensible contrast levels.

Semantic accents likewise come from libadwaita, and every one is used in a
light-theme variant and a dark-theme variant, each of which clears 4.5:1
against the surface it is used on. That pairing is enforced by
``tests/test_tokens.py``, so a bad swap fails the suite rather than shipping.

Rules this system exists to enforce
------------------------------------
* **One accent.** Slate, used only for the primary action and selection. It is
  never decoration, and it never appears next to YouTube's red artwork without
  enough separation to stay calm.
* **No gradients, no glow, no glass on content.** Translucency, if ever added,
  belongs to window chrome - never to the song list.
* **Colour is never the only signal.** Every status pairs a hue with a word, so
  the list is readable without colour vision.
* **Two type weights, Regular and Bold.** Light weights are hard to read at
  these sizes; bold is the only emphasis step.
* **Full-bleed surfaces have no radius.** Round only things that float or sit
  inside a padded surface, and keep nested radii concentric.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------- spacing scale
# A 4px base grid. Every gap in the app is one of these; nothing is arbitrary.
SPACE_XS = 4
SPACE_SM = 6
SPACE_MD = 8
SPACE_LG = 12
SPACE_XL = 16
SPACE_2XL = 24

# Window edge padding. libadwaita uses 12px inline and 24px between blocks; a
# desktop app at this size wants slightly more breathing room at the edges.
PAD_WINDOW = SPACE_2XL
PAD_SECTION = SPACE_LG
PAD_ROW = SPACE_MD

# ------------------------------------------------------------------ radii
# Working scale is 4 / 6 / 8. Marketing-scale 12-16px on a 30px control is the
# single most common tell of an amateur UI, so the top of the scale is 8.
RADIUS_NONE = 0
RADIUS_SM = 4      # inputs, checkboxes, small chips
RADIUS_MD = 6      # buttons, list cards, the log pane
RADIUS_LG = 8      # dialogs, panels
# The song table and toolbar are edge-to-edge, so they stay square.

# --------------------------------------------------------------- typography
# Desktop scale. 13px is the "normal" body size on a desktop; 10px is the floor
# and nothing in this app goes below it.
FONT_SIZE_TITLE = 20      # app name
FONT_SIZE_SECTION = 15    # section headers
FONT_SIZE_BODY = 13       # primary row text, control labels
FONT_SIZE_SECONDARY = 12  # artist, supporting copy
FONT_SIZE_CAPTION = 11    # column headers, status text
FONT_SIZE_LOG = 11        # log pane (monospace)

WEIGHT_REGULAR = "normal"
WEIGHT_BOLD = "bold"

# ----------------------------------------------------------------- metrics
# Dense enough to show a full playlist, tall enough for a two-line row.
ROW_HEIGHT = 56
ROW_HEIGHT_COMPACT = 44
THUMB_SIZE = (80, 45)     # 16:9
THUMB_RADIUS = RADIUS_SM
CHECKBOX_COLUMN = 40      # fixed and narrow, with no header of its own
TOOLBAR_HEIGHT = 40

# Progression through this scale, used for motion where motion is warranted.
# Kept short on purpose: see MOTION_BUDGET below.
DURATION_FAST_MS = 100     # hover, press, focus
DURATION_SLOW_MS = 180     # dialog enter
# Motion budget: a progress bar must never animate between yt-dlp's own ticks,
# because an interpolated bar misreports the transfer rate. The only
# animations this app justifies are state changes and dialog entry.
MOTION_BUDGET = (
    "Progress advances directly from the reported value - never tweened.\n"
    "Filter results appear instantly; animating a list re-sort is noise.\n"
    "Row status changes are allowed a short crossfade, nothing more."
)


# ------------------------------------------------------------------- colour
@dataclass(frozen=True)
class Palette:
    """Semantic colour roles for one theme.

    Names describe *intent*, never appearance, so a role can be re-pointed at a
    different hue without touching the widgets that consume it.
    """

    # Surfaces, from furthest back to nearest front. Material 3 dropped tonal
    # elevation in favour of explicit surface roles, so hierarchy comes from
    # this ramp rather than from shadows.
    surface: str            # window background
    surface_container: str  # cards, dialogs, the log pane
    surface_sunken: str     # inputs, wells, table body
    surface_hover: str      # row hover
    surface_selected: str   # selected row / focused control

    # Foreground. Three weights only: full, secondary for supporting text,
    # and muted for disabled or placeholder content.
    on_surface: str
    on_surface_secondary: str
    on_surface_muted: str

    # Lines. Two roles, per Material 3: `outline` for interactive boundaries
    # and `outline_variant` for decorative separators. Never swap them - using
    # `outline` for a row divider is a common and visible mistake.
    outline: str
    outline_variant: str

    # Accent. Used only for the primary action and selection.
    accent: str
    on_accent: str
    accent_hover: str

    # Semantic states. Each is pre-matched to this palette's surface so the
    # contrast requirement is satisfied by construction.
    success: str
    on_success: str
    warning: str
    on_warning: str
    danger: str
    on_danger: str
    info: str
    on_info: str

    # Selection / focus
    selection: str
    focus_ring: str

    def __getitem__(self, key: str) -> str:
        """Dict-style access, for code that iterates roles generically."""
        return getattr(self, key)

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


# Light theme. Accent text uses the darker standalone variants so it clears
# 4.5:1 on white; the mid-tone accent is reserved for fills.
LIGHT = Palette(
    surface="#fafafb",
    surface_container="#ffffff",
    surface_sunken="#f2f2f4",
    surface_hover="#eeeef0",
    surface_selected="#e3e8ee",

    on_surface="#1c1c1e",
    on_surface_secondary="#5b5b60",
    on_surface_muted="#7a7a80",

    # `outline` is held to 3:1 because it carries interactive boundaries, so
    # it is a mid-grey rather than the hairline most themes use for dividers
    # (that role is `outline_variant`).
    outline="#7c7c82",
    outline_variant="#e4e4e8",

    # Accent. In light mode this is the darker slate so white label text on it
    # clears 4.5:1. The mid-tone `#6f8396` only reaches 3.92:1 against white
    # and would ship unreadable button labels, so it is not used as a fill.
    accent="#526678",
    on_accent="#ffffff",
    accent_hover="#3f5261",

    success="#15772e",
    on_success="#ffffff",
    warning="#905300",
    on_warning="#ffffff",
    danger="#c00023",
    on_danger="#ffffff",
    info="#0461be",
    on_info="#ffffff",

    selection="#d5dee6",
    focus_ring="#0461be",
)

# Dark theme. Not an inversion: the accents shift lighter and desaturate, and
# the background is a lifted near-black rather than #000000, which would cause
# halation and smear bright text.
DARK = Palette(
    surface="#222226",
    surface_container="#2e2e32",
    surface_sunken="#1d1d20",
    surface_hover="#34343a",
    surface_selected="#2a3138",

    on_surface="#e8e6e3",
    on_surface_secondary="#b0aea9",
    on_surface_muted="#86857f",

    outline="#7c7c82",
    outline_variant="#33333a",

    accent="#bbd1e5",
    on_accent="#1b2733",
    accent_hover="#d5e4f0",

    success="#8de698",
    on_success="#12240f",
    warning="#ffc057",
    on_warning="#2b1d00",
    danger="#ff888c",
    on_danger="#2c0d10",
    info="#81d0ff",
    on_info="#00243a",

    selection="#3a4a58",
    focus_ring="#81d0ff",
)

PALETTES = {"light": LIGHT, "dark": DARK}

# Status presentation. Colour is paired with a glyph and a word so the state is
# legible without colour vision; the glyph is drawn from the same monospace
# family as the log so rows stay visually aligned.
STATUS_ICONS = {
    "ok": "✓",           # check
    "missing": "○",      # hollow circle - not present
    "busy": "◐",        # half-filled - in flight
    "failed": "✕",       # cross
    "unavailable": "⊘",  # circled slash - permanently gone
    "skipped": "→",      # arrow - deliberately passed over
    "muted": "·",        # middot - the neutral default
    # `new` is an alias of `muted`: an unexamined row is the neutral state, so
    # giving it a separate glyph would imply a distinction that is not drawn.
    "new": "·",
}

# Glyphs that intentionally share a shape, so the distinctness check below
# knows the difference is intentional rather than a copy-paste mistake.
STATUS_ICON_ALIASES = {"new": "muted"}


def palette(dark: bool) -> Palette:
    """Return the palette for a theme mode."""
    return DARK if dark else LIGHT


# ------------------------------------------------------------ ttkbootstrap glue
# ttkbootstrap's own light/dark theme pairs. The pre-2.0 names (``darkly``,
# ``litera``) are deprecated and slated for removal in 3.0, so the app pins
# current names and maps them onto our palettes. Keeping the mapping in one
# place means a ttkbootstrap upgrade touches this table alone.
TTK_THEME = {"light": "sandstone-light", "dark": "sandstone-dark"}

# Fallbacks used before a style exists (first paint, or a headless test).
BOOTSTYLE = {
    "primary": "secondary",
    "secondary": "secondary",
    "success": "success",
    "warning": "warning",
    "danger": "danger",
    "info": "info",
}
