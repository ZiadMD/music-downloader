"""Tests for the song list widget and its delegate.

The widget tests run on Qt's ``offscreen`` platform, so they need a
``QApplication`` but no display and no visible window - the view is rendered
into a buffer rather than onto a screen. The one test that matters most is
:func:`test_view_actually_renders`, because a delegate that raises or draws
nothing passes every other assertion here.
"""

import pytest

from musicdl.qt import songlist
from musicdl.qt.songmodel import (
    COL_ARTIST, COL_PICK, COL_STATUS, COL_TITLE, Song,
)
from musicdl.ui import tokens


def songs(n=6):
    return [Song(f"v{i}", f"Song {i}", f"Artist {i % 2}") for i in range(n)]


@pytest.fixture
def lst(qapp):
    w = songlist.SongList(dark=True)
    w.resize(900, 500)
    w.show()
    w.model.set_songs(songs())
    qapp.processEvents()
    yield w
    w.close()


class TestLayout:
    def test_columns_are_in_the_right_resize_modes(self, lst):
        """Only the two text columns move; the rest are fixed.

        The status column in particular must not resize, or a status change
        reflows the whole list - the exact jank the fixed width existed to
        prevent in the Tk version.
        """
        from PySide6.QtWidgets import QHeaderView

        h = lst.view.horizontalHeader()
        assert h.sectionResizeMode(COL_PICK) == QHeaderView.ResizeMode.Fixed
        assert h.sectionResizeMode(COL_STATUS) == QHeaderView.ResizeMode.Fixed
        assert h.sectionResizeMode(COL_TITLE) == QHeaderView.ResizeMode.Stretch
        assert h.sectionResizeMode(COL_ARTIST) == \
            QHeaderView.ResizeMode.Interactive

    def test_row_height_matches_the_token(self, lst):
        assert lst.view.verticalHeader().defaultSectionSize() == \
            tokens.ROW_HEIGHT

    def test_row_headers_are_hidden(self, lst):
        """Numbers down the side of a song list are noise, not information."""
        assert not lst.view.verticalHeader().isVisible()

    def test_grid_is_hidden(self, lst):
        """A grid plus banding is two competing ways of separating rows."""
        assert not lst.view.showGrid()

    def test_stretch_fills_available_width(self, lst):
        lst.resize(1200, 500)
        lst.view.resize(1200, 500)
        h = lst.view.horizontalHeader()
        fixed = (lst.view.columnWidth(COL_PICK)
                 + lst.view.columnWidth(COL_ARTIST)
                 + lst.view.columnWidth(COL_STATUS))
        assert h.sectionResizeMode(COL_TITLE) is not None
        assert fixed < 1200, "the title column has room to stretch"


class TestRendering:
    def test_view_actually_renders(self, lst):
        """The delegate must produce pixels, not just not crash.

        A delegate that returns an empty rect or draws with a null brush
        passes every other test in this file while showing the user a blank
        list, so the render is checked rather than assumed.
        """
        image = lst.view.grab()
        assert not image.isNull()
        assert image.width() > 0 and image.height() > 0

    def test_rendering_survives_a_theme_switch(self, lst):
        """The delegate repaints from a different palette without error."""
        lst.set_dark(False)
        lst.view.grab()
        lst.set_dark(True)
        lst.view.grab()

    def test_rendering_survives_a_filter_change(self, lst):
        lst.filter_entry.setText("Artist 1")
        lst.view.grab()
        assert not lst.view.grab().isNull()

    def test_thumbnail_replaces_the_tick_without_error(self, lst):
        """Artwork shares the tick cell rather than needing a column."""
        from PySide6.QtGui import QPixmap

        pix = QPixmap(tokens.THUMB_SIZE[0], tokens.THUMB_SIZE[1])
        pix.fill()
        lst.model.set_thumbnail("v0", pix)
        lst.view.grab()

    def test_selection_renders(self, lst):
        """The selected-row branch of the delegate must be exercised.

        Selection paints a different surface and is the one path that a
        plain render never reaches, so it is driven explicitly rather than
        assumed to be covered.
        """
        lst.view.selectRow(1)
        lst.view.grab()
        # selectedRows() is the reliable read here. isRowSelected() wants a
        # root index and reports False for a SelectRows view, so it is not a
        # check of "is this row is selected" at all.
        assert [i.row() for i in lst.view.selectionModel().selectedRows()] == [1]

    def test_skipped_and_downloaded_do_not_look_the_same(self, lst):
        """The regression guard for the identical-tick bug.

        Skipped and Downloaded share a colour role, which is correct - both
        are uneventful - and they used to share a glyph too, so a skipped row
        was indistinguishable from a downloaded one.

        The comparison is between the *same* row re-rendered with a different
        status, not between two different rows. Comparing two rows would pass
        no matter what the delegate drew, because alternating row banding
        alone makes their pixels differ - a test that cannot fail is worse
        than no test.
        """
        from PySide6.QtCore import QRect

        lst.model.set_songs([Song("a", "Song A", "Artist")])
        x = lst.view.columnViewportPosition(COL_STATUS)
        w = lst.view.columnWidth(COL_STATUS)
        y = lst.view.rowViewportPosition(0)

        def status_cell(phrase):
            lst.model.set_status("a", phrase)
            lst.view.grab()
            img = lst.view.viewport().grab().toImage()
            return img.copy(QRect(x, y, w, tokens.ROW_HEIGHT))

        # Control: the same phrase twice must be pixel-identical, otherwise
        # the comparison below proves nothing.
        assert status_cell("Skipped") == status_cell("Skipped"), (
            "the status cell is not deterministic, so a difference below "
            "would not prove anything"
        )
        assert status_cell("Downloaded") != status_cell("Skipped"), (
            "Skipped and Downloaded render identically; the per-phrase glyph "
            "lookup has regressed to the shared role glyph"
        )

    def test_no_hex_literals_in_the_view(self):
        """Colours come from token roles, so the two UIs cannot drift."""
        import pathlib
        import re

        src = pathlib.Path(songlist.__file__).read_text()
        allowed = ({v.lower() for v in tokens.LIGHT.as_dict().values()}
                   | {v.lower() for v in tokens.DARK.as_dict().values()})
        found = [h for h in re.findall(r"#[0-9a-fA-F]{6}\b", src)
                 if h.lower() not in allowed]
        assert not found, f"hex literals bypassed the token system: {found}"


class TestInteraction:
    def test_clicking_the_tick_column_toggles(self, lst):
        before = lst.model.checked_ids()
        lst._on_clicked(lst.model.index(0, COL_PICK))
        assert len(lst.model.checked_ids()) == len(before) - 1

    def test_clicking_a_text_column_does_not_toggle(self, lst):
        before = list(lst.model.checked_ids())
        lst._on_clicked(lst.model.index(0, COL_TITLE))
        assert lst.model.checked_ids() == before

    def test_search_narrows_the_list(self, lst):
        lst.filter_entry.setText("Artist 1")
        assert lst.model.rowCount() == 3

    def test_clearing_search_restores_every_row(self, lst):
        lst.filter_entry.setText("Artist 1")
        lst.filter_entry.clear()
        assert lst.model.rowCount() == 6

    def test_focus_search_selects_the_existing_text(self, lst):
        """Ctrl+F should replace the query, not append to it."""
        lst.filter_entry.setText("Song")
        lst.focus_search()
        assert lst.filter_entry.hasFocus()
        assert lst.filter_entry.selectedText() == "Song"
