"""The main application window.

Owns widget state and rendering only. All download logic lives in
:mod:`musicdl.ui.downloader`, which communicates back purely through the
message queue drained by :meth:`App._poll_queue`.
"""

import os
import queue
import time
import tkinter as tk
from tkinter import filedialog, scrolledtext

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, DISABLED, READONLY

from .. import config, core, paths
from ..cleanup import cleanup_partials
from ..cookies import validate_cookie_file
from ..formatting import fmt_bytes, fmt_eta, fmt_speed, plural
from . import downloader as dl
from . import fonts
from . import theme as theme_mod
from .dialogs import RenamePrompter
from .widgets import PlaylistTable

APP_TITLE = "Music Downloader"
WINDOW_SIZE = (1180, 820)
WINDOW_MINSIZE = (960, 700)

# Grid rows of the main frame. Sections are strictly sequential so no two
# differently-shaped sections ever share a row; only ROW_TABLE expands.
ROW_HEADER = 0
ROW_URL = 1
ROW_FORMAT = 2
ROW_OUTPUT = 3
ROW_TABLE = 4
ROW_ACTIONS = 5
ROW_PROGRESS = 6
ROW_STATUS = 7
ROW_LOG = 8

# How often the Tk event loop drains worker messages.
POLL_MS = 150
# Minimum gap between overall-progress detail text updates.
DETAIL_THROTTLE_SECONDS = 0.25

PICK = "primary"
MUTED = "secondary"

# The load button accepts a playlist link or a single video link, so the
# label follows what is actually in the box rather than claiming "playlist"
# either way. Both are the same width so relabelling never resizes the button
# out from under a click.
LOAD_LABEL = "Load Playlist"
SINGLE_LABEL = "Load Video"
LOAD_TOOLTIP = "Load every song in this playlist."
SINGLE_TOOLTIP = ("This link points at one video, so only that video will "
                  "be loaded - not the playlist it came from.")


