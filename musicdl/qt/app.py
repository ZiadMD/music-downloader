"""The main application window.

Owns widget state and rendering only. Download logic lives in
:mod:`musicdl.ui.downloader`, which is toolkit-independent and talks back
purely through the message queue the window drains.

Layout
------
A single vertical stack of sections, in the order they are used: title, link,
format, save location, the song list, the actions, then progress and the log.
Only the song list absorbs extra window height. Each section is one widget
group so hiding one - the audio settings when Video is chosen - cannot move
the others, which is what a ``grid_remove``-style toggle does badly once a
row has several independent groups on it.

Two behaviours here exist because of bugs found in the Tk version, and both
have tests: the load button's label follows what is actually in the link box
(:meth:`MainWindow.on_url_changed`), and each media type shows only the
settings that apply to it (:meth:`MainWindow.on_media_changed`).
"""

from __future__ import annotations

import os
import queue
import time

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QAction, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .. import config, core, paths, status as status_mod
from ..cleanup import cleanup_partials
from ..cookies import validate_cookie_file
from ..formatting import fmt_bytes, fmt_eta, fmt_speed, plural
from ..naming import is_saved_match
from ..ui import downloader as dl
from ..ui import tokens
from ..ui.fonts import progress_text, tick_text
from . import theme
from .dialogs import RenamePrompter
from .songlist import SongList
from .thumbs import ThumbnailLoader, to_pixmap
from .songmodel import Song

APP_TITLE = "Music Downloader"
WINDOW_SIZE = QSize(1180, 820)
WINDOW_MINSIZE = QSize(960, 700)

# The load button accepts a playlist link or a single video link, so its label
# follows what is actually in the box rather than claiming "playlist" either
# way. Both labels are sized to the longer of the two, so relabelling never
# resizes the button out from under a click.
LOAD_LABEL = "Load Playlist"
SINGLE_LABEL = "Load Video"
LOAD_TOOLTIP = "Load every song in this playlist."
SINGLE_TOOLTIP = ("This link points at one video, so only that video will be "
                  "loaded - not the playlist it came from.")

# Media types, in the order the radio buttons appear.
MEDIA_MUSIC = "Music"
MEDIA_VIDEO = "Video"

# How often the main thread drains worker messages. Fast enough that progress
# looks live, slow enough that the queue is not polled in a busy loop.
POLL_MS = 120

# Minimum gap between overall-progress detail text updates. yt-dlp reports far
# more often than a person can read, and re-laying out the text on every
# message is the work, not the reading.
DETAIL_THROTTLE_SECONDS = 0.25

# Section labels as small bold captions, used for the inline field labels that
# sit next to a control rather than above it.
_CAPTION = "captionBold"
_MUTED = "muted"

_THEME_LABELS = {
    theme.THEME_SYSTEM: "Match system",
    theme.THEME_LIGHT: "Light",
    theme.THEME_DARK: "Dark",
}


def _label(text: str, role: str = _CAPTION, parent=None) -> QLabel:
    """A label whose typography comes from a stylesheet object name.

    The Qt stylesheet is the only place a font size is expressed, so naming
    the role here rather than setting a font keeps the type scale with one
    definition and makes the label re-theme for free.
    """
    lab = QLabel(text, parent)
    lab.setObjectName(role)
    return lab


def _spacer() -> QWidget:
    """An expanding gap, so a row can push one control to the right."""
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Preferred)
    return w


def _fit_button(btn: QPushButton, *texts: str) -> None:
    """Pin a button wide enough for the widest of ``texts``.

    Measuring with ``fontMetrics().horizontalAdvance`` and adding a guess at
    the padding is the obvious approach and it is wrong: the stylesheet
    decides both the padding and the border width, and the two are declared in
    a different file from this one. A button came out 14px narrower than its
    own text needed and clipped "Browse" to "rows".

    So the width comes from Qt's own ``sizeHint``, with the button holding the
    longest label while it is measured - that is the label a relabel can
    change it to, and it is the one the width has to survive.
    """
    original = btn.text()
    btn.setFixedWidth(0)
    widest = 0
    for text in texts or (original,):
        btn.setText(text)
        btn.ensurePolished()
        widest = max(widest, btn.sizeHint().width())
    btn.setFixedWidth(widest)
    btn.setText(original)


