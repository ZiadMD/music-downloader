"""Tests for the shared status resolution and the Qt song model.

The status tests are here rather than in a Qt file because the logic is
shared. The parity test is the important one: it asserts the Tk list and the
Qt model render the same phrase identically, because a status that reads one
way in one UI and another way in the other is worse than either being wrong
on its own.
"""

import pytest

from musicdl import status as status_mod
from musicdl.status import GLYPH_OVERRIDES
from musicdl.qt.songmodel import (
    COL_PICK, COL_STATUS, COL_TITLE, Song, SongTableModel,
)
from musicdl.ui import tokens


@pytest.mark.usefixtures("qapp")
class TestStatusResolution:
    @pytest.mark.parametrize("phrase,role", [
        ("Downloaded", "ok"),
        ("Skipped", "ok"),
        ("Failed", "missing"),
        ("Unavailable", "missing"),
        ("Downloading 42% · 1.4 MiB/s", "busy"),
        ("Waiting...", "busy"),
        ("Pending", "busy"),
        ("Not downloaded", "muted"),
    ])
    def test_phrase_maps_to_role(self, phrase, role):
        assert status_mod.role_for(phrase) == role

    def test_trailing_ellipsis_is_stripped(self):
        """"Waiting..." has to match its own key, punctuation and all."""
        assert status_mod.role_for("Waiting...") == status_mod.role_for("Waiting")

    def test_live_reading_survives(self):
        """A progress reading is more useful than the bare word."""
        v = status_mod.describe("Downloading 42% · 1.4 MiB/s")
        assert v.text == "Downloading 42% · 1.4 MiB/s"
        assert v.role == "busy"

    def test_glyph_and_word_both_present(self):
        """Two signals, not one: colour is never the only cue."""
        v = status_mod.describe("Failed")
        assert v.glyph
        assert v.word
        assert v.role

    def test_unknown_phrase_is_not_terminal(self):
        assert status_mod.role_for("Something new") == "muted"

    def test_glyphs_are_single_width(self):
        """A wide glyph would break column alignment."""
        for role in ("ok", "missing", "busy", "failed", "unavailable",
                     "skipped", "muted"):
            assert len(tokens.STATUS_ICONS[role]) == 1, role

    def test_terminal_states_are_recognised(self):
        """A refresh must not overwrite a row that is still in flight."""
        assert status_mod.is_terminal_failure("Downloading 10%")
        assert status_mod.is_terminal_failure("Failed")
        assert not status_mod.is_terminal_failure("Downloaded")

class TestToolkitParity:
    def test_qt_and_tk_agree_on_every_status(self):
        """The two UIs must render a status identically.

        ``PlaylistTable._status_tag`` is the Tk implementation and
        ``status.role_for`` is the shared one. They are compared directly so a
        future edit to either one cannot silently fork the two UIs.
        """
        from musicdl.ui.widgets import PlaylistTable

        phrases = ["Downloaded", "Skipped", "Failed", "Unavailable",
                   "Downloading 42% · 1.4 MiB/s", "Waiting...",
                   "Pending", "Not downloaded", "New", "Whatever"]
        for phrase in phrases:
            assert PlaylistTable._status_tag(phrase) == status_mod.role_for(
                phrase), f"toolkits disagree about {phrase!r}"

    @pytest.mark.parametrize("phrase,role", [
        ("Downloaded", "ok"), ("Skipped", "ok"), ("Failed", "missing"),
        ("Unavailable", "missing"), ("Downloading 42%", "busy"),
        ("Not downloaded", "muted"),
    ])
    def test_glyph_comes_from_the_shared_token_table(self, phrase, role):
        """The glyph comes from the shared token table, never a local copy."""
        assert status_mod.describe(phrase).glyph in tokens.STATUS_ICONS.values()

    def test_colour_role_may_be_shared_but_glyph_must_not(self):
        """Skipped is coloured like Downloaded but must not *look* like it.

        Both resolve to the ``ok`` role, because the colour should be the
        same: neither is a problem. But the first render showed the identical
        tick for both, and a user scanning the list could not tell a
        deliberate skip from a completed download. The glyph is therefore
        looked up by phrase, not by role.
        """
        skipped = status_mod.describe("Skipped")
        done = status_mod.describe("Downloaded")
        assert skipped.role == done.role == "ok"
        assert skipped.glyph != done.glyph
        assert skipped.glyph == tokens.STATUS_ICONS["skipped"]

    @pytest.mark.parametrize("phrase,glyph_key", [
        ("Downloaded", "ok"), ("Skipped", "skipped"), ("Failed", "failed"),
        ("Unavailable", "unavailable"), ("Downloading 42%", "busy"),
        ("Pending", "busy"), ("Not downloaded", "muted"),
    ])
    def test_every_phrase_gets_a_drawable_shape(self, phrase, glyph_key):
        """Qt draws a shape per glyph key, so every key must be drawable."""
        from musicdl.qt.statusglyph import GLYPH_SHAPES

        key = GLYPH_OVERRIDES.get(
            phrase.split(" ", 1)[0].lower().rstrip(".…"),
            status_mod.role_for(phrase))
        assert key == glyph_key
        assert key in GLYPH_SHAPES


