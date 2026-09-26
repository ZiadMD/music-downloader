"""Tests for :mod:`musicdl.ui.tokens`.

The point of these tests is enforcement, not coverage. A design token file is
only useful if the values it asserts are actually checked, so this module
verifies the accessibility properties the tokens claim - every foreground role
against every surface it is used on, in both themes.

A future edit that swaps a colour for a nicer-looking one will fail here rather
than shipping unreadable text.
"""

import pytest

from musicdl.ui import tokens

# WCAG 2.x thresholds.
AA_TEXT = 4.5          # normal-size body text
AA_LARGE = 3.0         # >=18.66px bold or >=24px
AA_NON_TEXT = 3.0      # UI component boundaries, graphical objects


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance of an ``#rrggbb`` colour."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (0.2126 * _srgb_to_linear(r)
            + 0.7152 * _srgb_to_linear(g)
            + 0.0722 * _srgb_to_linear(b))


def contrast(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two ``#rrggbb`` colours."""
    a, b = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# Foreground roles and the surfaces each is legitimately painted on. The
# list is explicit rather than "every role against every surface" so that a
# failure points at the actual pairing that is unreadable.
FOREGROUND_PAIRS = [
    # Primary and secondary text, on every surface it can appear on.
    ("on_surface", "surface", AA_TEXT),
    ("on_surface", "surface_container", AA_TEXT),
    ("on_surface", "surface_sunken", AA_TEXT),
    ("on_surface", "surface_hover", AA_TEXT),
    ("on_surface", "surface_selected", AA_TEXT),
    ("on_surface_secondary", "surface", AA_TEXT),
    ("on_surface_secondary", "surface_container", AA_TEXT),
    ("on_surface_secondary", "surface_sunken", AA_TEXT),
    ("on_surface_secondary", "surface_hover", AA_TEXT),
    ("on_surface_secondary", "surface_selected", AA_TEXT),
    # Muted text is used for placeholders and disabled rows, never for content
    # the user must read, so it is held to the large-text threshold. It still
    # has to clear the bar.
    ("on_surface_muted", "surface", AA_LARGE),
    ("on_surface_muted", "surface_sunken", AA_LARGE),
    # Semantic text sits on the plain surface in the status column.
    ("success", "surface", AA_TEXT),
    ("warning", "surface", AA_TEXT),
    ("danger", "surface", AA_TEXT),
    ("info", "surface", AA_TEXT),
    # Text on top of a filled accent or state colour.
    ("on_accent", "accent", AA_TEXT),
    ("on_success", "success", AA_TEXT),
    ("on_warning", "warning", AA_TEXT),
    ("on_danger", "danger", AA_TEXT),
    ("on_info", "info", AA_TEXT),
]

# Non-text roles: boundaries and graphical elements need only 3:1.
NON_TEXT_PAIRS = [
    ("outline", "surface", AA_NON_TEXT),
    ("outline", "surface_container", AA_NON_TEXT),
    ("focus_ring", "surface", AA_NON_TEXT),
    ("focus_ring", "surface_container", AA_NON_TEXT),
    ("focus_ring", "surface_selected", AA_NON_TEXT),
]


class TestColourContrast:
    @pytest.mark.parametrize("name", ["light", "dark"])
    @pytest.mark.parametrize("fg,bg,minimum", FOREGROUND_PAIRS)
    def test_foreground_is_readable(self, name, fg, bg, minimum):
        p = tokens.palette(name == "dark")
        ratio = contrast(p[fg], p[bg])
        assert ratio >= minimum, (
            f"{name}: {fg} ({p[fg]}) on {bg} ({p[bg]}) is {ratio:.2f}:1, "
            f"needs {minimum}:1"
        )

    @pytest.mark.parametrize("name", ["light", "dark"])
    @pytest.mark.parametrize("fg,bg,minimum", NON_TEXT_PAIRS)
    def test_non_text_is_distinguishable(self, name, fg, bg, minimum):
        p = tokens.palette(name == "dark")
        ratio = contrast(p[fg], p[bg])
        assert ratio >= minimum, (
            f"{name}: {fg} ({p[fg]}) on {bg} ({p[bg]}) is {ratio:.2f}:1, "
            f"needs {minimum}:1"
        )

    @pytest.mark.parametrize("name", ["light", "dark"])
    def test_selected_row_keeps_text_readable(self, name):
        """Selection must be visible without becoming unreadable."""
        p = tokens.palette(name == "dark")
        assert contrast(p["on_surface"], p["surface_selected"]) >= AA_TEXT
        # And the selection itself has to differ from the resting surface, or
        # the selected row is not actually distinguishable.
        assert p["surface_selected"] != p["surface"]

    @pytest.mark.parametrize("name", ["light", "dark"])
    def test_surfaces_are_distinct(self, name):
        """Each surface step must be a different value, or the ramp is flat."""
        p = tokens.palette(name == "dark")
        surfaces = [p["surface"], p["surface_container"],
                    p["surface_sunken"], p["surface_hover"]]
        assert len(set(surfaces)) == len(surfaces)

    @pytest.mark.parametrize("name", ["light", "dark"])
    def test_dark_background_is_not_pure_black(self, name):
        """Pure #000 causes halation; a lifted near-black is correct."""
        if name == "dark":
            p = tokens.palette(True)
            assert p["surface"].lower() != "#000000"
            assert relative_luminance(p["surface"]) > 0.0


class TestColourRoles:
    @pytest.mark.parametrize("name", ["light", "dark"])
    def test_every_role_is_a_hex_colour(self, name):
        p = tokens.palette(name == "dark")
        for role, value in p.as_dict().items():
            assert isinstance(value, str), f"{role} is not a string"
            assert value.startswith("#") and len(value) in (4, 7), (
                f"{name}.{role} = {value!r} is not a hex colour"
            )

    @pytest.mark.parametrize("name", ["light", "dark"])
    def test_state_colours_are_not_reused_as_accent(self, name):
        """Red must mean failure, never decoration."""
        p = tokens.palette(name == "dark")
        for role in ("success", "warning", "danger", "info"):
            assert p[role] != p["accent"], f"{role} collides with accent"

    def test_palettes_differ(self):
        assert tokens.LIGHT.as_dict() != tokens.DARK.as_dict()

    def test_palette_lookup_by_name(self):
        assert tokens.palette(True) is tokens.DARK
        assert tokens.palette(False) is tokens.LIGHT

    def test_palette_is_hashable_and_frozen(self):
        """Tokens must be immutable so a widget cannot mutate the system."""
        with pytest.raises(Exception):
            tokens.LIGHT.accent = "#000000"  # type: ignore[misc]

    def test_missing_role_raises_clearly(self):
        with pytest.raises(AttributeError):
            tokens.LIGHT["no_such_role"]  # type: ignore[index]


class TestScale:
    def test_spacing_uses_only_declared_steps(self):
        """Spacing must come from the scale, not from ad-hoc values.

        The scale is 4 / 6 / 8 / 12 / 16 / 24 rather than a strict 4px grid:
        6 exists so the spacing rhythm shares its base with the radius scale,
        which keeps related gaps and corners visually consistent.
        """
        allowed = {4, 6, 8, 12, 16, 24}
        for name in dir(tokens):
            if name.startswith(("SPACE_", "PAD_")):
                value = getattr(tokens, name)
                assert value in allowed, f"{name}={value} is not a scale step"

    def test_spacing_increases(self):
        steps = [tokens.SPACE_XS, tokens.SPACE_SM, tokens.SPACE_MD,
                 tokens.SPACE_LG, tokens.SPACE_XL, tokens.SPACE_2XL]
        assert steps == sorted(steps)
        assert len(set(steps)) == len(steps), "two steps share a value"

    def test_radii_increase(self):
        assert tokens.RADIUS_NONE < tokens.RADIUS_SM < tokens.RADIUS_MD < tokens.RADIUS_LG

    def test_radii_stay_small(self):
        """Above 8px reads as marketing-scale, not UI-scale."""
        assert tokens.RADIUS_LG <= 8

    def test_typography_decreases(self):
        sizes = [
            tokens.FONT_SIZE_TITLE,
            tokens.FONT_SIZE_SECTION,
            tokens.FONT_SIZE_BODY,
            tokens.FONT_SIZE_SECONDARY,
            tokens.FONT_SIZE_CAPTION,
        ]
        assert sizes == sorted(sizes, reverse=True)
        assert len(set(sizes)) == len(sizes), "two roles share a size"

    def test_no_text_below_the_desktop_floor(self):
        """10px is the floor; 9px is unreadable on a 1x display."""
        for name in dir(tokens):
            if name.startswith("FONT_SIZE_"):
                assert getattr(tokens, name) >= 10, f"{name} is below 10px"

    def test_only_two_weights(self):
        """Light weights are hard to read; bold is the only emphasis step."""
        assert {tokens.WEIGHT_REGULAR, tokens.WEIGHT_BOLD} == {"normal", "bold"}

    def test_log_font_is_smallest_but_readable(self):
        assert tokens.FONT_SIZE_LOG >= 10


class TestThemeMapping:
    @pytest.mark.parametrize("name", ["light", "dark"])
    def test_ttk_theme_is_not_a_legacy_name(self, name):
        """darkly/litera are pre-2.0 and slated for removal in 3.0."""
        theme = tokens.TTK_THEME[name]
        assert theme not in ("darkly", "litera")
        assert theme.endswith(name)

    def test_both_modes_have_a_theme(self):
        assert set(tokens.TTK_THEME) == {"light", "dark"}


class TestStatusIcons:
    REQUIRED = ("ok", "missing", "busy", "failed", "unavailable", "new")

    @pytest.mark.parametrize("state", REQUIRED)
    def test_every_state_has_a_glyph(self, state):
        """Status must pair colour with a glyph, never colour alone."""
        assert state in tokens.STATUS_ICONS
        assert tokens.STATUS_ICONS[state].strip()

    def test_glyphs_are_distinct(self):
        """Two states sharing a glyph would be ambiguous without colour.

        Intentional aliases are declared in STATUS_ICON_ALIASES, so a
        duplicated shape has to be an explicit decision.
        """
        aliased = {k for k in tokens.STATUS_ICON_ALIASES
                   if tokens.STATUS_ICON_ALIASES[k] in tokens.STATUS_ICONS}
        glyphs = [g.strip() for k, g in tokens.STATUS_ICONS.items()
                  if k not in aliased]
        assert len(set(glyphs)) == len(glyphs)

    def test_aliases_point_at_a_real_state(self):
        for alias, target in tokens.STATUS_ICON_ALIASES.items():
            assert alias in tokens.STATUS_ICONS
            assert target in tokens.STATUS_ICONS
            assert tokens.STATUS_ICONS[alias] == tokens.STATUS_ICONS[target]

    def test_glyphs_are_single_width(self):
        """Wide glyphs would break column alignment."""
        for state, glyph in tokens.STATUS_ICONS.items():
            assert len(glyph) == 1, f"{state} glyph {glyph!r} is not single-width"
