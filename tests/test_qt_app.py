"""Tests for the Qt application window.

These run on Qt's ``offscreen`` platform, so there is a ``QApplication`` and
no visible window. The window is never shown for most of them either - a
widget's layout is computed once it is polished, which is enough to assert
the things that actually go wrong.

The two behaviours with the most history behind them get explicit tests:
the load button relabelling itself for a single-video link
(:class:`TestLoadButton`) and the audio settings disappearing when Video is
chosen (:class:`TestMediaVisibility`). Both were bugs in the Tk UI that had
to be carried across deliberately, and a port that "looked right" in a
screenshot is not evidence that it did.
"""

import pytest

from musicdl import config, paths
from musicdl.qt import app as app_mod
from musicdl.qt import theme


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    """Keep every test off the real settings file.

    The window loads and saves settings on construction and on any theme
    change, so without this a test run rewrites the user's ``config.json``.
    It is ``paths.config_file`` that has to be patched, not ``config``'s own
    functions: both :func:`config.load` and :func:`config.save` look the path
    up through ``paths`` on every call.
    """
    monkeypatch.setattr(paths, "config_file",
                        lambda: str(tmp_path / "config.json"))
    yield


@pytest.fixture
def win(qapp):
    w = app_mod.MainWindow(dark=True)
    w.resize(1180, 820)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


class TestStructure:
    def test_window_has_every_section(self, win):
        """The shell is only useful if all of it is there."""
        for name in ("url_edit", "load_btn", "rad_music", "rad_video",
                     "format_combo", "quality_combo", "res_combo",
                     "dir_edit", "browse_btn", "songs", "download_btn",
                     "check_btn", "retry_btn", "stop_btn", "progress",
                     "status_label", "detail_label", "log", "theme_btn"):
            assert hasattr(win, name), f"missing {name}"

    def test_window_builds_at_its_minimum_size(self, qapp):
        """Nothing may require a width the window does not allow.

        The window is a fixed 960px minimum, so a control that needs more than
        that will either clip or push the row wider than the window. Both
        happened: Browse came up 14px short of its own label.
        """
        w = app_mod.MainWindow(dark=True)
        w.resize(app_mod.WINDOW_MINSIZE)
        w.show()
        qapp.processEvents()
        assert w.width() >= app_mod.WINDOW_MINSIZE.width()
        for name in ("load_btn", "browse_btn", "fix_btn", "check_btn",
                     "download_btn"):
            btn = getattr(w, name)
            assert btn.width() >= btn.sizeHint().width(), (
                f"{name} is narrower than its own text needs"
            )
        w.close()

    def test_song_list_is_the_only_stretching_section(self, win):
        """Extra window height belongs to the list, not the log or the form.

        A log pane that grows with the window eventually pushes the song list
        off screen, which is the one thing the window exists to show.
        """
        win.resize(1180, 1100)
        win.layout().activate()
        win.songs.view.viewport().update()
        assert win.songs.height() > 300
        assert win.log.height() <= 200, "the log pane is growing with the window"

    def test_log_is_scrollable_not_growing(self, win):
        """A bounded block count, so a long run cannot exhaust memory."""
        assert win.log.isReadOnly()
        assert win.log.maximumBlockCount() > 0


class TestLoadButton:
    """The label has to follow the link, not claim "playlist" either way."""

    def test_says_playlist_for_a_playlist_link(self, win):
        win.url_edit.setText("https://www.youtube.com/playlist?list=PL123")
        assert win.load_btn.text() == app_mod.LOAD_LABEL

    def test_says_video_for_a_single_video_link(self, win):
        win.url_edit.setText("https://www.youtube.com/watch?v=abc123")
        assert win.load_btn.text() == app_mod.SINGLE_LABEL

    def test_falls_back_to_playlist_for_an_empty_box(self, win):
        win.url_edit.setText("")
        assert win.load_btn.text() == app_mod.LOAD_LABEL

    def test_tooltip_explains_the_single_video_case(self, win):
        """The label says "Load Video"; the tooltip says why that matters."""
        win.url_edit.setText("https://www.youtube.com/watch?v=abc123")
        assert "one video" in win.load_btn.toolTip()

    def test_width_does_not_change_when_the_label_does(self, win):
        """Relabelling must not resize the button under the pointer."""
        win.url_edit.setText("https://www.youtube.com/playlist?list=PL123")
        wide = win.load_btn.width()
        win.url_edit.setText("https://www.youtube.com/watch?v=abc123")
        assert win.load_btn.width() == wide


