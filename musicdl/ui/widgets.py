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
from . import fonts, tokens

# Thumbnail geometry. 16:9 at 80x45 suits the 56px row height with padding.
THUMB_SIZE = tokens.THUMB_SIZE
THUMB_RADIUS = tokens.THUMB_RADIUS
THUMB_WORKERS = 4
THUMB_URL = "https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
_USER_AGENT = "Mozilla/5.0"

# Maps a status word onto a tag used to colour the row, and onto the glyph
# shown beside it. Colour is never the only signal: every state carries both a
# glyph and a readable word, so the list works without colour vision.
STATUS_TAGS = {
    "ok": "ok",
    "downloaded": "ok",
    "skipped": "ok",
    "missing": "missing",
    "failed": "missing",
    "unavailable": "missing",
    "downloading": "busy",
    "waiting": "busy",
    "pending": "busy",
    # The neutral default: a row nobody has examined yet.
    "not": "muted",
}

# ttkbootstrap's name for de-emphasised foreground text.
MUTED = "secondary"


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
    ROW_HEIGHT = tokens.ROW_HEIGHT
    TICK = "✓"
    # Rows visible before the table scrolls. Keeps the window's natural
    # height sane on tall playlists; the table still grows with the window.
    VISIBLE_ROWS = 8

    # Fixed column widths. The thumbnail and tick columns are narrow and never
    # stretch; the status column is sized for its longest phrase so rows do not
    # reflow when their state changes.
    THUMB_COLUMN = 96
    STATUS_COLUMN = 150

    # Empty-state copy. It says what to do next rather than apologising for the
    # absence of content, and it stays to one line of instruction - a paragraph
    # in the middle of an empty panel is just noise.
    EMPTY_TITLE = "No songs yet"
    EMPTY_HINT = "Paste a playlist link above and choose Load Playlist."
    FILTER_TITLE = "Nothing matches"
    FILTER_HINT = "No song in this playlist matches the search."

    def __init__(self, master, emit, dark=True):
        super().__init__(master, padding=(2, 2))
        self._emit = emit
        self._dark = dark

        self.entries = []
        self.iid_by_id = {}     # vid -> iid
        self.vid_by_iid = {}    # iid -> vid
        self.checked = {}       # vid -> ticked
        self.row_order = []     # iids in insertion order
        self.status_by_vid = {}  # vid -> display status
        self._tag_by_vid = {}    # vid -> current status tag, for re-banding
        self.failed = {}        # vid -> failure reason
        self.unavailable = {}   # vid -> reason
        self._thumbs = {}       # vid -> PhotoImage (must be kept alive)
        self._loader = ThumbnailLoader(emit)
        self._anchor = None     # iid a shift-extend selection started from

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
        self.filter_entry = tb.Entry(bar, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=1, sticky="ew", padx=(tokens.SPACE_SM, tokens.SPACE_MD))

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
        style.configure("Playlist.Treeview", rowheight=self.ROW_HEIGHT,
                        font=fonts.body())
        style.configure("Playlist.Treeview.Heading", font=fonts.caption_bold())
        self.tree = tb.Treeview(
            self, columns=self.COLUMNS, show="tree headings",
            style="Playlist.Treeview", height=self.VISIBLE_ROWS,
        )
        self.tree.heading("#0", text="")
        self.tree.heading("pick", text=self.TICK)
        self.tree.heading("title", text="Song")
        self.tree.heading("artist", text="Artist")
        self.tree.heading("status", text="Status")
        # The tick column is a fixed 40px and carries no header of its own; the
        # thumbnail column is likewise fixed. Only the text columns stretch, so
        # a long title never squeezes the status column out of alignment.
        self.tree.column("#0", width=self.THUMB_COLUMN, anchor="center",
                         stretch=False, minwidth=self.THUMB_COLUMN)
        self.tree.column("pick", width=tokens.CHECKBOX_COLUMN, anchor="center",
                         stretch=False, minwidth=tokens.CHECKBOX_COLUMN)
        self.tree.column("title", width=380, anchor="w")
        self.tree.column("artist", width=180, anchor="w")
        # Wide enough for the longest status phrase plus its glyph, so the
        # column never reflows when a row changes state.
        self.tree.column("status", width=self.STATUS_COLUMN, anchor="center",
                         stretch=False, minwidth=self.STATUS_COLUMN)
        self.tree.grid(row=1, column=0, sticky="nsew")
        # The list must be reachable by keyboard, which needs both an explicit
        # takefocus and a real tab stop - a Treeview is neither by default.
        # The value is a string, not an int: ttk only accepts a Tcl boolean.
        self.tree.configure(takefocus="1")

        vsb = tb.Scrollbar(self, orient="vertical", command=self.tree.yview)
        vsb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)

        # The empty state sits on top of the tree rather than beside it, so it
        # occupies the same rectangle the rows would have and the window never
        # changes height between "no playlist" and "loaded". A Treeview cannot
        # host child widgets, so this is a sibling in the same grid cell, and
        # `lift` puts it above the tree whenever there is nothing to show.
        self.empty = tb.Frame(self)
        self.empty_title = tb.Label(self.empty, text=self.EMPTY_TITLE,
                                    bootstyle=MUTED, font=fonts.section())
        self.empty_title.pack()
        self.empty_hint = tb.Label(self.empty, text=self.EMPTY_HINT,
                                   bootstyle=MUTED, font=fonts.secondary(),
                                   justify="center")
        self.empty_hint.pack(pady=(tokens.SPACE_XS, 0))
        self.empty.grid(row=1, column=0, sticky="nsew")
        self._show_empty_state(True)

        self._apply_tags(tokens.palette(self._dark))

        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Shift-space>", self._on_shift_space)
        self.tree.bind("<Control-a>", self.select_all)
        self.tree.bind("<Control-A>", self.select_all)
        self.tree.bind("<Command-a>", self.select_all)
        # Find belongs on the tree, not just on the search box: Ctrl+F has to
        # work from wherever focus happens to be, and the tree is where focus
        # rests for most of the session.
        self.tree.bind("<Control-f>", self.focus_filter)
        self.tree.bind("<Command-f>", self.focus_filter)
        # Escape belongs to the search box first, and only falls through to
        # clearing the table selection when the box is already empty.
        self.filter_entry.bind("<Escape>", self._on_filter_escape)

    def _apply_tags(self, palette: tokens.Palette):
        """Colour row tags from the token palette, never from literals.

        Each tag is a *semantic* role rather than a raw colour, so the light and
        dark palettes can pick different values for the same meaning while
        both clearing WCAG AA against their own surface.
        """
        self.tree.tag_configure("ok", foreground=palette.success)
        self.tree.tag_configure("missing", foreground=palette.danger)
        self.tree.tag_configure("busy", foreground=palette.info)
        self.tree.tag_configure("muted", foreground=palette.on_surface_muted)
        # Banding is a background, not a foreground, so it is a separate tag
        # that coexists with the status tag on the same row. Tk applies tags in
        # order and later foregrounds would win, so the band deliberately
        # touches only `background`.
        self.tree.tag_configure("band", background=palette.surface_subtle)

    def apply_style_colors(self, dark: bool):
        """Re-tint the status rows after a theme change."""
        self._dark = dark
        self._apply_tags(tokens.palette(dark))

    # ------------------------------------------------------------------- data
    def populate(self, entries):
        """Replace the contents with ``entries`` and tick everything."""
        self.tree.delete(*self.tree.get_children())
        self.iid_by_id.clear()
        self.vid_by_iid.clear()
        self.checked.clear()
        self.row_order.clear()
        self.status_by_vid.clear()
        self._tag_by_vid.clear()
        self.failed.clear()
        self.unavailable.clear()
        self._thumbs.clear()
        for e in entries:
            self.checked[e["id"]] = True
            iid = self.tree.insert(
                "", "end", image="", values=(self.TICK, e["title"], e["uploader"], ""))
            self.iid_by_id[e["id"]] = iid
            self.vid_by_iid[iid] = e["id"]
            self.row_order.append(iid)
            self._loader.request(e["id"])
        self.set_status_all("new", "Not downloaded")
        self._update_count()

    def _row_tags(self, iid, status_tag):
        """The status tag plus, on alternate rows, the banding tag.

        Banding is what makes a dense list scannable: without it, a 56px row of
        text and artwork reads as one undifferentiated block. It is applied by
        position rather than at insert time because filtering reorders rows,
        and a band that stayed with a row would look wrong the moment the list
        changed underneath it.
        """
        try:
            index = self.tree.index(iid)
        except (tk.TclError, ValueError):
            index = 0
        tags = [status_tag] if status_tag else []
        if index % 2:
            tags.append("band")
        return tuple(tags)

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
        """Show a status on a row as glyph + word, tinted by its tag.

        The glyph is what makes the state readable without colour vision, and
        the word is what makes it unambiguous. Neither is decoration. Callers
        pass the raw status ("Downloading 42% · 1.4 MiB/s"); the glyph is
        stripped and re-applied here so it is never doubled up.
        """
        iid = self.iid_by_id.get(vid)
        if not iid:
            return
        tag = keep or self._status_tag(text)
        word = text.split(" ", 1)[-1] if " " in text else text
        display = f"{tokens.STATUS_ICONS.get(tag, '·')} {word}"
        self.status_by_vid[vid] = display
        self._tag_by_vid[vid] = tag
        self.tree.set(iid, "status", display)
        self.tree.item(iid, tags=self._row_tags(iid, tag))

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
        """Resolve a status phrase to its tag, which carries colour and glyph.

        Status phrases arrive in three shapes: a bare word ("Failed"), a word
        with an ellipsis ("Waiting..."), and a word with a live reading
        ("Downloading 42% · 1.4 MiB/s"). Matching on the first whitespace-
        delimited token handles all three, but the trailing punctuation has to
        come off first or "Downloading..." never matches its own key.
        """
        first = text.split(" ", 1)[0].lower().rstrip(".…")
        return STATUS_TAGS.get(first, "muted")

    def set_status_all(self, tag, word):
        """Give every row the same status, used for the initial 'new' state."""
        display = f"{tokens.STATUS_ICONS[tag]} {word}"
        for vid in self.checked:
            self.status_by_vid[vid] = display
            self._tag_by_vid[vid] = tag
            iid = self.iid_by_id.get(vid)
            if iid:
                self.tree.set(iid, "status", display)
                self.tree.item(iid, tags=self._row_tags(iid, tag))

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
        self._show_empty_state(not self.tree.get_children(""))
        if not total:
            self.count_var.set("")
            return
        picked = len(self.checked_ids())
        self.count_var.set(f"{picked}/{total} selected")

    def _show_empty_state(self, empty: bool):
        """Show or hide the placeholder, with copy to match the reason.

        "Nothing loaded" and "the search matched nothing" are different
        problems with different fixes, so they get different text rather than
        one generic message. The panel is only raised when it is relevant, so
        it never steals clicks from the rows underneath.
        """
        if not empty:
            self.empty.grid_remove()
            return
        filtered = bool((self.filter_var.get() or "").strip())
        self.empty_title.configure(
            text=self.FILTER_TITLE if filtered else self.EMPTY_TITLE)
        self.empty_hint.configure(
            text=self.FILTER_HINT if filtered else self.EMPTY_HINT)
        self.empty.grid()
        # Above the Treeview, which otherwise sits on top of it.
        self.empty.lift()

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
        # Banding is positional, so rows have to be re-tagged after every
        # reorder - otherwise the stripes stay behind and the list looks
        # arbitrary the moment a search runs.
        for iid in visible:
            vid = self.vid_by_iid.get(iid)
            if vid is not None:
                self.tree.item(iid, tags=self._row_tags(iid, self._tag_by_vid.get(vid)))
        # A search that matches nothing is a different situation from an empty
        # playlist, and the placeholder needs to say so.
        self._show_empty_state(not self.tree.get_children(""))

    def _matches(self, iid, query) -> bool:
        title, artist = self.tree.item(iid, "values")[1:3]
        return query in f"{title} {artist}".lower()

    # ------------------------------------------------------------------ input
    def _on_click(self, event):
        iid = self.tree.identify_row(event.y)
        # Shift-click extends the selection, matching every other list view.
        if iid and (event.state & 0x0001):
            self._extend_selection_to(iid)
        elif iid:
            self.tree.selection_set(iid)
        if self.tree.identify_column(event.x) == "#1":
            vid = self.vid_by_iid.get(iid)
            if vid:
                self.toggle_checked(vid)
                return "break"
        return None

    def _extend_selection_to(self, iid):
        """Extend the selection from the anchor row down to ``iid``.

        Tk's Treeview has no shift-click of its own, so the anchor is tracked
        here. Anchoring on the first row of a shift-drag makes the gesture feel
        natural: the range always starts where the selection began.
        """
        if not self._anchor:
            self._anchor = iid
        order = self.visible_order()
        try:
            start = order.index(self._anchor)
            end = order.index(iid)
        except ValueError:
            # The anchor was filtered out of view; start a fresh range.
            self._anchor = iid
            self.tree.selection_set(iid)
            return
        lo, hi = sorted((start, end))
        self.tree.selection_set(order[lo:hi + 1])

    def visible_order(self):
        """Row iids in display order, which differs from row_order when filtered."""
        return list(self.tree.get_children(""))

    def _on_space(self, _event=None):
        """Toggle the tick box on every selected row."""
        for iid in self.tree.selection():
            vid = self.vid_by_iid.get(iid)
            if vid:
                self.toggle_checked(vid)
        return "break"

    def _on_shift_space(self, _event=None):
        """Set every selected row to ticked, rather than flipping them.

        Flipping a mixed selection is the least predictable behaviour, so the
        modifier sets a known state instead.
        """
        selection = self.tree.selection()
        if not selection:
            return "break"
        want = not all(self.checked.get(self.vid_by_iid.get(iid, ""), False)
                       for iid in selection)
        for iid in selection:
            vid = self.vid_by_iid.get(iid)
            if vid is None or self.checked.get(vid, True) == want:
                continue
            self.checked[vid] = want
            self.tree.set(iid, "pick", self.TICK if want else "")
        self._update_count()
        return "break"

    def focus_filter(self, _event=None):
        """Move keyboard focus into the search box (Ctrl/Cmd+F).

        Selects the existing text so typing replaces it, which is what the
        user almost always wants from a find shortcut.
        """
        self.filter_entry.focus_set()
        self.filter_entry.select_range(0, tk.END)
        return "break"

    def clear_filter(self, _event=None):
        """Empty the search box and restore every row."""
        if not self.filter_var.get():
            return "break"
        self.filter_var.set("")
        return "break"

    def _on_filter_escape(self, _event=None):
        """Escape in the search box clears it, then returns focus to the list.

        One Escape does the obvious thing; a second moves on rather than
        making the user press it twice to get out of the box.
        """
        if self.filter_var.get():
            self.filter_var.set("")
            return "break"
        self.tree.focus_set()
        return "break"

    def select_all(self, _event=None):
        self.set_all_checked(True)
        return "break"

    def select_none(self, _event=None):
        self.set_all_checked(False)
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
