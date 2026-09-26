"""Playlist artwork, fetched off the main thread.

The Tk version has the same class in :mod:`musicdl.ui.widgets`, and it is
reused rather than reimplemented: the fetch, the resize and the rounded
corners are all toolkit-independent, and only the final hand-off differs. The
Tk loader emits onto a message queue and Tk's pump drains it; this one does
the same thing, so the two are interchangeable from the downloader's point of
view.

What is *not* shared is the conversion to a Qt pixmap. Pillow images and Qt
pixmaps do not share a buffer, so :func:`to_pixmap` wraps the Pillow bytes in
a ``QImage`` rather than decoding them one pixel at a time.

A ``QPixmap`` may only be created on the main thread, and it is only ever
created here - on the main thread, in the message handler. The fetch itself
happens on a worker and hands back a Pillow image, which is safe to pass
between threads.
"""

from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap

from ..ui.widgets import THUMB_WORKERS
from ..ui.widgets import ThumbnailLoader as _BaseLoader

__all__ = ["ThumbnailLoader", "to_pixmap"]


def to_pixmap(image) -> QPixmap:
    """Convert a Pillow RGBA image into a ``QPixmap``.

    The obvious alternative - writing a temp file and calling ``QPixmap.load``
    - would mean writing a file per row, on a path the user may not have
    write access to, to move a few kilobytes that were already in memory. A
    per-pixel loop is the other wrong answer: it works, and it is two orders
    of magnitude slower than handing the bytes to ``QImage`` directly.
    """
    width, height = image.size
    raw = image.convert("RGBA").tobytes("raw", "RGBA")
    # bytes_per_line is width * 4 for tightly packed RGBA. Passing it
    # explicitly is what lets QImage read the buffer without a copy; leaving
    # it at 0 makes QImage guess, and the guess is right only by accident.
    qimage = QImage(raw, width, height, width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


class ThumbnailLoader(_BaseLoader):
    """Fetches artwork in the background and reports it through the queue.

    The base class already does all of this; the subclass exists so the Qt
    code has a name to import that is unambiguously the Qt one, and so the
    worker count is the Qt tuning rather than Tk's by accident.
    """

    def __init__(self, emit) -> None:
        super().__init__(emit)

    def start(self, count: int = THUMB_WORKERS) -> None:
        super().start(count)
