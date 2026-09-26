"""A style guide for the Qt theme, as a runnable window.

The theme layer can only be judged by looking at it. A stylesheet that
parses cleanly, applies every token role and passes contrast tests can
still look wrong - too much rounding, a hover step that is invisible, a
focus ring that fights the accent. None of that shows up in a test.

So this renders every widget the theme touches, in both modes, with the
token values printed alongside. It is a development tool, not part of the
app, which is why it lives in ``tools/`` and is not imported by anything.

    uv run python tools/preview_qt_theme.py

Pass ``--mode light`` or ``--mode dark`` to pin one mode, or ``--side`` to
put both side by side. The default follows the OS.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

from musicdl.qt import fonts, theme  # noqa: E402
from musicdl.ui import tokens  # noqa: E402

# Rows shown in the status sample. These are the real status roles, so the
# sample is the same thing the app will render rather than a mock-up.
STATUS_SAMPLES = [
    ("ok", "Downloaded"),
    ("busy", "Downloading 42% · 1.4 MiB/s"),
    ("missing", "Failed"),
    ("muted", "Not downloaded"),
]


def swatch(role: str, dark: bool) -> QFrame:
    """A colour chip labelled with its token role.

    Labels matter more than the colour here: a designer needs to see the
    *name* to know whether the value is right, not just that it differs
    from its neighbour.
    """
    p = tokens.palette(dark)
    box = QFrame()
    box.setFixedSize(120, 44)
    box.setStyleSheet(
        f"background-color: {p[role]};"
        f"border: 1px solid {p['outline']};"
        f"border-radius: {tokens.RADIUS_SM}px;")
    return box


def _labelled(role: str, dark: bool) -> QWidget:
    col = QVBoxLayout()
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(2)
    col.addWidget(swatch(role, dark))
    name = QLabel(role)
    name.setObjectName("caption")
    col.addWidget(name)
    value = QLabel(tokens.palette(dark)[role])
    value.setObjectName("muted")
    col.addWidget(value)
    w = QWidget()
    w.setLayout(col)
    return w


def controls_section(dark: bool) -> QWidget:
    """Every interactive widget the stylesheet targets."""
    group = QGroupBox("Controls")
    grid = QGridLayout(group)
    grid.setSpacing(tokens.SPACE_MD)
    grid.setContentsMargins(tokens.PAD_SECTION, tokens.PAD_SECTION,
                            tokens.PAD_SECTION, tokens.PAD_SECTION)

    p = tokens.palette(dark)

    line = QLineEdit()
    line.setPlaceholderText("Paste a playlist or video link")
    grid.addWidget(QLabel("Line edit"), 0, 0)
    grid.addWidget(line, 0, 1)

    disabled = QLineEdit("Unavailable while busy")
    disabled.setEnabled(False)
    grid.addWidget(QLabel("Disabled"), 1, 0)
    grid.addWidget(disabled, 1, 1)

    combo = QComboBox()
    combo.addItems(["Music", "Video"])
    grid.addWidget(QLabel("Combo"), 2, 0)
    grid.addWidget(combo, 2, 1)

    # Buttons: the filled primary is the only one on screen in the real app,
    # so showing all four together is deliberately misleading. They are shown
    # here to inspect the states the stylesheet defines.
    row = QHBoxLayout()
    primary = QPushButton("Download Selected")
    primary.setObjectName("primary")
    ghost = QPushButton("Ghost")
    ghost.setObjectName("ghost")
    plain = QPushButton("Secondary")
    off = QPushButton("Disabled")
    off.setEnabled(False)
    for b in (primary, plain, ghost, off):
        row.addWidget(b)
    holder = QWidget()
    holder.setLayout(row)
    grid.addWidget(QLabel("Buttons"), 3, 0)
    grid.addWidget(holder, 3, 1)

    checks = QWidget()
    crow = QHBoxLayout()
    crow.setContentsMargins(0, 0, 0, 0)
    for label, on in (("Embed artwork", True), ("Multi-download", True),
                      ("Unchecked", False), ("Disabled", False)):
        cb = QCheckBox(label)
        cb.setChecked(on)
        if label == "Disabled":
            cb.setEnabled(False)
        crow.addWidget(cb)
    checks.setLayout(crow)
    grid.addWidget(QLabel("Checkboxes"), 4, 0)
    grid.addWidget(checks, 4, 1)

    radios = QWidget()
    rrow = QHBoxLayout()
    rrow.setContentsMargins(0, 0, 0, 0)
    for i, label in enumerate(("Music", "Video")):
        rb = QRadioButton(label)
        if i == 0:
            rb.setChecked(True)
        rrow.addWidget(rb)
    radios.setLayout(rrow)
    grid.addWidget(QLabel("Radios"), 5, 0)
    grid.addWidget(radios, 5, 1)

    bar = QProgressBar()
    bar.setValue(42)
    bar.setFormat("42% · 1.4 MiB/s")
    grid.addWidget(QLabel("Progress"), 6, 0)
    grid.addWidget(bar, 6, 1)

    log = QPlainTextEdit()
    log.setObjectName("log")
    log.setReadOnly(True)
    log.setFixedHeight(96)
    log.setPlainText(
        f"[12:04:31] Fetched 48 entries from playlist\n"
        f"[12:04:32] Saved: {p['on_surface_secondary'] and 'Track 01.mp3'}\n")
    grid.addWidget(QLabel("Log pane"), 7, 0)
    grid.addWidget(log, 7, 1)
    return group


def type_section() -> QWidget:
    """The type scale, so the sizes can be compared side by side."""
    group = QGroupBox("Type scale")
    col = QVBoxLayout(group)
    col.setContentsMargins(tokens.PAD_SECTION, tokens.PAD_SECTION,
                           tokens.PAD_SECTION, tokens.PAD_SECTION)
    for role, object_name in (("title", "title"), ("section", "section"),
                              ("body", None), ("secondary", "secondary"),
                              ("caption", "muted"),
                              ("caption_bold", "captionBold"),
                              ("numeric", "numeric")):
        text = {"numeric": "42% · 1.4 MiB/s · 00:17 remaining",
                "title": "Music Downloader",
                "section": "Section header",
                "body": "Body text at the primary size",
                "secondary": "Secondary, for supporting copy",
                "caption": "Caption, for column headers",
                "caption_bold": "Caption bold, for field labels"}[role]
        lbl = QLabel(f"{text}   ({role} · {fonts.families.TYPE_SCALE[role]}px)")
        if object_name:
            lbl.setObjectName(object_name)
        col.addWidget(lbl)
    return group


def status_section(dark: bool) -> QWidget:
    """Status rows, coloured from the token roles as the app renders them."""
    p = tokens.palette(dark)
    group = QGroupBox("Status glyph + word")
    col = QVBoxLayout(group)
    col.setContentsMargins(tokens.PAD_SECTION, tokens.PAD_SECTION,
                           tokens.PAD_SECTION, tokens.PAD_SECTION)
    col.setSpacing(tokens.SPACE_XS)
    for role, word in STATUS_SAMPLES:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        glyph = QLabel(f"{tokens.STATUS_ICONS.get(role, '·')}")
        glyph.setFixedWidth(24)
        text = QLabel(word)
        # The same mapping the Tk table uses, so the two UIs agree.
        fg = {"ok": p["success"], "busy": p["info"],
              "missing": p["danger"], "muted": p["on_surface_muted"]}[role]
        text.setStyleSheet(f"color: {fg}; font-size: {tokens.FONT_SIZE_CAPTION}px;")
        row.addWidget(glyph)
        row.addWidget(text)
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        col.addWidget(w)
    return group


def palette_section(dark: bool) -> QWidget:
    """Every surface and line role, so the ramp can be checked for flatness."""
    group = QGroupBox("Palette roles")
    grid = QGridLayout(group)
    grid.setSpacing(tokens.SPACE_MD)
    grid.setContentsMargins(tokens.PAD_SECTION, tokens.PAD_SECTION,
                            tokens.PAD_SECTION, tokens.PAD_SECTION)
    roles = ["surface", "surface_container", "surface_sunken",
             "surface_subtle", "surface_hover", "surface_selected",
             "outline", "outline_variant", "accent", "success", "warning",
             "danger", "info"]
    for i, role in enumerate(roles):
        grid.addWidget(_labelled(role, dark), i // 5, i % 5)
    return group


def page(dark: bool) -> QWidget:
    """One complete theme page."""
    w = QWidget()
    col = QVBoxLayout(w)
    col.setSpacing(tokens.SPACE_LG)
    col.setContentsMargins(tokens.PAD_WINDOW, tokens.PAD_WINDOW,
                           tokens.PAD_WINDOW, tokens.PAD_WINDOW)

    title = QLabel("Music Downloader")
    title.setObjectName("title")
    col.addWidget(title)
    sub = QLabel(f"Theme preview · {'dark' if dark else 'light'} mode")
    sub.setObjectName("secondary")
    col.addWidget(sub)

    col.addWidget(controls_section(dark))
    col.addWidget(type_section())
    col.addWidget(status_section(dark))
    col.addWidget(palette_section(dark))
    col.addStretch(1)
    return w


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["system", "light", "dark"],
                    default="system", help="which mode to show")
    ap.add_argument("--side", action="store_true",
                    help="show light and dark side by side")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    fonts.reset_cache()

    if args.side:
        # The stylesheet is an application-wide property: one QApplication
        # holds exactly one, so two windows in one process cannot show
        # different modes - the second apply_theme would restyle the first.
        # (Verified rather than assumed.) So the dark window is a second
        # process, which is also how the app itself would ever run.
        for mode in ("light", "dark"):
            subprocess.Popen(
                [sys.executable, __file__, "--mode", mode],
                env=dict(os.environ))
        return 0

    dark = theme.is_dark(args.mode)
    theme.apply_theme(app, dark)
    w = page(dark)
    w.setWindowTitle(f"Music Downloader · preview ({args.mode})")
    w.resize(820, 980)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
