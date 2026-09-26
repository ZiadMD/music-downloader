"""Reusable widgets for the app.

The playlist table is the screen's centre of gravity, so it gets its own class
rather than a pile of ``Treeview`` configuration inside the main window.
"""

import io
import queue
import threading
import tkinter as tk
import urllib.request

import ttkbootstrap as tb
from PIL import Image, ImageDraw, ImageTk

from ..naming import is_saved_match

# Thumbnail geometry. 16:9 at 96x54 suits the 66px row height with padding.
THUMB_SIZE = (96, 54)
THUMB_RADIUS = 8
THUMB_WORKERS = 4
THUMB_URL = "https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
_USER_AGENT = "Mozilla/5.0"

# A coloured dot prefixes each status so rows are scannable at a glance.
STATUS_DOT = "● "


class ThumbnailLoader:
    """Fetches playlist artwork in the background.

    Rows are inserted immediately with a placeholder; each image is fetched on
    a worker thread and pushed onto the app's message queue when ready, so the
    UI never blocks on the network.
    """

    def __init__(self, emit):
        self._emit = emit
        self._jobs = queue.Queue()
        self._workers = []

    def start(self, count=THUMB_WORKERS):
        if self._workers:
            return
        for _ in range(count):
            t = threading.Thread(target=self._work, daemon=True)
            t.start()
            self._workers.append(t)

    def request(self, vid):
        self.start()
        self._jobs.put(vid)

    def shutdown(self):
        for _ in self._workers:
            self._jobs.put(None)

    def _work(self):
        while True:
            vid = self._jobs.get()
            if vid is None:
                self._jobs.task_done()
                return
            try:
                self._emit(("row_thumb", vid, self._fetch(vid)))
            except Exception:
                self._emit(("row_thumb", vid, None))
            finally:
                self._jobs.task_done()

    @staticmethod
    def _fetch(vid):
        req = urllib.request.Request(THUMB_URL.format(vid=vid),
                                     headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        img.thumbnail(THUMB_SIZE)
        # Round the corners so artwork does not look like a raw square.
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, img.width - 1, img.height - 1], radius=THUMB_RADIUS, fill=255)
        img.putalpha(mask)
        return img


