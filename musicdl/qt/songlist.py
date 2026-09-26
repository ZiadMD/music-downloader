"""The song list widget: a table view plus a custom delegate.

Where the Tk list used a ``Treeview``, this is a ``QTableView`` with a
``QStyledItemDelegate``. That is the bigger half of why the Qt port is
worth doing - a delegate can paint per-row backgrounds, per-role foregrounds
and rounded artwork, none of which a stylesheet can express, and the view
gives real column resizing and sorting for free.

The delegate is where the token palette is actually drawn. Every colour it
paints comes from a token role via :mod:`musicdl.qt.theme`; there are no
literals here, and a test scans for them.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QStyle, QStyledItemDelegate, QTableView, QVBoxLayout, QWidget,
)

from .. import status as status_mod
from ..ui import tokens
from . import fonts
from .songmodel import (
    COL_ARTIST, COL_PICK, COL_STATUS, COL_TITLE, SongTableModel, TICK,
)

__all__ = ["SongList", "SongDelegate"]

# Width of the tick/artwork column. Sized to the 16:9 artwork at the token row
# height plus a little slack, not to a check mark.
THUMB_COLUMN = 76


class SongDelegate(QStyledItemDelegate):
    """Paints a row: the tick, the artwork, the text, and the status.

    Everything is drawn from a rectangle the view hands us, so there is no
    nested-widget cost per row - which is what a ``Treeview`` with embedded
    images cannot avoid, and why a 500-song playlist was slow to scroll.
    """

    def __init__(self, dark: bool, parent=None) -> None:
        super().__init__(parent)
        self._dark = dark

    def set_dark(self, dark: bool) -> None:
        self._dark = dark

    # ------------------------------------------------------------- painting
    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        from . import theme

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect: QRect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        # Selection and hover are drawn first and fill the whole row, so the
        # text on top is never clipped by a per-cell background.
        if selected:
            painter.fillRect(rect, theme.qcolor("surface_selected", self._dark))
        elif hovered:
            painter.fillRect(rect, theme.qcolor("surface_hover", self._dark))

        # Banding is positional, so it is applied by row index rather than
        # attached to the song. A band that moved with the row would leave a
        # gap in the pattern the moment a search reordered the list.
        if not selected and (index.row() % 2):
            painter.fillRect(
                rect, theme.qcolor("surface_subtle", self._dark))

        col = index.column()
        model = index.model()
        if col == COL_PICK:
            self._paint_pick(painter, rect, index, model, selected)
        elif col == COL_STATUS:
            self._paint_status(painter, rect, index, selected)
        else:
            self._paint_text(painter, rect, index, col, selected)
        painter.restore()

    def _paint_pick(self, painter, rect, index, model, selected) -> None:
        """The tick column: artwork once it has arrived, else a glyph.

        The tick is centred rather than left-aligned because it is the thing
        you act on, and a centre line makes the eye travel less across a tall
        list. It is a glyph rather than a real checkbox so that a whole cell
        can be clicked - a 13px checkbox is a fiddly target, and the Tk list's
        biggest usability complaint was exactly that.
        """
        from . import theme

        song = model.song_at(index.row())
        if song is None:
            return
        if song.thumb is not None:
            self._paint_thumb(painter, rect, song.thumb)
            return
        painter.setPen(theme.qcolor("accent", self._dark))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), TICK)

    def _paint_thumb(self, painter, rect: QRect, pixmap) -> None:
        """Draw the artwork centred in the cell, fitted to the row height.

        The width is derived from the height rather than using the token's
        16:9 width, because a fixed width that exceeds the column is what made
        the artwork spill past the tick cell's edge in the first render.
        """
        avail = min(rect.width() - tokens.SPACE_XS, rect.height()
                    - tokens.SPACE_SM)
        if avail <= 0:
            return
        scaled = pixmap.scaled(
            int(avail), int(avail), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        x = rect.x() + (rect.width() - scaled.width()) // 2
        y = rect.y() + (rect.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

    def _paint_text(self, painter, rect, index, col, selected) -> None:
        from . import theme

        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        role = "secondary" if col == COL_ARTIST else "body"
        fg = "on_surface" if col == COL_TITLE else "on_surface_secondary"
        painter.setFont(fonts.font(role))
        painter.setPen(theme.qcolor(fg, self._dark))
        # A little horizontal padding so text never touches the cell edge.
        inner = rect.adjusted(tokens.SPACE_MD, 0, -tokens.SPACE_MD, 0)
        fm = QFontMetrics(painter.font())
        elided = fm.elidedText(str(text), Qt.TextElideMode.ElideRight,
                               inner.width())
        painter.drawText(inner, int(Qt.AlignmentFlag.AlignVCenter
                                     | Qt.AlignmentFlag.AlignLeft), elided)

    def _paint_status(self, painter, rect, index, selected) -> None:
        """The status shape, tinted by the row's semantic role.

        Colour is never the only signal, and neither is the shape: the full
        phrase is in the tooltip and the word is what makes it unambiguous.
        The shape is drawn rather than set as text because the UI font
        supports none of the status characters - see
        :mod:`musicdl.qt.statusglyph`.
        """
        from . import theme
        from .statusglyph import GLYPH_SHAPES, paint_glyph

        model = index.model()
        song = model.song_at(index.row())
        if song is None:
            return
        # The glyph key is the token's own, so the shape and the character
        # stay in step: "skipped" and "ok" share a colour role but not a
        # shape, because they are different events.
        key = GLYPH_SHAPES.get(status_mod.glyph_key(song.status), "dot")
        fg = _STATUS_TOKEN.get(song.view.role, "on_surface_muted")
        paint_glyph(painter, key, QRectF(rect), theme.qcolor(fg, self._dark))

    # --------------------------------------------------------------- metrics
    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), tokens.ROW_HEIGHT)

    def editorForEvent(self, event, model, option, index):
        """No in-place editor.

        A ``Treeview`` gives you a free checkbox column; a table view does
        not, and the obvious Qt answer - an editable cell that opens a
        spinbox or line edit when clicked - is wrong for a tick. Toggling on
        click is handled by the view itself, which is simpler and matches
        what the Tk list did.
        """
        return None


# Maps a semantic status role onto the token role that paints it. Kept here
# rather than in the model because it is a *presentation* decision: the same
# status could be painted from a different token in a future theme.
_STATUS_TOKEN = {
    "ok": "success",
    "busy": "info",
    "missing": "danger",
    "muted": "on_surface_muted",
}


class SongList(QWidget):
    """The song list: search box, tick-all controls, and the table."""

    checked_changed = Signal()
    status_activated = Signal(str, str)   # vid, action

    def __init__(self, dark: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._dark = dark
        self.model = SongTableModel(self)
        self._delegate = SongDelegate(dark, self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(tokens.SPACE_MD)

        # The search box and the bulk toggles share one row above the table,
        # because both act on the list and neither is a separate section.
        bar = QWidget()
        blay = QHBoxLayout(bar)
        blay.setContentsMargins(0, 0, 0, 0)
        blay.setSpacing(tokens.SPACE_SM)

        self.filter_entry = QLineEdit()
        self.filter_entry.setPlaceholderText("Search songs")
        self.filter_entry.setClearButtonEnabled(True)
        self.filter_entry.textChanged.connect(self._on_search_changed)
        blay.addWidget(self.filter_entry, 1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("secondary")
        blay.addWidget(self.count_label, 0)

        tick_all_btn = QPushButton("Tick all")
        tick_all_btn.setObjectName("ghost")
        tick_all_btn.clicked.connect(lambda: self.set_all_checked(True))
        blay.addWidget(tick_all_btn, 0)

        untick_all_btn = QPushButton("Untick all")
        untick_all_btn.setObjectName("ghost")
        untick_all_btn.clicked.connect(lambda: self.set_all_checked(False))
        blay.addWidget(untick_all_btn, 0)

        lay.addWidget(bar)

        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(self._delegate)
        self.view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setShowGrid(False)
        self.view.setWordWrap(False)
        self.view.setAlternatingRowColors(False)   # the delegate does the banding
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(tokens.ROW_HEIGHT)
        self.view.horizontalHeader().setHighlightSections(False)
        self.view.horizontalHeader().setSectionsClickable(False)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        self._configure_columns()
        self.view.clicked.connect(self._on_clicked)
        self.model.dataChanged.connect(self._update_count)
        self.model.modelReset.connect(self._update_count)
        lay.addWidget(self.view, 1)

    def _configure_columns(self) -> None:
        """Fixed widths for the tick, thumb and status columns.

        Only the two text columns stretch. The status column is sized to the
        glyph so a row changing state never reflows the whole list, which was
        the original reason for a fixed width in the Tk version.
        """
        h = self.view.horizontalHeader()
        h.setSectionResizeMode(COL_PICK, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(COL_ARTIST, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Fixed)
        # The tick column is sized to the artwork, not to a check mark. A 40px
        # column - the Tk list's width, which only ever held a glyph - clips
        # 16:9 artwork at a 56px row height, so it is widened to fit the
        # thumbnail with a little slack on each side.
        self.view.setColumnWidth(COL_PICK, THUMB_COLUMN)
        self.view.setColumnWidth(COL_ARTIST, 180)
        self.view.setColumnWidth(COL_STATUS, 96)
        # The header is only ever decorative here, so it is short rather than
        # a full 32px band of chrome.
        h.setFixedHeight(30)

    # ------------------------------------------------------------- behaviour
    def _on_clicked(self, index: QModelIndex) -> None:
        """Clicking the tick column toggles; anywhere else just selects."""
        if index.column() == COL_PICK:
            self.model.toggle(self._vid_at(index))
            self.checked_changed.emit()

    def _vid_at(self, index: QModelIndex) -> str:
        song = self.model.song_at(index.row())
        return song.vid if song is not None else ""

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self._delegate.set_dark(dark)
        self.view.viewport().update()

    def _on_search_changed(self, text: str) -> None:
        self.model.set_query(text)
        self._update_count()

    def set_all_checked(self, on: bool) -> None:
        self.model.set_all_checked(on)
        self.checked_changed.emit()
        self._update_count()

    def _update_count(self) -> None:
        total = len(self.model._songs)
        if not total:
            self.count_label.setText("")
            return
        picked = len(self.model.checked_ids())
        self.count_label.setText(f"{picked}/{total} selected")

    def _on_context_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        song = self.model.song_at(index.row())
        if song is None:
            return
        menu = QMenu(self)
        retry_act = menu.addAction("Retry this song")
        act = menu.exec(self.view.viewport().mapToGlobal(pos))
        if act == retry_act:
            self.status_activated.emit(song.vid, "retry")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space:
            selection = self.view.selectionModel().selectedRows()
            if selection:
                for idx in selection:
                    self.model.toggle(self._vid_at(idx))
                self.checked_changed.emit()
                self._update_count()
                event.accept()
                return
        super().keyPressEvent(event)

    def focus_search(self) -> None:
        """Ctrl+F: focus the search box with its text selected.

        Selecting the existing text is what makes a find shortcut useful -
        you almost always want to replace the query, not edit it.
        """
        self.filter_entry.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.filter_entry.selectAll()

    def clear_search(self) -> None:
        self.filter_entry.clear()
