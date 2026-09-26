"""Status glyphs, drawn as shapes rather than taken from a font.

The status column was originally a Unicode character taken from the UI font
(✓ ○ ◐ ✕ ⊘ → ·). Rendering it revealed that this does not work: on this
machine the chosen family - Ubuntu - supports *none* of those characters.
Qt does not complain, it silently falls back to whatever font does, and the
glyph arrives as a blob or a box. Checking coverage across the installed
families found only CJK fonts covering all of them, which would mean shipping
a Japanese font to draw a tick.

So the glyphs are drawn. A check mark is two lines; a cross is two lines; a
half-filled circle is a ring plus a filled half. Drawn, they are identical
on every platform, scale with the row height, take the row's colour exactly,
and never depend on a font being installed.

They are still not colour-coded alone: :mod:`musicdl.status` pairs each one
with a word, and the full phrase lives in the tooltip. The shape is the fast
signal, the word is the certain one.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF

__all__ = ["paint_glyph", "GLYPH_SHAPES"]

# Maps the token's glyph key onto the shape to draw. The token table keeps
# the character (the Tk list still renders text and the token tests still
# check it), while Qt draws the shape. Same key, two renderers, one meaning.
GLYPH_SHAPES = {
    "ok": "check",
    "missing": "circle",
    "busy": "half",
    "failed": "cross",
    "unavailable": "slash",
    "skipped": "arrow",
    "muted": "dot",
    "new": "dot",
}


def paint_glyph(painter: QPainter, shape: str, rect: QRectF, colour: QColor,
                width: float = 1.6) -> None:
    """Draw ``shape`` centred in ``rect`` in ``colour``.

    The painter is expected to have antialiasing enabled already. Nothing is
    translated or clipped, so the caller's transform is respected.
    """
    if rect.width() <= 0 or rect.height() <= 0:
        return
    cx = rect.center().x()
    cy = rect.center().y()
    # Sized off the cell rather than a fixed pixel count, so the glyph stays
    # proportionate if the row height or density setting changes.
    r = min(rect.width(), rect.height()) * 0.28
    pen = QPen(colour)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    no_brush = QBrush(Qt.BrushStyle.NoBrush)

    painter.setPen(pen)
    painter.setBrush(no_brush)

    if shape == "check":
        # A short down-right stroke, then a longer up-right one.
        painter.drawPolyline(QPolygonF([
            QPointF(cx - r, cy),
            QPointF(cx - r * 0.25, cy + r * 0.7),
            QPointF(cx + r, cy - r * 0.8),
        ]))
    elif shape == "cross":
        painter.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
        painter.drawLine(QPointF(cx + r, cy - r), QPointF(cx - r, cy + r))
    elif shape == "circle":
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    elif shape == "half":
        # A ring with one half filled: in flight. The fill is inset by the
        # pen width so the ring's own stroke stays visible all the way round -
        # without the inset the fill paints over the left edge and the ring
        # stops reading as a circle, which was the whole point of the shape.
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colour))
        # Inset by the pen width *and* a hair, so the ring's stroke stays
        # continuous. Painting the fill out to the ellipse's own edge buries
        # the left arc and the shape stops reading as a circle at all.
        inset = r - width * 1.5
        painter.drawRect(QRectF(cx - inset, cy - inset, inset, inset * 2))
        painter.setBrush(no_brush)
    elif shape == "slash":
        # A ring with a diagonal bar: permanently unavailable.
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        painter.drawLine(QPointF(cx - r * 0.7, cy + r * 0.7),
                         QPointF(cx + r * 0.7, cy - r * 0.7))
    elif shape == "arrow":
        # Deliberately passed over: a right-pointing arrow.
        painter.drawLine(QPointF(cx - r, cy), QPointF(cx + r * 0.8, cy))
        painter.drawLine(QPointF(cx + r * 0.8, cy),
                         QPointF(cx + r * 0.15, cy - r * 0.55))
        painter.drawLine(QPointF(cx + r * 0.8, cy),
                         QPointF(cx + r * 0.15, cy + r * 0.55))
    elif shape == "dot":
        # The neutral default. Filled rather than stroked, because a hairline
        # circle is the first thing to disappear at small sizes.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(colour))
        painter.drawEllipse(QRectF(cx - r * 0.45, cy - r * 0.45,
                                   r * 0.9, r * 0.9))