class PlaylistTable(tb.Frame):
    """The song list: thumbnail, tick box, title, artist, and status.

    Owns the row model (``entries``, tick state, per-song status) and the
    Treeview that renders it. Emits ``("row_action", vid, action)`` for
    'retry' so the owning window can start a job.
    """

    COLUMNS = ("pick", "title", "artist", "status")
    ROW_HEIGHT = 66
    TICK = "✓"
    # Rows visible before the table scrolls. Keeps the window's natural
    # height sane on tall playlists; the table still grows with the window.
    VISIBLE_ROWS = 8

    def __init__(self, master, emit):
        super().__init__(master, padding=(2, 2))
        self._emit = emit

        self.entries = []
        self.iid_by_id = {}     # vid -> iid
        self.vid_by_iid = {}    # iid -> vid
        self.checked = {}       # vid -> ticked
        self.row_order = []     # iids in insertion order
        self.status_by_vid = {}  # vid -> display status
        self.failed = {}        # vid -> failure reason
        self.unavailable = {}   # vid -> reason
        self._thumbs = {}       # vid -> PhotoImage (must be kept alive)
        self._loader = ThumbnailLoader(emit)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_toolbar()
        self._build_tree()

    # ------------------------------------------------------------------ build
    def _build_toolbar(self):
        bar = tb.Frame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        bar.columnconfigure(1, weight=1)

        tb.Label(bar, text="Search", bootstyle="secondary").grid(
            row=0, column=0, sticky="w")
        self.filter_var = tb.StringVar(value="")
        self.filter_var.trace_add("write", lambda *_: self.apply_filter())
        entry = tb.Entry(bar, textvariable=self.filter_var)
        entry.grid(row=0, column=1, sticky="ew", padx=(6, 8))

        self.count_var = tb.StringVar(value="")
        tb.Label(bar, textvariable=self.count_var, bootstyle="secondary").grid(
            row=0, column=2, padx=(0, 8))

        tb.Button(bar, text="Tick all", bootstyle="secondary-outline", width=10,
                  command=lambda: self.set_all_checked(True)).grid(row=0, column=3)
        tb.Button(bar, text="Untick all", bootstyle="secondary-outline", width=11,
                  command=lambda: self.set_all_checked(False)).grid(
            row=0, column=4, padx=(6, 0))

    def _build_tree(self):
        style = tb.Style()
        style.configure("Playlist.Treeview", rowheight=self.ROW_HEIGHT)
        self.tree = tb.Treeview(
            self, columns=self.COLUMNS, show="tree headings",
            style="Playlist.Treeview", height=self.VISIBLE_ROWS,
        )
        self.tree.heading("#0", text="")
        self.tree.heading("pick", text=self.TICK)
        self.tree.heading("title", text="Song")
        self.tree.heading("artist", text="Artist")
        self.tree.heading("status", text="Status")
        self.tree.column("#0", width=112, anchor="center", stretch=False,
                         minwidth=112)
        self.tree.column("pick", width=40, anchor="center", stretch=False,
                         minwidth=40)
        self.tree.column("title", width=380, anchor="w")
        self.tree.column("artist", width=180, anchor="w")
        self.tree.column("status", width=150, anchor="center")
        self.tree.grid(row=1, column=0, sticky="nsew")

        vsb = tb.Scrollbar(self, orient="vertical", command=self.tree.yview)
        vsb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.tag_configure("ok", foreground="#2eb85c")
        self.tree.tag_configure("missing", foreground="#dc3545")
        self.tree.tag_configure("busy", foreground="#4dabf7")
        self.tree.tag_configure("muted", foreground="#868e96")

        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", self._on_space)

    def apply_style_colors(self, colors):
        """Re-tint the status rows after a theme change."""
        self.tree.tag_configure("ok", foreground=getattr(colors, "success", "#2eb85c"))
        self.tree.tag_configure("missing", foreground=getattr(colors, "danger", "#dc3545"))
        self.tree.tag_configure("busy", foreground=getattr(colors, "info", "#4dabf7"))
        self.tree.tag_configure("muted", foreground=getattr(colors, "secondary", "#868e96"))

    # ------------------------------------------------------------------- data
    def populate(self, entries):
        """Replace the contents with ``entries`` and tick everything."""
        self.tree.delete(*self.tree.get_children())
        self.iid_by_id.clear()
        self.vid_by_iid.clear()
        self.checked.clear()
        self.row_order.clear()
        self.status_by_vid.clear()
        self.failed.clear()
        self.unavailable.clear()
        self._thumbs.clear()
        for e in entries:
            self.checked[e["id"]] = True
            iid = self.tree.insert(
                "", "end", image="", values=(self.TICK, e["title"], e["uploader"], "New"))
            self.iid_by_id[e["id"]] = iid
            self.vid_by_iid[iid] = e["id"]
            self.row_order.append(iid)
            self._loader.request(e["id"])
        self._update_count()

    def set_thumbnail(self, vid, img):
        iid = self.iid_by_id.get(vid)
        if not iid or img is None:
            return
        try:
            photo = ImageTk.PhotoImage(img)
        except Exception:
            return
        self._thumbs[vid] = photo  # keep a reference or Tk garbage-collects it
        self.tree.item(iid, image=photo)

    # ----------------------------------------------------------------- status
    def set_status(self, vid, text, keep=None):
        iid = self.iid_by_id.get(vid)
        if not iid:
            return
        display = text if text.startswith(STATUS_DOT) else STATUS_DOT + text
        self.status_by_vid[vid] = display
        self.tree.set(iid, "status", display)
        tag = keep or self._status_tag(text)
        self.tree.item(iid, tags=(tag,) if tag else ())

    def mark_statuses(self, existing, only_if_clean=False):
        """Apply Downloaded/Missing across every row from a saved-title set."""
        for e in self.entries:
            vid = e["id"]
            if only_if_clean and (vid in self.failed or vid in self.unavailable
                                  or "skipped" in self.status_by_vid.get(vid, "").lower()):
                continue
            if is_saved_match(existing, e["title"]):
                self.set_status(vid, "Downloaded", keep="ok")
            else:
                self.set_status(vid, "Missing", keep="missing")

    @staticmethod
    def _status_tag(text):
        low = text.lower()
        if any(k in low for k in ("unavailable", "missing", "failed")):
            return "missing"
        if "downloaded" in low or "skipped" in low:
            return "ok"
        if "downloading" in low or "waiting" in low or "pending" in low:
            return "busy"
        return "muted"

    # ------------------------------------------------------------------ ticks
    def toggle_checked(self, vid):
        self.checked[vid] = not self.checked.get(vid, True)
        iid = self.iid_by_id.get(vid)
        if iid:
            self.tree.set(iid, "pick", self.TICK if self.checked[vid] else "")
        self._update_count()

    def set_all_checked(self, on):
        for vid in self.checked:
            self.checked[vid] = bool(on)
        mark = self.TICK if on else ""
        for iid, vid in self.vid_by_iid.items():
            self.tree.set(iid, "pick", mark)
        self._update_count()

    def checked_ids(self):
        return [vid for vid, on in self.checked.items() if on]

    def mark_default(self, vid):
        self.checked.setdefault(vid, True)

    def _update_count(self):
        total = len(self.checked)
        if not total:
            self.count_var.set("")
            return
        picked = len(self.checked_ids())
        self.count_var.set(f"{picked}/{total} selected")

    # ----------------------------------------------------------------- filter
    def apply_filter(self):
        query = (self.filter_var.get() or "").strip().lower()
        children = set(self.tree.get_children(""))
        visible = [iid for iid in self.row_order if self._matches(iid, query)] \
            if query else list(self.row_order)
        for iid in children - set(visible):
            self.tree.detach(iid)
        for index, iid in enumerate(visible):
            if iid not in children:
                self.tree.move(iid, "", min(index, len(self.tree.get_children(""))))

    def _matches(self, iid, query) -> bool:
        title, artist = self.tree.item(iid, "values")[1:3]
        return query in f"{title} {artist}".lower()

    # ------------------------------------------------------------------ input
    def _on_click(self, event):
        if self.tree.identify_column(event.x) == "#1":
            vid = self.vid_by_iid.get(self.tree.identify_row(event.y))
            if vid:
                self.toggle_checked(vid)
                return "break"
        return None

    def _on_space(self, _event=None):
        for iid in self.tree.selection():
            vid = self.vid_by_iid.get(iid)
            if vid:
                self.toggle_checked(vid)
        return "break"

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        vid = self.vid_by_iid.get(iid) if iid else None
        if not vid:
            return
        actions = [("Retry this song", "retry")] if vid in self.failed else []
        if not actions:
            return
        self.tree.selection_set(iid)
        menu = tk.Menu(self, tearoff=0)
        for label, action in actions:
            menu.add_command(label=label,
                             command=lambda a=action: self._emit(("row_action", vid, a)))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
