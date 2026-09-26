"""The song list's data model, with no widgets in it.

Qt's ``QAbstractTableModel`` is a view contract, not a business-logic one, so
this module keeps the state and the filtering as plain Python and exposes
only the handful of methods Qt actually requires. Two reasons:

* the logic is testable with no ``QApplication`` and no display, which is
  most of the test suite
* a model that owns filtering, tick state and status is far easier to reason
  about than one that mixes those with ``beginResetModel`` bookkeeping

The row model is the same one the Tk list uses - :class:`Song` here is the
same shape as the entry dicts ``core.fetch_playlist`` returns - so both UIs
consume identical data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from .. import status as status_mod

__all__ = ["Song", "SongTableModel", "COLUMNS", "COL_PICK", "COL_TITLE",
           "COL_ARTIST", "COL_STATUS"]

# Column order is the display order. The tick column comes first because it is
# the thing you act on, and a leading action column is the convention in every
# list view worth copying.
COL_PICK, COL_TITLE, COL_ARTIST, COL_STATUS = range(4)
COLUMNS = ("", "Song", "Artist", "Status")

TICK = "✓"


@dataclass
class Song:
    """One row.

    ``checked`` and ``status`` live here rather than in parallel dicts: a
    ``dict`` keyed by video id was the Tk list's original shape and it made
    "which rows exist" and "which are ticked" two separate questions that
    could disagree. One object per row cannot get out of step with itself.
    """

    vid: str
    title: str
    uploader: str = ""
    checked: bool = True
    status: str = "Not downloaded"
    thumb: object | None = None   # QPixmap, kept here so the view can reach it

    @property
    def view(self) -> status_mod.StatusView:
        """The resolved glyph, word and colour role for the current status."""
        return status_mod.describe(self.status)


def _all_rows(songs: Iterable[Song]) -> list[Song]:
    return list(songs)


class SongTableModel(QAbstractTableModel):
    """Presents :class:`Song` rows to Qt, with search filtering applied.

    Filtering hides rows rather than removing them, so a row's tick state and
    status survive a search being cleared. That matters because the search box
    is for finding rows, not for choosing a subset to act on - and because
    "Tick all" has to mean *every* song, not just the visible ones.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._songs: list[Song] = []
        self._visible: list[int] = []   # indices into _songs, in display order
        self._query: str = ""

    # ------------------------------------------------------------------ Qt API
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._visible)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation == Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole):
            # The tick column has no header: it is a checkbox column, and
            # labelling it would be noise.
            return "" if section == COL_PICK else COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        song = self._song_at(index.row())
        if song is None:
            return None
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_PICK:
                return TICK if song.checked else ""
            if col == COL_TITLE:
                return song.title
            if col == COL_ARTIST:
                return song.uploader
            if col == COL_STATUS:
                return song.view.glyph
        elif role == Qt.ItemDataRole.ToolTipRole and col == COL_STATUS:
            # The column shows a glyph precisely so it never reflows; the full
            # phrase lives here for anyone who needs the detail.
            return song.view.text
        elif role == Qt.ItemDataRole.TextAlignmentRole and col == COL_STATUS:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_PICK:
            # Clickable, so the whole cell is a target rather than a glyph
            # you have to hit precisely.
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if (not index.isValid() or role != Qt.ItemDataRole.EditRole
                or index.column() != COL_PICK):
            return False
        song = self._song_at(index.row())
        if song is None:
            return False
        song.checked = bool(value)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
        return True

    # ------------------------------------------------------------- song access
    def _song_at(self, row: int) -> Song | None:
        if 0 <= row < len(self._visible):
            return self._songs[self._visible[row]]
        return None

    def song_at(self, row: int) -> Song | None:
        """The song shown at a visible row, or ``None`` if out of range."""
        return self._song_at(row)

    def row_of(self, vid: str) -> int:
        """The visible row showing ``vid``, or -1 if hidden or absent."""
        for row, idx in enumerate(self._visible):
            if self._songs[idx].vid == vid:
                return row
        return -1

    def checked_ids(self) -> list[str]:
        """Every checked video id, in playlist order - not visible order.

        Search filtering must not change what "download selected" means, so
        this walks the underlying list rather than the filtered one.
        """
        return [s.vid for s in self._songs if s.checked]

    def visible_songs(self) -> list[Song]:
        return [self._songs[i] for i in self._visible]

    # ------------------------------------------------------------- mutations
    def set_songs(self, songs: Iterable[Song]) -> None:
        """Replace every row, then re-apply the current filter."""
        self.beginResetModel()
        self._songs = _all_rows(songs)
        self._recompute_visible()
        self.endResetModel()

    def set_query(self, text: str) -> None:
        """Apply a search term. A reset is used because the visible set can
        change size, and partial inserts would leave gaps."""
        query = (text or "").strip().lower()
        if query == self._query:
            return
        self.beginResetModel()
        self._query = query
        self._recompute_visible()
        self.endResetModel()

    def _recompute_visible(self) -> None:
        if not self._query:
            self._visible = list(range(len(self._songs)))
            return
        q = self._query
        self._visible = [
            i for i, s in enumerate(self._songs)
            if q in f"{s.title} {s.uploader}".lower()
        ]

    def set_all_checked(self, on: bool) -> None:
        """Tick or untick every song, including ones the filter is hiding.

        This is the behaviour users expect from "Tick all" next to a search
        box: it is a bulk action on the playlist, not on the current view.
        """
        for s in self._songs:
            s.checked = on
        if self._songs:
            self.dataChanged.emit(
                self.index(0, COL_PICK),
                self.index(len(self._visible) - 1, COL_PICK),
                [Qt.ItemDataRole.DisplayRole])

    def toggle(self, vid: str) -> bool:
        """Flip one song's tick, returning its new value."""
        for s in self._songs:
            if s.vid == vid:
                s.checked = not s.checked
                row = self.row_of(vid)
                if row >= 0:
                    idx = self.index(row, COL_PICK)
                    self.dataChanged.emit(idx, idx,
                                          [Qt.ItemDataRole.DisplayRole])
                return s.checked
        return False

    def set_status(self, vid: str, text: str) -> None:
        """Update one row's status phrase and repaint just that cell."""
        for s in self._songs:
            if s.vid == vid:
                s.status = text
                row = self.row_of(vid)
                if row >= 0:
                    idx = self.index(row, COL_STATUS)
                    self.dataChanged.emit(idx, idx,
                                          [Qt.ItemDataRole.DisplayRole])
                return

    def set_status_all(self, text: str) -> None:
        """Give every row the same status, used for the initial state."""
        for s in self._songs:
            s.status = text
        if self._visible:
            self.dataChanged.emit(
                self.index(0, COL_STATUS),
                self.index(len(self._visible) - 1, COL_STATUS),
                [Qt.ItemDataRole.DisplayRole])

    def set_thumbnail(self, vid: str, pixmap) -> None:
        """Attach artwork to a row. Kept as a plain attribute.

        The pixmap cannot be a model role, because it is an object rather than
        a value Qt can compare - so the delegate reads it off the song and the
        model does not need a role for it.
        """
        for s in self._songs:
            if s.vid == vid:
                s.thumb = pixmap
                row = self.row_of(vid)
                if row >= 0:
                    idx = self.index(row, COL_PICK)
                    self.dataChanged.emit(idx, idx)
                return

    # ------------------------------------------------------------- iteration
    def __len__(self) -> int:
        return len(self._visible)

    def __iter__(self) -> Iterator[Song]:
        return iter(self.visible_songs())

    def __getitem__(self, row: int) -> Song:
        song = self._song_at(row)
        if song is None:
            raise IndexError(row)
        return song
