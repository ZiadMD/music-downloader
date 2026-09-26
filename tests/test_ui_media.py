"""Tests for the settings that apply to the chosen media type.

Audio and video have disjoint settings, and the two bugs these guard against
were both about showing the user choices that do not apply: a load button
labelled "playlist" when the field accepts a single video, and audio
settings still on screen after switching to video.

These drive the real widgets, because the whole point is which widgets are
*visible* - a unit test on a helper would pass while the UI stayed broken.
"""

import pytest

import tkinter as tk

from musicdl.ui import app as app_mod


@pytest.fixture
def app(tk_root, monkeypatch):
    """The real main window, on a throwaway config.

    Each test gets its own Toplevel rather than the shared session root. A
    Toplevel can be destroyed without taking the Tcl interpreter's font
    database with it - destroying the session root itself would break every
    later test, which is why conftest.py keeps that one alive.
    """
    # Keep the developer's own settings out of the test.
    monkeypatch.setattr(app_mod.config, "load", lambda: app_mod.config._defaults())
    win = tk.Toplevel(tk_root)
    win.geometry("+2000+2000")
    a = app_mod.App(win)
    win.update()
    yield a
    a.table._loader.shutdown()
    win.destroy()


def visible(widget):
    return bool(widget.grid_info())


class TestMediaTypeVisibility:
    def test_music_shows_audio_and_hides_resolution(self, app):
        app.media_var.set("Music")
        app._on_media_change()
        app.root.update()
        assert visible(app.format_combo)
        assert visible(app.quality_combo)
        assert not visible(app.res_combo)

    def test_video_hides_audio_entirely(self, app):
        """The reported bug: audio settings stayed on screen when greyed out."""
        app.media_var.set("Video")
        app._on_media_change()
        app.root.update()
        assert not visible(app.format_combo)
        assert not visible(app.quality_combo)
        assert not visible(app.audio_label)
        assert not visible(app.quality_label)

    def test_video_shows_resolution(self, app):
        app.media_var.set("Video")
        app._on_media_change()
        app.root.update()
        assert visible(app.res_combo)
        assert visible(app.res_label)

    def test_switching_back_restores_audio(self, app):
        """Hiding has to be reversible, or the panel is a one-way door."""
        for media in ("Video", "Music", "Video", "Music"):
            app.media_var.set(media)
            app._on_media_change()
            app.root.update()
            want_audio = media == "Music"
            assert visible(app.format_combo) is want_audio
            assert visible(app.res_combo) is not want_audio

    def test_video_hides_the_artwork_toggle(self, app):
        """A cover image cannot be embedded in an MP4, so do not offer it."""
        app.media_var.set("Video")
        app._on_media_change()
        app.root.update()
        assert not visible(app.thumb_holder)

    def test_hidden_widgets_are_disabled_too(self, app):
        """Hidden is not the same as inert.

        A hidden widget that still takes a tab stop would make keyboard
        navigation appear to skip through controls the user cannot see.
        """
        app.media_var.set("Video")
        app._on_media_change()
        app.root.update()
        for w in app.audio_widgets:
            assert not visible(w)


class TestLoadButtonLabel:
    """The button accepts a playlist or a video, so the label must follow."""

    def _label_for(self, app, url):
        app.url_var.set(url)
        app.root.update()
        return app.load_btn.cget("text")

    def test_empty_field_claims_nothing(self, app):
        assert self._label_for(app, "") == app_mod.LOAD_LABEL

    def test_playlist_link_says_playlist(self, app):
        url = "https://www.youtube.com/playlist?list=PLabcdef"
        assert self._label_for(app, url) == app_mod.LOAD_LABEL

    def test_watch_link_says_video(self, app):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert self._label_for(app, url) == app_mod.SINGLE_LABEL

    def test_short_link_says_video(self, app):
        assert self._label_for(app, "https://youtu.be/dQw4w9WgXcQ") \
            == app_mod.SINGLE_LABEL

    def test_watch_link_with_a_list_param_still_says_video(self, app):
        """YouTube decorates shared links with ``list=`` even for one video.

        This is the case that made the old label actively misleading: the
        label said "playlist" while the app was about to download one video.
        """
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabcdef"
        assert self._label_for(app, url) == app_mod.SINGLE_LABEL

    def test_both_labels_are_the_same_width(self, app):
        """Relabelling must not resize the button out from under a click."""
        app.url_var.set("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        app.root.update()
        video_width = app.load_btn.cget("width")
        app.url_var.set("https://www.youtube.com/playlist?list=PLabcdef")
        app.root.update()
        assert app.load_btn.cget("width") == video_width