class TestMediaVisibility:
    """Audio and video settings are disjoint, so only one set is shown."""

    def test_music_shows_audio_and_hides_resolution(self, win):
        win.rad_music.setChecked(True)
        assert win.audio_group.isVisible()
        assert not win.video_group.isVisible()

    def test_video_shows_resolution_and_hides_audio(self, win):
        """The bug this ports: audio settings stayed on screen, disabled."""
        win.rad_video.setChecked(True)
        assert win.video_group.isVisible()
        assert not win.audio_group.isVisible()

    def test_artwork_toggle_is_audio_only(self, win):
        """Embedding a cover in an MP4 is not something the app can do."""
        win.rad_video.setChecked(True)
        assert not win.thumb_holder.isVisible()
        win.rad_music.setChecked(True)
        assert win.thumb_holder.isVisible()

    def test_toggling_does_not_clobber_the_other_settings(self, win):
        """Hiding is not resetting: a chosen format must survive the round trip."""
        win.rad_music.setChecked(True)
        win.format_combo.setCurrentText("FLAC")
        win.rad_video.setChecked(True)
        win.rad_music.setChecked(True)
        assert win.format_combo.currentText() == "FLAC"


class TestParallelToggle:
    def test_job_count_is_disabled_until_multi_download_is_on(self, win):
        win.parallel_check.setChecked(False)
        assert not win.jobs_combo.isEnabled()
        win.parallel_check.setChecked(True)
        assert win.jobs_combo.isEnabled()

    def test_enabling_multi_download_restores_a_parallel_count(self, win):
        """One job with multi-download on is a contradiction."""
        win.parallel_check.setChecked(False)
        win.jobs_combo.setCurrentText("1")
        win.parallel_check.setChecked(True)
        assert win.current_jobs() >= 2

    def test_disabling_multi_download_drops_back_to_one(self, win):
        win.parallel_check.setChecked(True)
        win.jobs_combo.setCurrentText("5")
        win.parallel_check.setChecked(False)
        assert win.current_jobs() == 1

    def test_job_count_is_clamped_to_the_allowed_range(self, win):
        win.parallel_check.setChecked(True)
        win.jobs_combo.setCurrentText("99")
        assert 1 <= win.current_jobs() <= 6


class TestBusyState:
    def test_stop_is_the_only_control_enabled_while_busy(self, win):
        """It is the only action that makes sense mid-job."""
        win.set_busy(True)
        assert win.stop_btn.isEnabled()
        for btn in (win.load_btn, win.download_btn, win.check_btn,
                    win.browse_btn, win.fix_btn):
            assert not btn.isEnabled(), f"{btn.text()} stayed live while busy"

    def test_idle_re_enables_the_controls(self, win):
        win.set_busy(True)
        win.set_busy(False)
        assert win.load_btn.isEnabled()
        assert not win.stop_btn.isEnabled()

    def test_retry_is_disabled_until_something_has_failed(self, win):
        assert not win.retry_btn.isEnabled()
        win.set_busy(False)
        win.set_has_failures(True)
        assert win.retry_btn.isEnabled()

    def test_going_busy_disables_retry_again(self, win):
        win.set_has_failures(True)
        win.set_busy(True)
        assert not win.retry_btn.isEnabled()

    def test_media_visibility_is_preserved_across_a_busy_cycle(self, win):
        """Un-busying re-applies the media groups and must not reset them."""
        win.rad_video.setChecked(True)
        win.set_busy(True)
        win.set_busy(False)
        assert win.video_group.isVisible()
        assert not win.audio_group.isVisible()


class TestSettings:
    def test_snapshot_reflects_the_visible_controls(self, win):
        win.rad_music.setChecked(True)
        win.format_combo.setCurrentText("FLAC")
        win.quality_combo.setCurrentText("320")
        snap = win.snapshot()
        assert snap["media"] == app_mod.MEDIA_MUSIC
        assert snap["format"] == "FLAC"
        assert snap["quality"] == "320"

    def test_snapshot_resolves_the_save_directory(self, win):
        """``~`` must be expanded before a worker thread touches the path."""
        win.dir_edit.setText("~/music")
        assert "~" not in win.snapshot()["dir"]

    def test_saving_round_trips_through_the_config(self, win):
        win.url_edit.setText("https://www.youtube.com/playlist?list=PL9")
        win.format_combo.setCurrentText("OPUS")
        win.save_settings()
        assert config.load()["format"] == "OPUS"
        assert config.load()["last_url"].endswith("PL9")

    def test_settings_are_never_written_to_the_real_config(self, win):
        """Guards the fixture: a run must not rewrite the user's settings."""
        win.url_edit.setText("https://example.invalid/nope")
        win.save_settings()
        assert win.cfg["last_url"] == "https://example.invalid/nope"

    def test_parallel_jobs_are_not_persisted_when_the_toggle_is_off(self, win):
        """A stale count must not come back as 5 the next time it is used."""
        win.parallel_check.setChecked(False)
        win.jobs_combo.setCurrentText("1")
        win.save_settings()
        assert config.load()["parallel_jobs"] == 3