@pytest.mark.usefixtures("qapp")
class TestSongModel:
    @staticmethod
    def songs(n=6):
        return [Song(f"v{i}", f"Song {i}", f"Artist {i % 2}")
                for i in range(n)]
        return [Song(f"v{i}", f"Song {i}", f"Artist {i % 2}") for i in range(n)]

    def test_row_count(self, qapp):
        m = SongTableModel()
        m.set_songs(self.songs())
        assert m.rowCount() == 6
        assert m.columnCount() == 4

    def test_pick_column_has_no_header(self, qapp):
        from PySide6.QtCore import Qt

        m = SongTableModel()
        m.set_songs(self.songs())
        assert m.headerData(COL_PICK, Qt.Orientation.Horizontal) == ""
        assert m.headerData(COL_TITLE, Qt.Orientation.Horizontal) == "Song"

    def test_filtering_narrows_without_losing_rows(self, qapp):
        m = SongTableModel()
        m.set_songs(self.songs())
        m.set_query("Artist 1")
        assert m.rowCount() == 3
        m.set_query("")
        assert m.rowCount() == 6

    def test_tick_all_covers_hidden_rows(self, qapp):
        """A bulk action means the whole playlist, not the current view.

        Ticking only what the search happens to be showing is the classic
        filtered-list bug: the user searches to check one row, clears the box,
        and finds half the playlist silently unticked.
        """
        m = SongTableModel()
        m.set_songs(self.songs())
        m.set_query("Artist 1")
        m.set_all_checked(False)
        assert m.checked_ids() == []
        m.set_query("")
        m.set_all_checked(True)
        assert len(m.checked_ids()) == 6

    def test_checked_ids_ignore_the_filter(self, qapp):
        m = SongTableModel()
        m.set_songs(self.songs())
        m.set_query("Artist 1")
        assert len(m.checked_ids()) == 6

    def test_status_cell_shows_the_glyph_not_the_phrase(self, qapp):
        """The column is sized to the glyph so rows never reflow."""
        m = SongTableModel()
        m.set_songs(self.songs())
        m.set_status("v1", "Failed")
        cell = m.data(m.index(1, COL_STATUS))
        assert cell in tokens.STATUS_ICONS.values()
        # "Failed" gets its own glyph, distinct from the other "missing"
        # role phrases, which is what the delegate draws.
        assert cell == tokens.STATUS_ICONS["failed"]

    def test_status_tooltip_carries_the_full_phrase(self, qapp):
        from PySide6.QtCore import Qt

        m = SongTableModel()
        m.set_songs(self.songs())
        m.set_status("v1", "Downloading 42% · 1.4 MiB/s")
        tip = m.data(m.index(1, COL_STATUS), Qt.ItemDataRole.ToolTipRole)
        assert tip == "Downloading 42% · 1.4 MiB/s"

    def test_hidden_rows_are_not_reported_as_visible(self, qapp):
        """A status update on a filtered-out row must not crash or leak."""
        m = SongTableModel()
        m.set_songs(self.songs())
        m.set_query("Artist 1")
        m.set_status("v0", "Failed")     # hidden
        assert m.row_of("v0") == -1
        m.set_query("")
        assert m.row_of("v0") == 0

    def test_toggle_flips_one_row(self, qapp):
        m = SongTableModel()
        m.set_songs(self.songs())
        assert m.toggle("v2") is False
        assert m.toggle("v2") is True

    def test_out_of_range_row_is_none(self, qapp):
        m = SongTableModel()
        m.set_songs(self.songs(2))
        assert m.song_at(9) is None
        with pytest.raises(IndexError):
            _ = m[9]
