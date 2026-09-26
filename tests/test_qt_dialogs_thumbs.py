"""Tests for Qt rename dialogs and thumbnail loader."""

import queue
import threading
from PIL import Image
from PySide6.QtGui import QPixmap

from musicdl.qt import dialogs, thumbs
from musicdl.ui import downloader as dl


class TestRenameDialog:
    def test_dialog_buttons_set_expected_values(self, qapp):
        entry = {"id": "123", "title": "Test Song"}
        dialog = dialogs.RenameDialog(entry)
        assert dialog.value() == dialogs.CANCEL

        dialog._decide(dialogs.SKIP)
        assert dialog.value() == dialogs.SKIP

        dialog._decide(dialogs.RENAME)
        assert dialog.value() == dialogs.RENAME

        dialog._decide(dialogs.CANCEL)
        assert dialog.value() == dialogs.CANCEL
        dialog.close()


class TestRenamePrompter:
    def test_ask_and_show_flow(self, qapp):
        q = queue.Queue()
        prompter = dialogs.RenamePrompter(q.put)

        entry = {"id": "xyz", "title": "Collision Song"}
        answer_holder = []

        def worker():
            res = prompter.ask(entry)
            answer_holder.append(res)

        t = threading.Thread(target=worker)
        t.start()

        # Wait until prompt is enqueued
        msg = q.get(timeout=2)
        assert msg[0] == dl.ASK_RENAME
        assert msg[1] == entry

        # Simulate resolving prompt
        with prompter._lock:
            prompter._answers["xyz"] = dialogs.RENAME
            ev = prompter._events.get("xyz")
            if ev:
                ev.set()

        t.join(timeout=2)
        assert answer_holder == [dialogs.RENAME]


class TestPixmapConversion:
    def test_to_pixmap_rgba(self, qapp):
        img = Image.new("RGBA", (80, 45), (255, 0, 0, 255))
        pix = thumbs.to_pixmap(img)
        assert isinstance(pix, QPixmap)
        assert not pix.isNull()
        assert pix.width() == 80
        assert pix.height() == 45

    def test_to_pixmap_rgb_converted(self, qapp):
        img = Image.new("RGB", (60, 30), (0, 255, 0))
        pix = thumbs.to_pixmap(img)
        assert isinstance(pix, QPixmap)
        assert not pix.isNull()
        assert pix.width() == 60
        assert pix.height() == 30
