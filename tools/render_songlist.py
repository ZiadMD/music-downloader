"""Render the song list to a PNG, for review without opening a window.

The list is the screen's centre of gravity, and it is also the part of the
Qt UI that a stylesheet cannot produce - the banding, the per-status glyph
tint and the artwork are all drawn by a delegate. That means the only honest
way to review it is to look at it.

Rather than opening a window, this renders the view into an offscreen buffer
and writes a PNG, so the result can be looked at, diffed in review, and
attached to a commit - none of which is true of a window that has to be open
at the right moment.

    uv run python tools/render_songlist.py                  # dark, PNG
    uv run python tools/render_songlist.py --mode light
    uv run python tools/render_songlist.py --out /tmp/list.png
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from musicdl.qt import songlist, theme  # noqa: E402
from musicdl.qt.songmodel import Song  # noqa: E402

# Sample data covering every status role, so all four glyphs and tints are
# visible at once. Placeholder artwork is a flat swatch - this is a layout and
# colour check, not a thumbnail fetcher.
SAMPLE = [
    ("v0", "Songs that make you feel like the villain", "Artist One", "Downloaded"),
    ("v1", "Midnight Drive", "Artist Two", "Downloading 42% · 1.4 MiB/s"),
    ("v2", "A Very Long Title That Has To Be Elided Because It Does Not Fit", "Artist Three", "Missing"),
    ("v3", "Short", "A", "Skipped"),
    ("v4", "Untitled draft", "Artist Four", "Unavailable"),
    ("v5", "Waiting on the queue", "Artist Two", "Waiting..."),
    ("v6", "Another one", "Artist One", "Downloaded"),
    ("v7", "And another", "Artist Three", "Not downloaded"),
    # "Failed" and "Unavailable" and "Missing" all resolve to the same
    # colour role but must not share a glyph. Including all three is the only
    # way a one-screen render can show that they actually differ.
    ("v8", "A take that fell over", "Artist Four", "Failed"),
]

# A deterministic set of placeholder colours, so re-renders are comparable.
_THUMB_COLOURS = ["#526678", "#6f8396", "#8a6a52", "#5b7a5b", "#7a5b7a"]


def build(dark: bool) -> songlist.SongList:
    widget = songlist.SongList(dark=dark)
    widget.resize(980, 560)
    widget.show()
    widget.model.set_songs(
        [Song(vid, title, artist) for vid, title, artist, _ in SAMPLE])
    for i, (vid, _t, _a, status) in enumerate(SAMPLE):
        pix = QPixmap(80, 45)
        pix.fill(QColor(_THUMB_COLOURS[i % len(_THUMB_COLOURS)]))
        widget.model.set_thumbnail(vid, pix)
        widget.model.set_status(vid, status)
    # Leave one row selected so the selection surface is visible too.
    widget.view.selectRow(2)
    return widget


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["light", "dark"], default="dark")
    ap.add_argument("--out", default=None, help="output PNG path")
    ap.add_argument("--search", default="", help="apply a search term")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication([])
    dark = args.mode == "dark"
    theme.apply_theme(app, dark)
    widget = build(dark)
    if args.search:
        widget.filter_entry.setText(args.search)
    app.processEvents()

    out = args.out or f"songlist-{args.mode}.png"
    image = widget.grab()
    if image.save(out):
        print(f"wrote {out}  ({image.width()}x{image.height()})")
        return 0
    print("failed to write", out, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
