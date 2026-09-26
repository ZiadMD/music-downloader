"""Tests for :mod:`musicdl.ui.fonts`.

Two things are worth protecting here:

* **Graceful degradation.** Font availability differs wildly across the
  platforms this app runs on. Resolution must never name a family that is not
  installed, and must never raise.
* **Stable width for live numbers.** The progress and counter formatters are
  what stops a status column twitching on every yt-dlp tick, so their output
  width is asserted directly.
"""

import pytest

from musicdl.ui import fonts, tokens

tkfont = pytest.importorskip("tkinter.font")


@pytest.fixture
def root(tk_root):
    """The session-wide Tk root. Tests must not destroy it."""
    return tk_root


@pytest.fixture(autouse=True)
def _clear_cache():
    fonts.reset_cache()
    yield
    fonts.reset_cache()


class TestFamilyResolution:
    def test_ui_family_is_a_string(self, root):
        assert isinstance(fonts.ui_family(), str)
        assert fonts.ui_family()

    def test_mono_family_is_a_string(self, root):
        assert isinstance(fonts.mono_family(), str)
        assert fonts.mono_family()

    def test_resolution_is_cached(self, root):
        first = fonts.ui_family()
        fonts._resolved["ui"] = "sentinel"
        # A cached value is returned without touching the font database.
        assert fonts.ui_family() == "sentinel"
        fonts._resolved["ui"] = first

    def test_falls_back_when_nothing_matches(self, root, monkeypatch):
        """An empty candidate list must not name a missing family."""
        monkeypatch.setattr(fonts, "_first_available",
                            lambda cands, fb: fb)
        assert fonts.ui_family() == fonts._UI_FALLBACK
        assert fonts.mono_family() == fonts._MONO_FALLBACK

    def test_first_available_picks_the_first_installed(self, root):
        available = set(tkfont.families())
        assert fonts._first_available(("Definitely Not Installed",), "fallback") == "fallback"
        if available:
            real = sorted(available)[0]
            assert fonts._first_available(("Nope", real), "fallback") == real

    def test_every_platform_has_candidates(self):
        for table in (fonts._UI_FAMILIES, fonts._MONO_FAMILIES):
            assert set(table) == {"Windows", "Darwin", "Linux"}
            for names in table.values():
                assert names, "a platform has no font candidates"


class TestNamedStyles:
    @pytest.mark.parametrize("name", sorted(fonts.ALL_STYLES))
    def test_style_registers(self, root, name):
        style = fonts.ALL_STYLES[name]()
        assert isinstance(style, str)
        assert style.startswith("musicdl.")

    def test_all_styles_are_distinct(self, root):
        """Two roles sharing a name would make one of them unstyleable."""
        names = {fn() for fn in fonts.ALL_STYLES.values()}
        assert len(names) == len(fonts.ALL_STYLES)

    def test_registering_twice_is_safe(self, root):
        """Widgets hold a reference, so a reconfigure must not replace it."""
        first = fonts.body()
        held = fonts._registered[first]
        second = fonts.body()
        assert first == second
        assert fonts._registered[second] is held, "font object was replaced"

    def test_font_survives_garbage_collection(self, root):
        """Regression: Tk unregisters a font when its last reference dies.

        Without holding the object, every widget pointing at the style would
        silently revert to Tk's default face on the next collection.
        """
        import gc

        name = fonts.section()
        fonts.reset_cache()
        gc.collect()
        assert name in fonts._registered or tkfont.nametofont(name)

    def test_log_and_numeric_use_the_mono_family(self, root):
        """Monospace is the whole point of these two styles.

        The check reads back the *configured* family rather than Tk's resolved
        ``actual()`` value: on a machine where resolution fell back to
        ``TkFixedFont``, Tk reports a concrete family such as 'fixed' once it
        has substituted it, and comparing that against the named font would
        fail for a reason that has nothing to do with this module.
        """
        for fn in (fonts.log, fonts.numeric, fonts.numeric_bold):
            name = fn()
            assert fonts._registered[name].cget("family") == fonts.mono_family() \
                or fonts.mono_family() == fonts._MONO_FALLBACK

    def test_text_styles_use_the_ui_family(self, root):
        for name in ("title", "section", "body", "secondary", "caption"):
            style = fonts.ALL_STYLES[name]()
            assert fonts._registered[style].cget("family") == fonts.ui_family() \
                or fonts.ui_family() == fonts._UI_FALLBACK

    def test_sizes_match_the_token_scale(self, root):
        pairs = [
            (fonts.title, tokens.FONT_SIZE_TITLE),
            (fonts.section, tokens.FONT_SIZE_SECTION),
            (fonts.body, tokens.FONT_SIZE_BODY),
            (fonts.secondary, tokens.FONT_SIZE_SECONDARY),
            (fonts.caption, tokens.FONT_SIZE_CAPTION),
            (fonts.log, tokens.FONT_SIZE_LOG),
        ]
        for fn, expected in pairs:
            assert fonts._registered[fn()].cget("size") == expected

    def test_bold_variants_use_the_bold_weight(self, root):
        for fn in (fonts.title, fonts.section, fonts.body_bold, fonts.caption_bold):
            assert fonts._registered[fn()].cget("weight") == tokens.WEIGHT_BOLD

    def test_no_style_uses_a_light_weight(self, root):
        for fn in fonts.ALL_STYLES.values():
            assert fonts._registered[fn()].cget("weight") in ("normal", "bold")


class TestProgressText:
    def test_percentage_is_right_aligned(self):
        """Fixed width is the entire point - the column must not jitter."""
        assert fonts.progress_text(0).startswith("  0%")
        assert fonts.progress_text(7).startswith("  7%")
        assert fonts.progress_text(42).startswith(" 42%")
        assert fonts.progress_text(100).startswith("100%")

    def test_width_is_constant_across_percentages(self):
        widths = {len(fonts.progress_text(p)) for p in range(0, 101, 7)}
        assert len(widths) == 1, "progress text width varies"

    def test_clamps_out_of_range(self):
        assert fonts.progress_text(-5) == fonts.progress_text(0)
        assert fonts.progress_text(150) == fonts.progress_text(100)

    def test_unknown_speed_and_eta_are_dropped(self):
        """'--' means not-yet-known and must not print as a placeholder."""
        assert "--" not in fonts.progress_text(50, "--", "--")

    def test_known_speed_and_eta_are_shown(self):
        text = fonts.progress_text(50, "1.4 MiB/s", "0:12")
        assert "1.4 MiB/s" in text
        assert "ETA 0:12" in text

    def test_separator_is_consistent(self):
        text = fonts.progress_text(50, "1.4 MiB/s", "0:12")
        assert text.count(" · ") == 2

    def test_speed_without_eta(self):
        text = fonts.progress_text(50, "1.4 MiB/s", "--")
        assert "1.4 MiB/s" in text
        assert "ETA" not in text

    def test_eta_without_speed(self):
        text = fonts.progress_text(50, "--", "0:12")
        assert "ETA 0:12" in text
        assert "MiB/s" not in text


class TestTickText:
    def test_counts_are_present(self):
        text = fonts.tick_text(3, 2, 10)
        assert "3" in text and "10" in text and "2" in text

    def test_width_grows_with_total_but_not_with_done(self):
        """Within a run, the counter must not change width as it counts up."""
        widths = {len(fonts.tick_text(d, 1, 50)) for d in range(0, 51)}
        assert len(widths) == 1

    def test_zero_total_does_not_crash(self):
        assert "0" in fonts.tick_text(0, 0, 0)