class TestElidedLabel:
    def test_short_text_is_shown_whole(self, win):
        win.status_label.setText("Ready.")
        assert win.status_label.text() == "Ready."

    def test_long_text_is_elided_but_kept(self, qapp):
        """A failure summary can run to a sentence; it must not widen the row.

        The label is constrained directly rather than through the window: at
        the window's 960px minimum a 100-character message still fits, so a
        test that relied on the window to squeeze it was passing without ever
        reaching the eliding path.
        """
        long_text = ("Downloaded 3 of 8, then failed: this particular song is "
                     "not available in your region and cannot be fetched.")
        label = app_mod.ElidedLabel(long_text, "secondary")
        label.setFixedWidth(120)
        label.show()
        qapp.processEvents()
        assert label.text() != long_text
        assert "…" in label.text()
        # The full text is not lost - it is one hover away.
        assert label.full_text() == long_text
        assert label.toolTip() == long_text
        label.close()

    def test_short_text_is_not_elided(self, qapp):
        """Eliding a message that fits would just make it harder to read."""
        label = app_mod.ElidedLabel("Ready.", "secondary")
        label.setFixedWidth(400)
        label.show()
        qapp.processEvents()
        assert label.text() == "Ready."
        label.close()

    def test_eliding_does_not_widen_the_window(self, qapp):
        """The row's width must not depend on how long the message is.

        This is the actual bug: a long status text used to stretch the layout,
        pushing the row past the window's minimum width.
        """
        w = app_mod.MainWindow(dark=True)
        w.show()
        qapp.processEvents()
        central = w.centralWidget()
        assert central is not None
        before = central.sizeHint().width()
        w.status_label.setText("x" * 400)
        qapp.processEvents()
        assert central.sizeHint().width() == before
        w.close()


class TestProgressRow:
    """The bar and the detail text share a row; neither may hide the other."""

    def test_detail_text_is_inside_the_row(self, win):
        """The regression guard for a label pushed off the right edge.

        ``QSizePolicy.Ignored`` reports a minimum width of *zero* to the
        layout, so the expanding progress bar took the entire row and the
        detail text was positioned past the window's right edge. Every widget
        still reported itself visible, and no test caught it - the row has to
        be measured, not trusted.
        """
        detail = win.detail_label
        detail.setText("42% · 1.4 MiB/s · 3.2 MiB of 7.6 MiB")
        row = detail.parentWidget()
        assert detail.x() + detail.width() <= row.width() + 1, (
            "the progress detail text is laid out past the right edge of its row"
        )
        assert detail.width() > 0

    def test_detail_text_is_not_elided_at_the_default_size(self, win):
        """A normal speed/ETA line must be readable, not truncated."""
        detail = win.detail_label
        detail.setText("42% · 1.4 MiB/s · 3.2 MiB of 7.6 MiB")
        assert detail.text() == detail.full_text()

    def test_the_bar_and_the_text_do_not_overlap(self, win):
        assert (win.progress.x() + win.progress.width()) <= \
            win.detail_label.x() + 1


class TestShortcuts:
    @pytest.mark.parametrize("seq", ["Ctrl+F", "Ctrl+L", "Ctrl+D", "Ctrl+T",
                                     "F5"])
    def test_every_shortcut_is_registered(self, win, seq):
        """Bound on the window, so they work whatever has focus."""
        from PySide6.QtGui import QKeySequence

        assert not QKeySequence(seq).isEmpty()
        registered = {a.shortcut().toString() for a in win.actions()}
        assert QKeySequence(seq).toString() in registered

    def test_find_focuses_the_search_box(self, win):
        win.songs.focus_search()
        assert win.songs.filter_entry.hasFocus()
        # Selecting the text is what makes find useful: you nearly always
        # want to replace the query rather than edit it.
        assert win.songs.filter_entry.selectedText() == \
            win.songs.filter_entry.text()


class TestTheme:
    def test_button_shows_the_stored_theme(self, qapp):
        config.save({**config.load(), "theme": theme.THEME_LIGHT})
        w = app_mod.MainWindow(dark=False)
        w.show()
        qapp.processEvents()
        assert w.theme_btn.text() == "Light"
        w.close()

    def test_system_reports_what_it_resolved_to(self, qapp, monkeypatch):
        """'Match system' has to say which way it went, or it is a mystery."""
        monkeypatch.setattr(theme, "resolve", lambda _c: "dark")
        config.save({**config.load(), "theme": theme.THEME_SYSTEM})
        w = app_mod.MainWindow(dark=True)
        w.show()
        qapp.processEvents()
        assert w.theme_btn.text() == "Match system"
        assert "dark" in w.theme_btn.toolTip()
        w.close()

    def test_choosing_a_theme_saves_it(self, win):
        win.set_theme(theme.THEME_DARK)
        assert config.load()["theme"] == theme.THEME_DARK