class ElidedLabel(QLabel):
    """A single-line label that shortens its text rather than overflowing.

    ``QLabel`` does not elide. Left to itself it either expands the layout -
    which pushes the controls either side of it off the window - or gets
    clipped mid-word, and the two failure modes are both worse than showing
    less. Status text is exactly the thing that grows: a failure summary can
    run to a full sentence.

    The full text stays in the tooltip, so nothing is lost - it just takes a
    deliberate hover to see, rather than being squashed into the layout.

    ``minimum_width`` picks between two genuinely different layouts, and
    getting it wrong is not subtle:

    * ``0`` - *flexible*. The label takes whatever slack the row has and
      elides into it. Its size hint is ignored, so the row's width never
      depends on how long the text is. This is what a status line wants.
    * non-zero - *fixed share*. The label reserves that width and elides
      into it, leaving the rest of the row to its neighbours.

    The fixed-share case cannot use ``QSizePolicy.Ignored`` even though it
    wants to elide: that policy tells the layout the widget's minimum is zero,
    so an expanding neighbour takes the entire row and pushes the label
    completely off the right edge. The progress detail text vanished that way
    while every widget still reported itself visible.
    """

    def __init__(self, text: str = "", role: str = _MUTED,
                 minimum_width: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._full = text
        self._min_width = int(minimum_width)
        self.setObjectName(role)
        policy = (QSizePolicy.Policy.Ignored if self._min_width <= 0
                  else QSizePolicy.Policy.Preferred)
        self.setSizePolicy(policy, QSizePolicy.Policy.Preferred)
        if self._min_width > 0:
            self.setMinimumWidth(self._min_width)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt's name
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply()

    def full_text(self) -> str:
        """The unelided text, for tests and tooltips."""
        return self._full

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        """Reserve only the fixed share, never the full message.

        Returning the text's own width would make a long status stretch the
        row, which is the problem this class exists to solve.
        """
        hint = super().sizeHint()
        if self._min_width > 0:
            hint.setWidth(self._min_width)
        return hint

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt's name
        hint = super().minimumSizeHint()
        if self._min_width > 0:
            hint.setWidth(max(hint.width(), self._min_width))
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(
            metrics.elidedText(self._full, Qt.TextElideMode.ElideRight,
                               max(0, self.width())))


class MainWindow(QMainWindow):
    """Settings, the song list, progress and the log."""

    def __init__(self, dark: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_TITLE)
        self.resize(WINDOW_SIZE)
        self.setMinimumSize(WINDOW_MINSIZE)

        self.cfg = config.load()
        self._dark = dark
        self.entries: list = []
        self._closed = False

        # Job state. The three maps are shared *by reference* with the running
        # job, so a failure classified on a worker thread is the same object
        # the Retry button reads - the Tk version does the same, and copying
        # them would mean the list and the job could disagree about what
        # failed.
        self.failed: dict = {}
        self.unavailable: dict = {}
        self._job = None
        self._stop_requested = False
        self._expected_n = 0
        self._song_i = 0
        self._last_detail = 0.0

        self._queue: queue.Queue = queue.Queue()
        self._prompter = RenamePrompter(self._enqueue)
        self._thumbs = ThumbnailLoader(self._enqueue)

        self._build_ui()
        self.on_media_changed()
        self.on_url_changed()
        self._refresh_cookie_status()
        self._bind_shortcuts()

        # The pump runs on the main thread and is what makes the worker's
        # messages safe to handle. It is started last, so the first tick cannot
        # arrive before the window is finished being built.
        self._pump_timer = QTimer(self)
        self._pump_timer.setInterval(POLL_MS)
        self._pump_timer.timeout.connect(self._on_pump)
        self._pump_timer.start()

    # ------------------------------------------------------------------ build
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(
            tokens.PAD_WINDOW, tokens.PAD_WINDOW - 4,
            tokens.PAD_WINDOW, tokens.PAD_WINDOW)
        outer.setSpacing(tokens.SPACE_SM)

        self.songs = SongList(dark=self._dark)
        # The list is the only section allowed to grow, so it gets the stretch
        # factor and everything else stays at its natural height.
        outer.addWidget(self._build_header(), 0)
        outer.addWidget(self._build_url_row(), 0)
        outer.addWidget(self._build_format_row(), 0)
        outer.addWidget(self._build_output_row(), 0)
        outer.addWidget(self.songs, 1)
        outer.addWidget(self._build_actions_row(), 0)
        outer.addWidget(self._build_progress_row(), 0)
        outer.addWidget(self._build_status_row(), 0)
        outer.addWidget(self._build_log(), 0)

    def _build_header(self) -> QWidget:
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, tokens.SPACE_SM)
        row.setSpacing(tokens.SPACE_LG)

        titles = QWidget()
        tlay = QVBoxLayout(titles)
        tlay.setContentsMargins(0, 0, 0, 0)
        tlay.setSpacing(0)
        self.title_label = _label(APP_TITLE, "title", titles)
        self.subtitle_label = _label(
            "Load a playlist or a single video to begin.", "secondary", titles)
        tlay.addWidget(self.title_label)
        tlay.addWidget(self.subtitle_label)
        row.addWidget(titles, 1)

        # A menu rather than a toggle, because two states cannot express
        # "follow the system" - and once an explicit choice is made there is
        # no way back to following the OS.
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("ghost")
        self.theme_btn.setMenu(self._build_theme_menu())
        self.theme_btn.setToolTip("Theme")
        # The three labels differ in length, and the button must not resize
        # when one is chosen - a menu that reshuffles the header as you read it
        # is the kind of thing you notice and cannot un-notice.
        _fit_button(self.theme_btn, *_THEME_LABELS.values())
        row.addWidget(self.theme_btn, 0, Qt.AlignmentFlag.AlignTop)
        self._update_theme_btn()
        return header

    def _build_theme_menu(self) -> QMenu:
        menu = QMenu(self)
        for choice, text in _THEME_LABELS.items():
            act = QAction(text, self)
            act.setCheckable(True)
            act.setData(choice)
            act.triggered.connect(
                lambda _checked, c=choice: self.set_theme(c))
            menu.addAction(act)
        return menu

    def _build_url_row(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_SM)

        row.addWidget(_label("Link"))
        self.url_edit = QLineEdit(self.cfg.get("last_url", ""))
        self.url_edit.setPlaceholderText(
            "Paste a YouTube playlist or video link")
        self.url_edit.returnPressed.connect(self.on_load_pressed)
        row.addWidget(self.url_edit, 1)

        self.load_btn = QPushButton(LOAD_LABEL)
        self.load_btn.setObjectName("primary")
        self.load_btn.clicked.connect(self.on_load_pressed)
        # Sized to the longer of the two labels, so swapping the label under
        # the pointer does not move the button the pointer is already on.
        _fit_button(self.load_btn, LOAD_LABEL, SINGLE_LABEL)
        row.addWidget(self.load_btn, 0)

        self.url_edit.textChanged.connect(self.on_url_changed)
        return box

    def _build_format_row(self) -> QWidget:
        box = QGroupBox("Format")
        row = QHBoxLayout(box)
        row.setContentsMargins(
            tokens.SPACE_LG, tokens.SPACE_MD, tokens.SPACE_LG, tokens.SPACE_LG)
        row.setSpacing(tokens.SPACE_MD)

        # Each media type's settings live in their own container so
        # on_media_changed hides or shows the group wholesale. Sharing one row
        # would mean hiding a neighbour's controls along with it.
        self.type_group = self._group_widget()
        trow = QHBoxLayout(self.type_group)
        trow.setContentsMargins(0, 0, 0, 0)
        trow.setSpacing(tokens.SPACE_SM)
        trow.addWidget(_label("Type"))
        self.media_group = QButtonGroup(self)
        self.rad_music = QRadioButton(MEDIA_MUSIC)
        self.rad_video = QRadioButton(MEDIA_VIDEO)
        stored = self.cfg.get("media", MEDIA_MUSIC)
        self.rad_music.setChecked(stored != MEDIA_VIDEO)
        self.rad_video.setChecked(stored == MEDIA_VIDEO)
        self.media_group.addButton(self.rad_music)
        self.media_group.addButton(self.rad_video)
        self.rad_music.toggled.connect(self.on_media_changed)
        trow.addWidget(self.rad_music)
        trow.addWidget(self.rad_video)
        trow.addSpacing(tokens.SPACE_LG)
        row.addWidget(self.type_group, 0)

        self.audio_group = self._group_widget()
        arow = QHBoxLayout(self.audio_group)
        arow.setContentsMargins(0, 0, 0, 0)
        arow.setSpacing(tokens.SPACE_SM)
        arow.addWidget(_label("Audio"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(list(core.AUDIO_FORMATS))
        self.format_combo.setCurrentText(self.cfg.get("format", "MP3"))
        arow.addWidget(self.format_combo)
        arow.addSpacing(tokens.SPACE_LG)
        arow.addWidget(_label("Quality"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(list(core.QUALITIES))
        self.quality_combo.setCurrentText(self.cfg.get("quality", "192"))
        arow.addWidget(self.quality_combo)
        row.addWidget(self.audio_group, 0)

        self.video_group = self._group_widget()
        vrow = QHBoxLayout(self.video_group)
        vrow.setContentsMargins(0, 0, 0, 0)
        vrow.setSpacing(tokens.SPACE_SM)
        vrow.addWidget(_label("Resolution"))
        self.res_combo = QComboBox()
        self.res_combo.addItems(list(core.VIDEO_RESOLUTIONS))
        self.res_combo.setCurrentText(self.cfg.get("resolution", "Best"))
        vrow.addWidget(self.res_combo)
        row.addWidget(self.video_group, 0)

        row.addWidget(_spacer(), 1)
        return box

    @staticmethod
    def _group_widget() -> QWidget:
        """A zero-margin container, so a hidden group leaves no gap."""
        w = QWidget()
        w.setContentsMargins(0, 0, 0, 0)
        return w

    def _build_output_row(self) -> QWidget:
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(tokens.SPACE_MD)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_SM)
        row.addWidget(_label("Save to"))
        self.dir_edit = QLineEdit(self.cfg.get("output_dir", ""))
        self.dir_edit.setPlaceholderText("Choose a folder")
        row.addWidget(self.dir_edit, 1)
        browse = QPushButton("Browse")
        browse.clicked.connect(self.browse_dir)
        _fit_button(browse, "Browse")
        self.browse_btn = browse
        row.addWidget(browse, 0)
        outer.addLayout(row)

        opts = QHBoxLayout()
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setSpacing(tokens.SPACE_SM)

        # Artwork embedding is audio-only, so the toggle sits in its own
        # container that on_media_changed hides. In a shared row it would drag
        # the neighbouring toggles out of alignment when hidden.
        self.thumb_holder = self._group_widget()
        trow = QHBoxLayout(self.thumb_holder)
        trow.setContentsMargins(0, 0, 0, 0)
        trow.setSpacing(0)
        self.thumb_check = QCheckBox("Embed artwork")
        self.thumb_check.setChecked(bool(self.cfg.get("thumbnail", True)))
        trow.addWidget(self.thumb_check)
        opts.addWidget(self.thumb_holder, 0)

        self.parallel_check = QCheckBox("Multi-download")
        self.parallel_check.setChecked(bool(self.cfg.get("parallel", False)))
        self.parallel_check.toggled.connect(self.on_parallel_toggle)
        opts.addWidget(self.parallel_check, 0)

        self.jobs_combo = QComboBox()
        self.jobs_combo.addItems([str(n) for n in range(1, 7)])
        self.jobs_combo.setCurrentText(str(self._restore_jobs()))
        # Wider than the digits need: a combo box narrower than its own arrow
        # reads as an empty field, and the digit is the only thing in it.
        self.jobs_combo.setMinimumWidth(72)
        opts.addWidget(self.jobs_combo, 0)
        opts.addWidget(_label("at once", _MUTED), 0)
        opts.addSpacing(tokens.SPACE_SM)

        self.cookie_label = _label("", _MUTED)
        opts.addWidget(self.cookie_label, 0)
        opts.addStretch(1)

        self.fix_btn = QPushButton("Fix blocked")
        self.fix_btn.clicked.connect(self.choose_cookie_file)
        opts.addWidget(self.fix_btn, 0)
        outer.addLayout(opts)

        self.on_parallel_toggle()
        return box

    def _build_actions_row(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_SM)

        # Exactly one filled button on screen, so "Download Selected" is the
        # thing the eye lands on without a second accent competing with it.
        self.download_btn = QPushButton("Download Selected")
        self.download_btn.setObjectName("primary")
        self.download_btn.clicked.connect(self.on_download_pressed)
        row.addWidget(self.download_btn, 0)

        self.check_btn = QPushButton("Check Saved")
        self.check_btn.clicked.connect(self.on_check_pressed)
        row.addWidget(self.check_btn, 0)

        self.retry_btn = QPushButton("Retry Failed")
        self.retry_btn.clicked.connect(self.on_retry_pressed)
        # Nothing has failed yet, so there is nothing to retry.
        self.retry_btn.setEnabled(False)
        row.addWidget(self.retry_btn, 0)

        row.addWidget(_spacer(), 1)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.on_stop_pressed)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn, 0)
        return box

    def _build_progress_row(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_LG)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        # The bar stretches, but it is not allowed to stretch to nothing: it
        # gave all 1120px to itself and squeezed the detail text down to its
        # bare minimum, so the live speed and ETA - the numbers a waiting user
        # actually looks for - were elided to nothing on a wide window.
        self.progress.setMinimumWidth(160)
        row.addWidget(self.progress, 1)
        # A fixed share of the row, so the live speed and ETA have room to be
        # read rather than being elided to nothing on a wide window.
        self.detail_label = ElidedLabel("", _MUTED, minimum_width=240)
        row.addWidget(self.detail_label, 0)
        return box

    def _build_status_row(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_SM)
        # The one label whose text length is not under our control, so it is
        # the one that elides. Everything else has a fixed, short string.
        self.status_label = ElidedLabel("Ready.", "secondary")
        row.addWidget(self.status_label, 1)
        return box

    def _build_log(self) -> QWidget:
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        # Sized to hold several lines without becoming the window's focus, and
        # to scroll internally rather than pushing the list off screen.
        self.log.setFixedHeight(120)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        return self.log

    # -------------------------------------------------------------- behaviour
    def on_url_changed(self, *_args) -> None:
        """Point the load button at what the link actually is.

        The pasted link is usually a playlist, but a shared ``watch?v=`` link
        is a single video, and yt-dlp would otherwise pull the whole playlist
        context. The app already handles that case; this only makes the
        difference visible before the user commits to it.
        """
        url = (self.url_edit.text() or "").strip()
        if url and core.looks_like_single_video(url):
            self.load_btn.setText(SINGLE_LABEL)
            self.load_btn.setToolTip(SINGLE_TOOLTIP)
        else:
            self.load_btn.setText(LOAD_LABEL)
            self.load_btn.setToolTip(LOAD_TOOLTIP)

    def on_media_changed(self, *_args) -> None:
        """Show only the settings that apply to the chosen media type.

        Audio and video have disjoint settings. Leaving the other set on
        screen but disabled was worse than either extreme: it took the room it
        was going to take anyway and asked for a decision the user could not
        make. Hiding is reversible and keeps the panel honest about what will
        actually be used.
        """
        is_video = self.rad_video.isChecked()
        self.audio_group.setVisible(not is_video)
        self.video_group.setVisible(is_video)
        # Cover art is an audio-only feature, so the toggle follows the type.
        self.thumb_holder.setVisible(not is_video)

    def on_parallel_toggle(self, *_args) -> None:
        """Keep the job count consistent with multi-download being on.

        One job with multi-download enabled is a contradiction the user did
        not mean, and six jobs with it off is a control that does nothing.
        """
        on = self.parallel_check.isChecked()
        if on and self.current_jobs() < 2:
            self.jobs_combo.setCurrentText(str(self._restore_jobs()))
        elif not on and self.current_jobs() >= 2:
            self.jobs_combo.setCurrentText("1")
        self.jobs_combo.setEnabled(on)

    def media(self) -> str:
        return MEDIA_VIDEO if self.rad_video.isChecked() else MEDIA_MUSIC

    def current_jobs(self) -> int:
        """The job count, clamped to what the control allows."""
        try:
            return max(1, min(int(self.jobs_combo.currentText() or 1), 6))
        except (TypeError, ValueError):
            return 1

    def _restore_jobs(self) -> int:
        try:
            return max(2, min(int(self.cfg.get("parallel_jobs", 3) or 3), 6))
        except (TypeError, ValueError):
            return 3

    # ------------------------------------------------------------------ theme
    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.songs.set_dark(dark)

    def set_theme(self, choice: str) -> None:
        self.cfg["theme"] = choice
        self._update_theme_btn()
        self.save_settings()
        note = " (following system)" if choice == theme.THEME_SYSTEM else ""
        self.append_log(f">>> Theme: {choice}{note}.")

    def toggle_theme(self) -> None:
        """Flip between light and dark, leaving 'system' behind.

        Kept for the keyboard shortcut, which is a fast two-way action;
        picking an explicit mode is what the menu button is for.
        """
        self.set_theme(theme.THEME_LIGHT if self._dark else theme.THEME_DARK)

    def _update_theme_btn(self) -> None:
        """Show the current theme, and which mode 'system' resolved to."""
        choice = self.cfg.get("theme", theme.THEME_SYSTEM)
        resolved = theme.resolve(choice)
        label = _THEME_LABELS.get(choice, _THEME_LABELS[theme.THEME_SYSTEM])
        suffix = f" (following system: {resolved})" if choice == theme.THEME_SYSTEM \
            else ""
        self.theme_btn.setText(label)
        self.theme_btn.setToolTip(f"Theme: {label}{suffix}")
        for act in self.theme_btn.menu().actions():
            act.setChecked(act.data() == choice)

    # ----------------------------------------------------------------- output
    def append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_detail(self, text: str) -> None:
        self.detail_label.setText(text)

    def set_busy(self, busy: bool) -> None:
        """Enable exactly the controls that make sense in each state.

        Stop is the inverse of everything else: it is the only control that
        is live *while* a job runs, so it is the only one whose enablement
        flips the other way.
        """
        for w in (self.load_btn, self.download_btn, self.check_btn,
                  self.retry_btn, self.browse_btn, self.fix_btn,
                  self.rad_music, self.rad_video, self.thumb_check,
                  self.parallel_check, self.format_combo, self.quality_combo,
                  self.res_combo, self.url_edit, self.dir_edit):
            w.setEnabled(not busy)
        self.jobs_combo.setEnabled(not busy and self.parallel_check.isChecked())
        self.stop_btn.setEnabled(busy)

    _set_busy = set_busy

    def set_has_failures(self, has_failures: bool) -> None:
        self.retry_btn.setEnabled(has_failures and self.download_btn.isEnabled())

    # ------------------------------------------------------------- validation
    def check_prereqs(self) -> bool:
        """Confirm the app can actually do the job before starting it.

        Both failures are reported rather than raised: the user pasted a link
        or did not, and neither is a programming error.
        """
        if not core.ffmpeg_available():
            QMessageBox.critical(
                self, "ffmpeg not found",
                "ffmpeg is required to convert audio and merge video.\n\n"
                "Install it (Windows: 'winget install Gyan.FFmpeg', macOS: "
                "'brew install ffmpeg', Debian/Ubuntu: 'sudo apt install "
                "ffmpeg'), then restart this app.")
            return False
        if not self.url_edit.text().strip():
            QMessageBox.warning(
                self, "Missing link",
                "Please paste a YouTube playlist or video link first.")
            return False
        return True

    # ---------------------------------------------------------------- actions
    def on_load_pressed(self) -> None:
        self._begin("load")

    def on_download_pressed(self) -> None:
        self._begin("download")

    def on_check_pressed(self) -> None:
        self._begin("check")

    def on_retry_pressed(self) -> None:
        self._begin("retry")

    def on_stop_pressed(self) -> None:
        """Ask the worker to stop after the current song.

        Stopping mid-file is not offered: yt-dlp has already written a partial
        file by the time the user reaches for the button, and killing the
        process there would leave a file that looks complete and is not. The
        ffmpeg process is aborted directly instead, which is the one part that
        is safe to interrupt because it has not written the final file yet.
        """
        self._stop_requested = True
        core.abort_ffmpeg()
        self.append_log(">>> Stop requested. Aborting current song...")

    def _begin(self, action: str, ids=None, url=None) -> None:
        """Validate, snapshot, and start a job.

        A second job is refused rather than queued. Two jobs writing into one
        output folder would fight over filenames, and the failure would show up
        as a confusing "file already exists" on the second one rather than as
        the conflict it is.
        """
        if self._job is not None:
            self.append_log(">>> Still busy - wait for the current job to finish.")
            return
        if not self.check_prereqs():
            return
        self.save_settings()
        self._stop_requested = False
        self._set_busy(True)
        self._job = dl.DownloadJob(
            action=action,
            snapshot=self.snapshot(),
            enqueue=self._enqueue,
            ask_rename=self._prompter.ask,
            stop_requested=lambda: self._stop_requested,
            url=url,
            ids=ids,
        )
        # Shared with the job so its failure and unavailable maps stay in step
        # with what the list is showing, the way the Tk version shared them.
        self._job.entries = self.entries
        self._job.failed = self.failed
        self._job.unavailable = self.unavailable
        self._job.start()

    def _enqueue(self, msg) -> None:
        """Called from a worker thread. Just puts the message on the queue.

        Nothing is touched here. A worker thread must not call a Qt method -
        the widgets are owned by the main thread, and touching them from
        anywhere else is undefined behaviour rather than a slow path. The
        timer in :meth:`_pump` is what moves the message onto the main thread.
        """
        self._queue.put(msg)

    def _on_pump(self) -> None:
        """Drain the queue without waiting, then come back.

        A ``QTimer`` rather than ``QApplication.processEvents``: processEvents
        re-enters the event loop from wherever it is called, so a dialog
        opening from inside a handler can get processed by a *second* nested
        loop, and the same slot then runs twice for one message. A timer
        cannot re-enter like that.
        """
        while True:
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                break
            handler = self._HANDLERS.get(msg[0])
            if handler is not None:
                handler(self, *msg[1:])
        self._pump_timer.start()

    # --------------------------------------------------------------- handlers
    def _h_log(self, text) -> None:
        self.append_log(text)

    def _h_status(self, text) -> None:
        self.set_status(text)

    def _h_progress(self, status, downloaded, total, _fname, speed, eta) -> None:
        if not total:
            return
        n = self._expected_n or 1
        frac = downloaded / total
        # Overall progress is a fraction of the playlist, not of this song:
        # showing one song's bar as the whole run makes a 3-song queue look
        # like it has just started when it is nearly done.
        self.progress.setValue(min(((self._song_i - 1) + frac) / n * 100, 100.0))
        now = time.monotonic()
        if now - self._last_detail < DETAIL_THROTTLE_SECONDS:
            return
        self._last_detail = now
        self.set_detail(
            f"Song {self._song_i}/{n} · "
            f"{progress_text(int(frac * 100), fmt_speed(speed), fmt_eta(eta))} · "
            f"{fmt_bytes(downloaded)} of {fmt_bytes(total)}")

    def _h_song_index(self, i, _total) -> None:
        self._song_i = i

    def _h_tick(self, done, active, total) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.set_detail(tick_text(done, active, total))

    def _h_row_status(self, vid, text) -> None:
        self.songs.model.set_status(vid, text)

    def _h_row_progress(self, vid, downloaded, total, speed) -> None:
        if not total:
            return
        self.songs.model.set_status(
            vid,
            f"Downloading {progress_text(int(downloaded / total * 100), fmt_speed(speed))}")

    def _h_set_expected(self, n) -> None:
        self._expected_n = n or 1
        self.progress.setRange(0, self._expected_n)
        self.progress.setValue(0)

    def _h_reset_progress(self) -> None:
        self.progress.setValue(0)
        self.set_detail("")

    def _h_ask_rename(self, entry) -> None:
        self._prompter.show(self, entry)

    def _h_setup_tree(self, entries) -> None:
        self.entries = entries
        self._populate(entries)
        self.subtitle_label.setText(f"{plural(len(entries), 'song')} loaded")

    def _h_mark_statuses(self, existing) -> None:
        self._mark_statuses(existing)

    def _h_refresh_statuses(self, existing) -> None:
        self._mark_statuses(existing, only_if_clean=True)

    def _h_row_thumb(self, vid, img) -> None:
        self._set_thumbnail(vid, img)

    def _h_finished(self, text, summary) -> None:
        self._job = None
        self._stop_requested = False
        self._set_busy(False)
        self.set_status(text)
        self.set_detail("")
        # Retry is only offered when there is something to retry, and the
        # answer comes from the job's own classification rather than from
        # re-reading the list - the list's status column is a display concern.
        self.set_has_failures(bool(self.failed))
        if summary:
            QMessageBox.information(self, "Finished", summary)

    _HANDLERS = {
        dl.LOG: _h_log,
        dl.STATUS: _h_status,
        dl.PROGRESS: _h_progress,
        dl.SONG_INDEX: _h_song_index,
        dl.TICK: _h_tick,
        dl.ROW_STATUS: _h_row_status,
        dl.ROW_PROGRESS: _h_row_progress,
        dl.SET_EXPECTED: _h_set_expected,
        dl.RESET_PROGRESS: _h_reset_progress,
        dl.ASK_RENAME: _h_ask_rename,
        dl.SETUP_TREE: _h_setup_tree,
        dl.MARK_STATUSES: _h_mark_statuses,
        dl.REFRESH_STATUSES: _h_refresh_statuses,
        dl.ROW_THUMB: _h_row_thumb,
        dl.FINISHED: _h_finished,
    }

    # -------------------------------------------------------------- the list
    def _populate(self, entries) -> None:
        """Replace the list with ``entries`` and tick everything.

        Mirrors ``PlaylistTable.populate``: a fresh load is a fresh list, so
        the previous statuses and failures are dropped rather than carried
        over onto songs that may not be the same ones.
        """
        self.failed.clear()
        self.unavailable.clear()
        self.songs.model.set_songs(
            Song(e["id"], e["title"], e["uploader"]) for e in entries)
        self.songs.model.set_status_all("Not downloaded")
        for e in entries:
            self._thumbs.request(e["id"])
        self.set_has_failures(False)

    def _mark_statuses(self, existing, only_if_clean=False) -> None:
        """Apply Downloaded/Missing across every row from a saved-title set.

        ``only_if_clean`` is what makes a manual Check Saved different from
        the check a download run does for itself: a row that has already
        failed, or was deliberately skipped, keeps what it is saying, because
        the user has been told something more specific than "it's missing".
        """
        model = self.songs.model
        for entry in self.entries:
            vid = entry["id"]
            if only_if_clean and (vid in self.failed
                                  or vid in self.unavailable
                                  or status_mod.role_for(
                                      model.song_of(vid).status) != "muted"
                                  and model.song_of(vid).status != "Not downloaded"):
                continue
            if is_saved_match(existing, entry["title"]):
                model.set_status(vid, "Downloaded")
            else:
                model.set_status(vid, "Missing")

    def _set_thumbnail(self, vid, img) -> None:
        """Show fetched artwork, or do nothing.

        A failed fetch sends ``None`` rather than an exception, so a row with
        no artwork simply stays as it is instead of showing a broken image.
        """
        if img is None:
            return
        self.songs.model.set_thumbnail(vid, to_pixmap(img))

    # --------------------------------------------------------------- settings
    def save_settings(self) -> None:
        self.cfg.update({
            "last_url": self.url_edit.text().strip(),
            "output_dir": self.dir_edit.text().strip(),
            "format": self.format_combo.currentText(),
            "quality": self.quality_combo.currentText(),
            "media": self.media(),
            "resolution": self.res_combo.currentText(),
            "thumbnail": self.thumb_check.isChecked(),
            "parallel": self.parallel_check.isChecked(),
            "parallel_jobs": self.current_jobs() if self.parallel_check.isChecked()
            else 3,
        })
        config.save(self.cfg)

    def snapshot(self) -> dict:
        """Copy the current settings for a job to run against."""
        cookie_path = self.cfg.get("cookie_path", "") or ""
        # A cookie file that has since been deleted or replaced must not be
        # handed to the worker; the job would fail on every file instead of
        # once, and the reason would be much harder to see.
        if cookie_path and not validate_cookie_file(cookie_path)[0]:
            cookie_path = ""
        return {
            "url": self.url_edit.text().strip(),
            "dir": paths.resolve_user_path(
                self.dir_edit.text(), paths.home_dir()),
            "media": self.media(),
            "format": self.format_combo.currentText(),
            "quality": self.quality_combo.currentText(),
            "resolution": self.res_combo.currentText(),
            "thumbnail": self.thumb_check.isChecked(),
            "cookie_path": cookie_path,
            "selected": self.songs.model.checked_ids(),
            "parallel_jobs": self.current_jobs()
            if self.parallel_check.isChecked() else 1,
        }

    def browse_dir(self) -> None:
        start = self.dir_edit.text().strip() or paths.home_dir()
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        if chosen:
            self.dir_edit.setText(chosen)

    def choose_cookie_file(self) -> None:
        initial = core._cookies_txt_path()
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose your signed-in cookies.txt",
            os.path.dirname(initial) or paths.home_dir(),
            "cookies.txt (cookies.txt);;Text files (*.txt);;All files (*)")
        if not path:
            return
        ok, count, youtube, msg = validate_cookie_file(path)
        if not ok:
            self.append_log(
                f">>> Fix blocked: rejected '{os.path.basename(path)}' - {msg}.")
            return
        self.cfg["cookie_path"] = path
        self.save_settings()
        self._refresh_cookie_status()
        self.append_log(
            f">>> Fix blocked: using cookies file '{os.path.basename(path)}' "
            f"({count} cookies, {youtube} for YouTube/Google).")

    def _refresh_cookie_status(self) -> None:
        path = self.cfg.get("cookie_path", "")
        ok, count, _yt, _msg = validate_cookie_file(path) if path \
            else (False, 0, 0, "")
        if ok:
            self.cookie_label.setText(
                f"cookies: {os.path.basename(path)} ({count})")
        else:
            self.cookie_label.setText("no cookies file")

    # -------------------------------------------------------------- shortcuts
    def _bind_shortcuts(self) -> None:
        """Window-level keyboard shortcuts.

        Bound on the window rather than per-widget so they work regardless of
        which control has focus. The ones the song list handles for itself
        (Space, Ctrl+A) are left to the list.
        """
        for seq, slot in (
            ("Ctrl+F", self.songs.focus_search),
            ("Ctrl+L", self.on_load_pressed),
            ("Ctrl+D", self.on_download_pressed),
            ("Ctrl+T", self.toggle_theme),
            ("F5", self.on_check_pressed),
        ):
            act = QAction(self)
            act.setShortcut(seq)
            act.triggered.connect(slot)
            self.addAction(act)

    # ------------------------------------------------------------------ close
    def closeEvent(self, event) -> None:
        if not self._closed:
            self._closed = True
            self.save_settings()
            target = self.dir_edit.text().strip()
            if target and os.path.isdir(os.path.expanduser(target)):
                cleanup_partials(os.path.expanduser(target))
        super().closeEvent(event)


def run() -> int:
    """Create the application and enter the Qt event loop."""
    cfg = config.load()
    app = QApplication.instance() or QApplication([])
    dark = theme.is_dark(cfg.get("theme", theme.THEME_SYSTEM))
    theme.apply_theme(app, dark)
    win = MainWindow(dark=dark)
    win.show()
    return app.exec()