class App:
    """Main window: settings, the playlist table, progress and the log."""

    def __init__(self, root):
        self.root = root
        self.cfg = config.load()

        self.entries = []
        self.worker_alive = False
        self.stop_requested = False
        self.msg_queue = queue.Queue()
        self._closed = False
        self._expected_n = 0
        self._song_i = 0
        self._last_detail = 0.0

        self._prompts = RenamePrompter(self._enqueue)
        self._job = None

        self._build_ui()
        # Applied after the widgets exist: theme_mod needs the log widget to
        # retint it, and tk.Text is not themed by ttkbootstrap.
        self.style = theme_mod.apply(root, self._cfg_is_dark())
        self.table.apply_style_colors(self._cfg_is_dark())
        self._bind_shortcuts()
        self._refresh_cookie_status()
        self.root.after(POLL_MS, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _bind_shortcuts(self):
        """Window-level keyboard shortcuts.

        Bound on the root rather than per-widget so they work regardless of
        which control has focus. The ones the table already handles for itself
        (Space, Ctrl+A) are left to the table.
        """
        root = self.root
        for key in ("<Control-f>", "<Command-f>"):
            root.bind_all(key, self.table.focus_filter)
        for key in ("<Control-l>", "<Command-l>"):
            # Load the playlist without reaching for the mouse.
            root.bind_all(key, lambda _e: self.load_playlist())
        for key in ("<Control-d>", "<Command-d>"):
            root.bind_all(key, lambda _e: self.download_all())
        for key in ("<Control-t>", "<Command-t>"):
            root.bind_all(key, self.toggle_theme)
        root.bind_all("<F5>", lambda _e: self.check_status())
        # Escape falls through to the filter box, which decides for itself
        # whether to clear the text or hand focus back to the list.
        root.bind_all("<Escape>", self._on_escape)

    def _on_escape(self, _event=None):
        focused = self.root.focus_get()
        if focused is self.table.filter_entry:
            return None  # the filter's own binding handles it
        self.table.clear_filter()

    def _cfg_is_dark(self) -> bool:
        """Resolve the stored theme choice (which may be 'system') to dark."""
        return theme_mod.is_dark(self.cfg.get("theme", theme_mod.THEME_SYSTEM))

    # ------------------------------------------------------------------- build
    def _build_ui(self):
        """Lay the window out as a single vertical stack of sections.

        Every section owns exactly one grid row of ``frame``; only
        :data:`ROW_TABLE` is allowed to expand, so the table absorbs any extra
        window height while everything else stays at its natural size.
        """
        pad = {"padx": 8, "pady": 5}
        frame = tb.Frame(self.root, padding=(16, 14))
        frame.pack(fill=BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(ROW_TABLE, weight=1)
        self._frame = frame

        self._build_header(frame, pad)
        self._build_url_row(frame, pad)
        self._build_options_row(frame, pad)
        self._build_output_row(frame, pad)
        self.table = PlaylistTable(frame, self._enqueue, dark=self._cfg_is_dark())
        self.table.grid(row=ROW_TABLE, column=0, sticky="nsew", **pad)
        self._build_actions_row(frame, pad)
        self._build_footer(frame, pad)
        self._on_media_change()

    def _build_header(self, frame, pad):
        header = tb.Frame(frame)
        header.grid(row=ROW_HEADER, column=0, sticky="ew", **pad)
        header.columnconfigure(0, weight=1)

        title_box = tb.Frame(header)
        title_box.grid(row=0, column=0, sticky="w")
        tb.Label(title_box, text=APP_TITLE,
                 font=fonts.title()).pack(anchor="w")
        self.subtitle_var = tk.StringVar(value="Load a playlist or a single video to begin.")
        tb.Label(title_box, textvariable=self.subtitle_var,
                 bootstyle=MUTED, font=fonts.secondary()).pack(anchor="w")

        self.theme_btn = tb.Button(header, bootstyle="secondary-outline", width=4,
                                   command=self.choose_theme)
        self.theme_btn.grid(row=0, column=1, sticky="e")
        self._theme_icon = None
        self._update_theme_btn()

    def _build_url_row(self, frame, pad):
        box = tb.Frame(frame)
        box.grid(row=ROW_URL, column=0, sticky="ew", **pad)
        box.columnconfigure(1, weight=1)

        tb.Label(box, text="Link", font=fonts.caption_bold()).grid(
            row=0, column=0, sticky="w")
        self.url_var = tk.StringVar(value=self.cfg["last_url"])
        self.url_entry = tb.Entry(box, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.url_entry.bind("<Return>", lambda _e: self.load_playlist())
        # "Load Playlist" was wrong: the same field accepts a single video
        # link, and core.looks_like_single_video exists precisely to tell the
        # two apart. The label now says what the button actually does. The
        # width is fixed so a relabel cannot resize the button mid-click.
        self.load_btn = tb.Button(box, text=LOAD_LABEL, bootstyle="info",
                                  command=self.load_playlist, width=15)
        self.load_btn.grid(row=0, column=2, padx=(8, 0))
        # Keep the label honest about what is in the box, once it is parsed.
        self.url_var.trace_add("write", lambda *_: self._on_url_change())

    def _on_url_change(self):
        """Point the load button's tooltip at what the link actually is.

        The pasted link is usually a playlist, but a shared ``watch?v=`` link
        is a single video and yt-dlp would otherwise pull the whole playlist
        context. The app already handles that; this only makes the distinction
        visible before the user commits.
        """
        url = (self.url_var.get() or "").strip()
        if not url:
            self.load_btn.configure(text=LOAD_LABEL)
            self._set_load_tooltip(LOAD_TOOLTIP)
            return
        if core.looks_like_single_video(url):
            self.load_btn.configure(text=SINGLE_LABEL)
            self._set_load_tooltip(SINGLE_TOOLTIP)
        else:
            self.load_btn.configure(text=LOAD_LABEL)
            self._set_load_tooltip(LOAD_TOOLTIP)

    def _set_load_tooltip(self, text):
        """Attach a tooltip to the load button, replacing any existing one."""
        self._load_tip = tb.ToolTip(self.load_btn, text=text, bootstyle=MUTED)

    def _build_options_row(self, frame, pad):
        box = tb.Labelframe(frame, text="Format", padding=(10, 8))
        box.grid(row=ROW_FORMAT, column=0, sticky="ew", **pad)

        tb.Label(box, text="Type").grid(row=0, column=0, sticky="w")
        self.media_var = tk.StringVar(value=self.cfg["media"])
        self.rad_music = tb.Radiobutton(
            box, text="Music", bootstyle="primary-toolbutton",
            variable=self.media_var, value="Music", command=self._on_media_change)
        self.rad_music.grid(row=0, column=1, padx=(4, 0))
        self.rad_video = tb.Radiobutton(
            box, text="Video", bootstyle="primary-toolbutton",
            variable=self.media_var, value="Video", command=self._on_media_change)
        self.rad_video.grid(row=0, column=2, padx=(4, 16))

        # Audio and video have different settings, so each group is shown only
        # when it applies. A greyed-out control is still on screen and still
        # asks the user to make a choice they cannot make; hiding it is the
        # honest answer. The grid columns stay in place either way, so toggling
        # does not make the whole panel reflow.
        self.audio_label = tb.Label(box, text="Audio")
        self.audio_label.grid(row=0, column=3, sticky="w")
        self.format_var = tk.StringVar(value=self.cfg["format"])
        self.format_combo = tb.Combobox(
            box, textvariable=self.format_var, state=READONLY, width=13,
            values=list(core.AUDIO_FORMATS))
        self.format_combo.grid(row=0, column=4, padx=(4, 16))

        self.quality_label = tb.Label(box, text="Quality")
        self.quality_label.grid(row=0, column=5, sticky="w")
        self.quality_var = tk.StringVar(value=self.cfg["quality"])
        self.quality_combo = tb.Combobox(
            box, textvariable=self.quality_var, state=READONLY, width=7,
            values=core.QUALITIES)
        self.quality_combo.grid(row=0, column=6, padx=(4, 16))

        self.res_label = tb.Label(box, text="Resolution")
        self.res_label.grid(row=0, column=7, sticky="w")
        self.res_var = tk.StringVar(value=self.cfg["resolution"])
        self.res_combo = tb.Combobox(
            box, textvariable=self.res_var, state=READONLY, width=9,
            values=core.VIDEO_RESOLUTIONS)
        self.res_combo.grid(row=0, column=8, padx=(4, 0))
        # Grouped so the visibility toggle touches every widget in the group.
        self.audio_widgets = (self.audio_label, self.format_combo,
                              self.quality_label, self.quality_combo)
        self.video_widgets = (self.res_label, self.res_combo)
        # Artwork only applies to audio files; embedding a cover image in an
        # MP4 is not something the app can do.
        self.thumb_holder = None

    def _build_output_row(self, frame, pad):
        box = tb.Frame(frame)
        box.grid(row=ROW_OUTPUT, column=0, sticky="ew", **pad)
        box.columnconfigure(1, weight=1)

        tb.Label(box, text="Save to", font=fonts.caption_bold()).grid(
            row=0, column=0, sticky="w")
        self.dir_var = tk.StringVar(value=self.cfg["output_dir"])
        tb.Entry(box, textvariable=self.dir_var).grid(row=0, column=1, sticky="ew",
                                                      padx=(8, 0))
        tb.Button(box, text="Browse", bootstyle="secondary-outline",
                  command=self._browse_dir, width=9).grid(row=0, column=2, padx=(8, 0))

        opts = tb.Frame(box)
        opts.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        opts.columnconfigure(1, weight=1)

        # The artwork toggle is audio-only, so it lives in a one-column frame
        # that _on_media_change can hide wholesale. Putting it in a shared row
        # would mean hiding the neighbouring toggles with it.
        self.thumb_holder = tb.Frame(opts)
        self.thumb_holder.grid(row=0, column=0, sticky="w")
        self.thumb_var = tk.BooleanVar(value=self.cfg["thumbnail"])
        self.thumb_cb = tb.Checkbutton(
            self.thumb_holder, text="Embed artwork",
            bootstyle="success-round-toggle", variable=self.thumb_var)
        self.thumb_cb.grid(row=0, column=0, sticky="w")

        self.parallel_var = tb.BooleanVar(value=self.cfg["parallel"])
        self.parallel_cb = tb.Checkbutton(
            opts, text="Multi-download", bootstyle="success-round-toggle",
            variable=self.parallel_var, command=self._on_parallel_toggle)
        self.parallel_cb.grid(row=0, column=1, sticky="w", padx=(18, 0))

        self.jobs_var = tk.StringVar(value="1")
        self.jobs_combo = tb.Combobox(
            opts, textvariable=self.jobs_var, state=DISABLED, width=3,
            values=[str(n) for n in range(1, 7)])
        self.jobs_combo.grid(row=0, column=2, sticky="w", padx=(4, 0))
        tb.Label(opts, text="at once", bootstyle=MUTED).grid(
            row=0, column=3, sticky="w", padx=(4, 18))

        self.fix_btn = tb.Button(
            opts, text="Fix blocked", bootstyle="secondary-outline",
            command=self._choose_cookie_file, width=14)
        self.fix_btn.grid(row=0, column=4, sticky="e")
        self.cookie_var = tk.StringVar(value="")
        self.cookie_lbl = tb.Label(opts, textvariable=self.cookie_var,
                                   bootstyle=MUTED)
        self.cookie_lbl.grid(row=0, column=5, padx=(6, 0), sticky="e")
        self._on_parallel_toggle()

    def _build_actions_row(self, frame, pad):
        row = tb.Frame(frame)
        row.grid(row=ROW_ACTIONS, column=0, sticky="ew", **pad)
        row.columnconfigure(3, weight=1)

        self.download_btn = tb.Button(row, text="Download Selected",
                                      bootstyle="success", command=self.download_all)
        self.download_btn.grid(row=0, column=0)
        self.check_btn = tb.Button(row, text="Check Saved", bootstyle=PICK,
                                   command=self.check_status)
        self.check_btn.grid(row=0, column=1, padx=(6, 0))
        self.retry_btn = tb.Button(row, text="Retry Failed", bootstyle="warning",
                                   command=self.retry_failed, state=DISABLED)
        self.retry_btn.grid(row=0, column=2, padx=(6, 0))
        self.stop_btn = tb.Button(row, text="Stop", bootstyle="danger",
                                  command=self.request_stop, state=DISABLED)
        self.stop_btn.grid(row=0, column=4, sticky="e")

    def _build_footer(self, frame, pad):
        prog = tb.Frame(frame)
        prog.grid(row=ROW_PROGRESS, column=0, sticky="ew", **pad)
        prog.columnconfigure(0, weight=1)
        self.progress = tb.Progressbar(prog, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.detail_var = tk.StringVar(value="")
        tb.Label(prog, textvariable=self.detail_var, bootstyle=MUTED).grid(
            row=0, column=1, padx=(12, 0), sticky="e")

        self.status_var = tk.StringVar(value="Ready.")
        tb.Label(frame, textvariable=self.status_var,
                 font=fonts.secondary()).grid(row=ROW_STATUS, column=0, sticky="w",
                                                padx=8, pady=(6, 0))

        self.log = scrolledtext.ScrolledText(
            frame, height=7, wrap="word", relief="flat", borderwidth=0,
            state=tk.DISABLED, font=fonts.log())
        self.log.grid(row=ROW_LOG, column=0, sticky="ew", **pad)
        # tk.Text is not themed by ttkbootstrap; theme_mod.apply retints these.
        self.root._musicdl_text_widgets = (self.log,)

    # ----------------------------------------------------------------- theme
    def _update_theme_btn(self):
        """Show the current theme, and which mode 'system' resolved to."""
        choice = self.cfg.get("theme", theme_mod.THEME_SYSTEM)
        resolved = theme_mod.resolve(choice)
        glyph = {"dark": "☾", "light": "☀"}[resolved]
        try:
            icon = tb.Icon("moon" if resolved == "dark" else "sun",
                           size=18, color="fg")
            self._theme_icon = icon
            self.theme_btn.configure(image=icon, text="")
        except Exception:
            self.theme_btn.configure(text=glyph)
        label = {"system": "System", "light": "Light", "dark": "Dark"}[choice]
        suffix = f" (following system: {resolved})" if choice == "system" else ""
        try:
            tb.ToolTip(self.theme_btn, text=f"Theme: {label}{suffix}",
                       bootstyle="light" if resolved == "dark" else "dark")
        except Exception:
            pass

    def choose_theme(self):
        """Show the theme menu.

        Three states rather than a toggle, because a two-state switch cannot
        express 'follow the system' - and once you have set an explicit
        preference there is no way back to following the OS.
        """
        current = self.cfg.get("theme", theme_mod.THEME_SYSTEM)
        labels = {
            theme_mod.THEME_SYSTEM: "Match system",
            theme_mod.THEME_LIGHT: "Light",
            theme_mod.THEME_DARK: "Dark",
        }
        menu = tk.Menu(self.root, tearoff=0)
        for choice, label in labels.items():
            prefix = "●  " if choice == current else "    "
            menu.add_command(
                label=f"{prefix}{label}",
                command=lambda c=choice: self.set_theme(c),
            )
        x = self.theme_btn.winfo_rootx()
        y = self.theme_btn.winfo_rooty() + self.theme_btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def set_theme(self, choice):
        self.cfg["theme"] = choice
        self._apply_theme()
        self._save_settings()
        note = " (following system)" if choice == theme_mod.THEME_SYSTEM else ""
        self._log(f">>> Theme: {choice}{note}.")

    def _apply_theme(self):
        dark = self._cfg_is_dark()
        self.style = theme_mod.apply(self.root, dark)
        self.table.apply_style_colors(dark)
        self._update_theme_btn()
        self._bar_style("")

    def toggle_theme(self):
        """Flip between light and dark, leaving 'system' behind.

        Kept for the keyboard shortcut, which is a fast two-way action; picking
        an explicit mode is what the menu button is for.
        """
        self.set_theme(theme_mod.THEME_LIGHT if self._cfg_is_dark()
                       else theme_mod.THEME_DARK)

    # ---------------------------------------------------------------- helpers
    def _log(self, text):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def _enqueue(self, msg):
        self.msg_queue.put(msg)

    def _cfg_jobs(self) -> int:
        try:
            return max(1, min(int(self.jobs_var.get() or 1), 6))
        except (TypeError, ValueError):
            return 1

    def _restore_jobs(self) -> int:
        try:
            return max(2, min(int(self.cfg.get("parallel_jobs", 3) or 3), 6))
        except (TypeError, ValueError):
            return 3

    def _browse_dir(self):
        chosen = filedialog.askdirectory(
            initialdir=self.dir_var.get() or paths.home_dir())
        if chosen:
            self.dir_var.set(chosen)

    def _choose_cookie_file(self):
        initial = core._cookies_txt_path()
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Choose your signed-in cookies.txt",
            initialdir=os.path.dirname(initial),
            initialfile=os.path.basename(initial),
            filetypes=[("cookies.txt", "cookies.txt"),
                       ("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        ok, count, youtube, msg = validate_cookie_file(path)
        if not ok:
            self._log(f">>> Fix blocked: rejected '{os.path.basename(path)}' - {msg}.")
            return
        self.cfg["cookie_path"] = path
        self._save_settings()
        self._refresh_cookie_status()
        self._log(f">>> Fix blocked: using cookies file "
                  f"'{os.path.basename(path)}' ({count} cookies, "
                  f"{youtube} for YouTube/Google).")

    def _refresh_cookie_status(self):
        path = self.cfg.get("cookie_path", "")
        ok, count, _yt, _msg = validate_cookie_file(path) if path else (False, 0, 0, "")
        if ok:
            self.cookie_lbl.configure(bootstyle="success")
            self.cookie_var.set(f"cookies: {os.path.basename(path)} ({count})")
        else:
            self.cookie_lbl.configure(bootstyle=MUTED)
            self.cookie_var.set("no cookies file")

    def _save_settings(self):
        self.cfg.update({
            "last_url": self.url_var.get().strip(),
            "output_dir": self.dir_var.get().strip(),
            "format": self.format_var.get(),
            "quality": self.quality_var.get(),
            "media": self.media_var.get(),
            "resolution": self.res_var.get(),
            "thumbnail": self.thumb_var.get(),
            "theme": self.cfg.get("theme", theme_mod.THEME_SYSTEM),
            "parallel": self.parallel_var.get(),
            "parallel_jobs": self._restore_jobs() if self.parallel_var.get() else 3,
        })
        config.save(self.cfg)

    def _on_media_change(self):
        """Show only the settings that apply to the chosen media type.

        Audio and video have disjoint settings. Leaving the other set on
        screen but disabled was worse than either extreme: it took up the room
        it was going to take anyway, and asked for a decision the user could
        not make. Hiding is reversible and keeps the panel honest about what
        is actually going to be used.
        """
        is_video = self.media_var.get() == "Video"
        for group, visible in ((self.audio_widgets, not is_video),
                               (self.video_widgets, is_video)):
            for w in group:
                if visible:
                    w.grid()
                else:
                    w.grid_remove()
        # Cover art is an audio-only feature, so the toggle follows the type.
        if self.thumb_holder is not None:
            if is_video:
                self.thumb_holder.grid_remove()
            else:
                self.thumb_holder.grid()

    def _on_parallel_toggle(self):
        on = bool(self.parallel_var.get())
        if on and self._cfg_jobs() < 2:
            self.jobs_var.set(str(self._restore_jobs()))
        elif not on and self._cfg_jobs() >= 2:
            self.jobs_var.set("1")
        self.jobs_combo.configure(state=READONLY if on else DISABLED)

    def _set_busy(self, busy):
        for btn in (self.load_btn, self.download_btn, self.check_btn,
                    self.rad_music, self.rad_video, self.thumb_cb,
                    self.parallel_cb, self.fix_btn):
            btn.configure(state=DISABLED if busy else "normal")
        self.jobs_combo.configure(
            state=DISABLED if busy else (READONLY if self.parallel_var.get() else DISABLED))
        self.stop_btn.configure(state="normal" if busy else DISABLED)
        has_failures = bool(self.table.failed)
        self.retry_btn.configure(
            state=DISABLED if busy else ("normal" if has_failures else DISABLED))
        if not busy:
            self._on_media_change()

    def _bar_style(self, name):
        try:
            self.progress.configure(bootstyle=name or "default")
        except Exception:
            pass

    # ------------------------------------------------------------- validation
    def _check_prereqs(self) -> bool:
        if not core.ffmpeg_available():
            tb.Messagebox.show_error(
                "ffmpeg is required to convert audio and merge video.\n\n"
                "Install it (Windows: 'winget install Gyan.FFmpeg', macOS: "
                "'brew install ffmpeg', Debian/Ubuntu: 'sudo apt install ffmpeg'), "
                "then restart this app.",
                title="ffmpeg not found",
            )
            return False
        if not self.url_var.get().strip():
            tb.Messagebox.show_warning(
                "Please paste a YouTube playlist or video link first.",
                title="Missing link")
            return False
        return True

    def _snapshot(self) -> dict:
        """Copy UI settings. Must be read on the Tk main thread only."""
        cookie_path = self.cfg.get("cookie_path", "") or ""
        if cookie_path and not validate_cookie_file(cookie_path)[0]:
            cookie_path = ""
        for e in self.entries:
            self.table.mark_default(e["id"])
        return {
            "url": self.url_var.get().strip(),
            "dir": paths.resolve_user_path(self.dir_var.get(), paths.home_dir()),
            "media": self.media_var.get(),
            "format": self.format_var.get(),
            "quality": self.quality_var.get(),
            "resolution": self.res_var.get(),
            "thumbnail": bool(self.thumb_var.get()),
            "cookie_path": cookie_path,
            "selected": self.table.checked_ids(),
            "parallel_jobs": self._cfg_jobs() if self.parallel_var.get() else 1,
        }

    # ---------------------------------------------------------------- actions
    def load_playlist(self):
        if self._check_prereqs():
            self._save_settings()
            self._start("load", url=self.url_var.get().strip())

    def download_all(self):
        if self._check_prereqs():
            self._save_settings()
            self._start("download")

    def retry_failed(self):
        if self.table.failed and self._check_prereqs():
            self._save_settings()
            self._start("retry", ids=list(self.table.failed))

    def check_status(self):
        if self._check_prereqs():
            self._save_settings()
            self._start("check")

    def request_stop(self):
        self.stop_requested = True
        core.abort_ffmpeg()
        self._log(">>> Stop requested. Aborting current song...")

    def _on_row_action(self, vid, action):
        if action == "retry" and self._check_prereqs():
            self._save_settings()
            self._start("retry", ids=[vid])

    def _start(self, action, url=None, ids=None):
        if self.worker_alive:
            self._log(">>> Still busy - wait for the current job to finish.")
            return
        self.worker_alive = True
        self.stop_requested = False
        self._set_busy(True)
        self._job = dl.DownloadJob(
            action=action,
            snapshot=self._snapshot(),
            enqueue=self._enqueue,
            ask_rename=self._prompts.ask,
            stop_requested=lambda: self.stop_requested,
            url=url,
            ids=ids,
        )
        self._job.entries = self.entries
        self._job.failed = self.table.failed
        self._job.unavailable = self.table.unavailable
        self._job.start()

    # ------------------------------------------------------------ queue pump
    def _poll_queue(self):
        try:
            while True:
                self._handle(self.msg_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self._poll_queue)

    def _handle(self, msg):
        kind = msg[0]
        handler = self._HANDLERS.get(kind)
        if handler:
            handler(self, *msg[1:])

    def _on_log(self, text):
        self._log(text)

    def _on_status(self, text):
        self.status_var.set(text)

    def _on_progress(self, status, downloaded, total, _fname, speed, eta):
        if not total:
            return
        n = self._expected_n or 1
        frac = downloaded / total
        overall = ((self._song_i - 1) + frac) / n * 100
        self.progress["value"] = min(overall, 100.0)
        now = time.monotonic()
        if now - self._last_detail < DETAIL_THROTTLE_SECONDS:
            return
        self._last_detail = now
        text = (f"Song {self._song_i}/{n} · "
                f"{fonts.progress_text(int(frac * 100), fmt_speed(speed), fmt_eta(eta))} · "
                f"{fmt_bytes(downloaded)} of {fmt_bytes(total)}")
        self.detail_var.set(text)

    def _on_song_index(self, i, _total):
        self._song_i = i

    def _on_tick(self, done, active, total):
        self.progress.configure(maximum=total, value=done)
        self.detail_var.set(fonts.tick_text(done, active, total))

    def _on_row_status(self, vid, text):
        self.table.set_status(vid, text)

    def _on_row_progress(self, vid, downloaded, total, speed):
        if not total:
            return
        self.table.set_status(
            vid, f"Downloading {fonts.progress_text(int(downloaded / total * 100), fmt_speed(speed))}")

    def _on_set_expected(self, n):
        self._expected_n = n or 1
        self.progress.configure(maximum=self._expected_n, value=0)
        self._bar_style("info-striped")

    def _on_reset_progress(self):
        self.progress["value"] = 0
        self.detail_var.set("")

    def _on_ask_rename(self, entry):
        self._prompts.show(self.root, entry)

    def _on_setup_tree(self, entries):
        self.entries = entries
        self.table.populate(entries)
        self.subtitle_var.set(f"{plural(len(entries), 'song')} loaded")

    def _on_mark_statuses(self, existing):
        self.table.mark_statuses(existing)

    def _on_refresh_statuses(self, existing):
        self.table.mark_statuses(existing, only_if_clean=True)

    def _on_row_thumb(self, vid, img):
        self.table.set_thumbnail(vid, img)

    def _on_finished(self, text, summary):
        self.worker_alive = False
        self.stop_requested = False
        self._set_busy(False)
        self.status_var.set(text)
        self.detail_var.set("")
        self._bar_style("danger" if self.table.failed else "success")
        if summary:
            tb.Messagebox.show_info(summary, title="Finished")

    _HANDLERS = {
        dl.LOG: _on_log,
        dl.STATUS: _on_status,
        dl.PROGRESS: _on_progress,
        dl.SONG_INDEX: _on_song_index,
        dl.TICK: _on_tick,
        dl.ROW_STATUS: _on_row_status,
        dl.ROW_PROGRESS: _on_row_progress,
        dl.SET_EXPECTED: _on_set_expected,
        dl.RESET_PROGRESS: _on_reset_progress,
        dl.ASK_RENAME: _on_ask_rename,
        dl.SETUP_TREE: _on_setup_tree,
        dl.MARK_STATUSES: _on_mark_statuses,
        dl.REFRESH_STATUSES: _on_refresh_statuses,
        dl.ROW_THUMB: _on_row_thumb,
        dl.FINISHED: _on_finished,
        "row_action": lambda self, vid, action: self._on_row_action(vid, action),
    }

    # ------------------------------------------------------------------ close
    def _on_close(self):
        if not self._closed:
            self._closed = True
            self.stop_requested = True
            core.abort_ffmpeg()
            self.table._loader.shutdown()
            self._save_settings()
            target = self.dir_var.get().strip()
            if target and os.path.isdir(os.path.expanduser(target)):
                cleanup_partials(os.path.expanduser(target))
        self.root.destroy()


def run() -> int:
    """Create the window and enter the Tk event loop."""
    cfg = config.load()
    root = tb.Window(
        title=APP_TITLE,
        themename=theme_mod.ttk_theme(
            theme_mod.is_dark(cfg.get("theme", theme_mod.THEME_SYSTEM))),
        size=WINDOW_SIZE,
        minsize=WINDOW_MINSIZE,
    )
    icon = paths.resource_path("icon.ico")
    if os.path.isfile(icon):
        try:
            root.iconbitmap(icon)
        except Exception:
            pass
    App(root)
    root.mainloop()
    return 0
