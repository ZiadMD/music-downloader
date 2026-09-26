"""The name-collision dialog, and the thread bridge behind it.

A download worker that finds an existing file has to ask the user what to do,
but Qt - like Tk - may only be touched from the main thread. The arrangement
is the one :mod:`musicdl.ui.dialogs` already uses, unchanged:

* the worker calls :meth:`RenamePrompter.ask`, which puts a message on the
  window's queue and blocks on a :class:`threading.Event`
* the window's queue pump calls :meth:`RenamePrompter.show`, which raises the
  dialog on the main thread and sets the event

The prompter is handed the same ``enqueue`` the downloader was given, so
nothing in :mod:`musicdl.ui.downloader` knows a second toolkit exists.

The registry is a plain dict rather than anything clever, because there is at
most one prompt in flight: the downloader processes songs one at a time
within a batch and the dialog is modal.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..ui import downloader as dl
from ..ui import tokens

# How long a worker will block waiting for the user to answer. Long enough
# that a user who walked away does not leave a permanently stuck worker, and
# the answer on timeout is "cancel" - the safe direction, since it stops the
# run rather than renaming files the user never approved.
RENAME_TIMEOUT_SECONDS = 3600

# The three answers, and what each one means to the downloader.
SKIP = "skip"
RENAME = "rename"
CANCEL = "cancel"


class RenameDialog(QDialog):
    """Skip / Rename / Cancel, for one colliding file."""

    def __init__(self, entry: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Name already exists")
        self.setModal(True)
        # Fixed size: this is a message and three buttons, and letting it be
        # resized only produces a dialog with a lot of empty space in it.
        self.setMinimumWidth(460)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(tokens.SPACE_2XL, tokens.SPACE_2XL,
                                 tokens.SPACE_2XL, tokens.SPACE_LG)
        outer.setSpacing(tokens.SPACE_MD)

        outer.addWidget(QLabel("A saved file already has the same name as:"))
        # The title is the whole question, so it gets the emphasis rather than
        # sitting in body text alongside the explanation.
        name = QLabel(entry.get("title", ""))
        name.setObjectName("section")
        name.setWordWrap(True)
        name.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(name)
        outer.addSpacing(tokens.SPACE_XS)
        outer.addWidget(QLabel("What should I do with this download?"))

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, tokens.SPACE_LG, 0, 0)
        buttons.setSpacing(tokens.SPACE_SM)
        # Order is increasing destructiveness, left to right. Cancel is the
        # default: pressing Enter on a dialog that appeared unasked should
        # never rename or download anything.
        self._value = CANCEL
        for text, value in (
            ("Skip this song", SKIP),
            ("Rename to 'Title (2)'", RENAME),
            ("Cancel rest", CANCEL),
        ):
            btn = QPushButton(text)
            if value == CANCEL:
                btn.setObjectName("destructive")
            btn.clicked.connect(lambda _checked=False, v=value: self._decide(v))
            buttons.addWidget(btn, 1)
            if value == CANCEL:
                btn.setDefault(True)
        outer.addLayout(buttons)

    def _decide(self, value: str) -> None:
        self._value = value
        self.accept()

    def value(self) -> str:
        """The answer, once the dialog has closed."""
        return self._value


class RenamePrompter:
    """Runs the dialog on the main thread and blocks the worker on it."""

    def __init__(self, enqueue) -> None:
        self._emit = enqueue
        self._events: dict = {}
        self._answers: dict = {}
        # Guards the two dicts. The worker registers, the main thread resolves,
        # and the window can close in between - so "is this prompt still
        # pending" has to be a real question rather than a KeyError.
        self._lock = threading.Lock()

    def ask(self, entry: dict) -> str:
        """Block the calling worker until the user answers. Never raises."""
        vid = entry.get("id", "")
        event = threading.Event()
        with self._lock:
            self._events[vid] = event
            self._answers[vid] = None
        self._emit((dl.ASK_RENAME, entry))
        event.wait(RENAME_TIMEOUT_SECONDS)
        with self._lock:
            self._events.pop(vid, None)
            # Nothing recorded means the window closed or the wait timed out.
            return self._answers.pop(vid, None) or CANCEL

    def show(self, parent, entry: dict) -> None:
        """Raise the dialog for a pending prompt. Main thread only."""
        vid = entry.get("id", "")
        with self._lock:
            if vid not in self._events:
                return     # already answered, or the worker gave up
        answer = CANCEL
        try:
            dialog = RenameDialog(entry, parent)
            dialog.exec()
            answer = dialog.value()
        finally:
            # Released in a finally, and the answer recorded first: if raising
            # the dialog itself fails, the worker still has to be woken up or
            # the whole download hangs waiting for a prompt that will never
            # come again. Defaulting to "cancel" stops the run rather than
            # touching files the user never approved.
            with self._lock:
                self._answers[vid] = answer
                event = self._events.get(vid)
            if event:
                event.set()
