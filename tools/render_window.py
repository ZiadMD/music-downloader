"""Render the Qt window to a PNG so it can be reviewed without a display.

A window that builds cleanly can still be laid out wrong: a section that
collapses, a control clipped at the right edge, a label that says "Load
Playlist" over a video link. None of that shows up in an assertion, so the
window is rendered offscreen and looked at.

Run it for both themes - a layout that reads on one can break on the other,
because the type scale and the padding are the same but the contrast is not.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Run from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # noqa: E402

from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from musicdl import config  # noqa: E402
from musicdl.qt import app as app_mod, theme  # noqa: E402
from musicdl.qt.songmodel import Song  # noqa: E402

# One row per status, so a single screenshot covers every glyph and tint.
# Placeholder artwork is a flat swatch: this is a layout check, not a
# thumbnail fetcher.
SAMPLE = [
    ("v0", "Songs that make you feel like the villain", "Artist One", "Downloaded"),
    ("v1", "Midnight Drive", "Artist Two", "Downloading 42% · 1.4 MiB/s"),
    ("v2", "A Very Long Title That Has To Be Elided Because It Does Not Fit",
     "Artist Three", "Missing"),
    ("v3", "Short", "A", "Skipped"),
    ("v4", "Untitled draft", "Artist Four", "Unavailable"),
    ("v5", "Waiting on the queue", "Artist Two", "Waiting..."),
    ("v6", "Another one", "Artist One", "Failed"),
    ("v7", "And another", "Artist Three", "Not downloaded"),
]

_THUMB_COLOURS = ["#526678", "#6f8396", "#8a6a52", "#5b7a5b", "#7a5b7a"]


def _swatch(colour: str) -> QPixmap:
    """A flat placeholder thumbnail.

    Filled with a painter rather than ``QPixmap.fill``, because ``fill``
    goes through the style and the Fusion style answers a plain colour with a
    theme icon - the render came back with a pixmap glyph on every row.
    """
    pix = QPixmap(80, 45)
    painter = QPainter(pix)
    painter.fillRect(pix.rect(), QColor(colour))
    painter.end()
    return pix


def build(dark: bool) -> app_mod.MainWindow:
    win = app_mod.MainWindow(dark=dark)
    win.resize(1180, 820)
    win.show()
    model = win.songs.model
    model.set_songs([Song(v, t, a) for v, t, a, _ in SAMPLE])
    for i, (vid, _t, _a, status) in enumerate(SAMPLE):
        model.set_thumbnail(vid, _swatch(
            _THUMB_COLOURS[i % len(_THUMB_COLOURS)]))
        model.set_status(vid, status)
    win.songs.view.selectRow(2)
    win.songs.model.set_all_checked(True)
    win.songs.model.toggle("v3")
    win.subtitle_label.setText("8 songs loaded")
    win.status_label.setText("Downloading: Song 2 of 8")
    win.detail_label.setText("42% · 1.4 MiB/s · 3.2 MiB of 7.6 MiB")
    win.progress.setValue(31)
    for line in (
        ">>> Load: 8 songs, 7 selected.",
        "Downloading 2/8: Midnight Drive",
        "  1.4 MiB/s · eta 00:04",
    ):
        win.append_log(line)
    return win


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("light", "dark", "system"),
                    default="dark",
                    help="Overrides the stored theme setting, so the same "
                         "code path renders both themes.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--media", choices=("Music", "Video"), default="Music")
    args = ap.parse_args()

    qapp = QApplication.instance() or QApplication([])
    # The window reads its theme from the stored settings, not from an
    # argument, because that is what the real app does. To render the other
    # theme the setting is overridden *before* the window is built, rather
    # than passing a flag the window ignores - which is how the first render
    # came out light-on-light and dark-on-dark.
    if args.mode != "system":
        cfg = config.load()
        cfg["theme"] = args.mode
        config.save(cfg)
    dark = theme.is_dark(args.mode)
    theme.apply_theme(qapp, dark)

    win = build(dark)
    if args.media == "Video":
        win.rad_video.setChecked(True)
    else:
        win.rad_music.setChecked(True)
    qapp.processEvents()
    win.grab().save(args.out)
    print(f"wrote {args.out}  ({win.width()}x{win.height()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
