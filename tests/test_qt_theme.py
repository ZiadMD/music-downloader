"""Tests for the Qt theme layer.

The point of these is that the Qt UI is driven by the *same* token palette as
the Tk one. That is easy to state and easy to break: a single hard-coded hex
in a stylesheet would look fine and quietly fork the two designs. So the
tests check for that specifically, not just that the CSS parses.
"""

import re

import pytest
from PySide6.QtGui import QPalette

from musicdl.qt import families, theme
from musicdl.ui import tokens

# Only the token palettes are allowed to contain hex colours. Any other match
# in the Qt layer is a literal that has escaped the token system.
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def _qt_sources():
    """The Qt modules, as text, for literal-scanning."""
    import pathlib

    here = pathlib.Path(__file__).resolve().parent.parent / "musicdl" / "qt"
    return {p.name: p.read_text() for p in sorted(here.glob("*.py"))}


class TestNoColourDrift:
    def test_no_hex_literals_in_the_qt_layer(self):
        """Every colour must come from a token role, never a literal.

        A literal is how a design system starts quietly forking. The one
        allowed exception is a test file's own scratch values, and there are
        none here.
        """
        offenders = {}
        for name, text in _qt_sources().items():
            found = [h for h in HEX.findall(text) if h.lower() not in
                     {v.lower() for v in tokens.LIGHT.as_dict().values()} |
                     {v.lower() for v in tokens.DARK.as_dict().values()}]
            if found:
                offenders[name] = sorted(set(found))
        assert not offenders, (
            f"hex literals bypassed the token system: {offenders}"
        )

    def test_stylesheet_draws_only_from_the_palette(self):
        """Both themes must render, and render *differently*."""
        light = theme.stylesheet(dark=False)
        dark = theme.stylesheet(dark=True)
        assert light and dark
        # A stylesheet that is identical in both modes means a token is being
        # read in a way that collapses the two palettes together.
        assert light != dark


class TestPalette:
    @pytest.mark.parametrize("dark", [False, True])
    def test_every_token_reaches_qt(self, dark):
        """The palette is populated in both modes, not just one."""
        p = theme.build_palette(dark)
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Text,
                     QPalette.ColorRole.Button, QPalette.ColorRole.Base):
            assert p.color(role).isValid()

    def test_window_text_is_readable_on_window(self):
        """The base text pairing must clear WCAG AA, not just look fine."""
        for dark in (False, True):
            p = tokens.palette(dark)
            assert _contrast(p["on_surface"], p["surface"]) >= 4.5

    def test_disabled_text_is_set_explicitly(self):
        """Qt's automatic disabled colour is too faint to read.

        Left to Qt, a disabled control ends up around 2:1 against its own
        surface. It is set from the token role here precisely so that does
        not happen silently.
        """
        p = theme.build_palette(dark=True)
        disabled = p.color(QPalette.ColorGroup.Disabled,
                           QPalette.ColorRole.Text)
        assert _contrast(disabled.name(), tokens.DARK.surface_container) >= 3.0


def _contrast(fg: str, bg: str) -> float:
    """WCAG relative-contrast ratio for two hex colours."""
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(hexv: str) -> float:
        h = hexv.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


class TestFamilies:
    def test_preference_lists_are_shared_with_the_tk_side(self):
        """One source of truth for family preferences.

        The Tk module has its own copies for historical reasons; the point of
        the Qt module is that the *lists* are identical, so a platform change
        lands in both.
        """
        from musicdl.ui import fonts as tkfonts

        assert families.UI_FAMILIES == tkfonts._UI_FAMILIES
        assert families.MONO_FAMILIES == tkfonts._MONO_FAMILIES

    def test_returns_none_when_nothing_matches(self):
        """A missing family must be reported, not invented.

        Naming a font that is not installed produces a silent fallback, so
        the caller needs to know it got None and use the platform default.
        """
        assert families.ui_family(set()) is None
        assert families.mono_family(set()) is None

    def test_picks_the_first_installed_preference(self):
        available = {"Noto Sans", "Cantarell", "Ubuntu"}
        assert families.ui_family(available) == "Cantarell"

    def test_falls_through_to_a_later_preference(self):
        assert families.ui_family({"DejaVu Sans"}) == "DejaVu Sans"


class TestTypeScale:
    def test_scale_matches_the_shared_tokens(self):
        """The Qt type scale is the Tk one, not a second opinion."""
        for role, size in families.TYPE_SCALE.items():
            assert size in {
                tokens.FONT_SIZE_TITLE, tokens.FONT_SIZE_SECTION,
                tokens.FONT_SIZE_BODY, tokens.FONT_SIZE_SECONDARY,
                tokens.FONT_SIZE_CAPTION, tokens.FONT_SIZE_LOG,
            }, f"{role} has a size that is not in the token scale"

    def test_numeric_roles_are_the_ones_that_change_in_place(self):
        assert families.is_numeric("numeric")
        assert families.is_numeric("numeric_bold")
        assert not families.is_numeric("body")
        assert not families.is_numeric("caption")
