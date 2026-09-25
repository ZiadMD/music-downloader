"""YouTube playlist downloader - modern GUI.

Features:
  - Load a YouTube playlist OR a single video/music link
  - Inline thumbnails shown next to each song
  - Tick the songs you want; download only the ticked ones
  - Per-song check: Downloaded / Missing / Failed statuses (manual "Check Status",
    or refreshed automatically during a download run)
  - Download songs as Music (MP3/M4A/FLAC/WAV/OGG/OPUS) or Video (MP4)
  - Same-name files: offers Skip / Rename / Cancel
  - 'Fix blocked videos' (browser cookies) for YouTube bot-protected songs
  - Retry failed songs (button + right-click)
  - Live search, live progress, dark / light theme toggle
"""

import io
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import urllib.request
import concurrent.futures
from tkinter import filedialog, scrolledtext

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, DISABLED, EW, READONLY
from PIL import Image, ImageDraw, ImageTk

import core

def _config_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_FILE = os.path.join(_config_dir(), "config.json")

DEFAULT_CONFIG = {
    "last_url": "",
    "output_dir": os.path.join(os.path.expanduser("~"), "Music", "Playlists"),
    "format": "MP3",
    "quality": "192",
    "media": "Music",
    "resolution": "Best",
    "thumbnail": True,
    "theme": "dark",
    "cookie_path": "",
    "parallel": False,
    "parallel_jobs": 3,
}


def _resource_path(name):
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except OSError:
        pass


def system_theme():
    """Detect Windows light/dark mode and return a matching ttkbootstrap theme."""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "litera" if val else "darkly"
    except Exception:
        return "litera"


class App:
    def __init__(self, root):
        self.root = root
        self.style = tb.Style()
        self.cfg = load_config()

        self.entries = []
        self.iid_by_id = {}
        self.vid_by_iid = {}
        self.checked = {}                # vid -> ticked (selected for download)
        self.row_order = []              # tree iids in insertion order
        self.status_by_vid = {}            # vid -> status text (kept across re-filter)
        self.missing = []
        self.worker_alive = False
        self.stop_requested = False
        self.msg_queue = queue.Queue()

        self.failed = {}                   # vid -> failure reason
        self.unavailable = {}              # vid -> reason (video removed/private)
        self.row_thumbs = {}               # vid -> (iid, PhotoImage) cache
        self._thumb_jobs = queue.Queue()
        self._thumb_workers = []
        self._closed = False

        self.is_dark = self.cfg.get("theme", "dark") != "light"
        self._ask_events = {}              # vid -> threading.Event (rename prompt)
        self._ask_answers = {}             # vid -> "skip"/"rename"/"cancel"
        self._expected_n = 0
        self._song_i = 0
        self._last_detail = time.monotonic()

        self._build_ui()
        self._apply_theme(self.is_dark)

        root.after(150, self._poll_queue)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------- UI
    def _build_ui(self):
        root = self.root
        pad = {"padx": 6, "pady": 4}

        frame = tb.Frame(root, padding=14)
        frame.pack(fill=BOTH, expand=True)
        frame.columnconfigure(0, weight=1)

        # 0) Header: title (left) + theme toggle (right, website-style)
        header = tb.Frame(frame)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", **pad)
        header.columnconfigure(0, weight=1)
        title_lbl = tb.Label(
            header, text="YouTube Playlist Downloader",
            font=("TkDefaultFont", 14, "bold"))
        title_lbl.grid(row=0, column=0, sticky="w")
        self.theme_btn = tb.Button(header, bootstyle="secondary", command=self.toggle_theme,
                                   width=3)
        self.theme_btn.grid(row=0, column=1, sticky="e")
        self._theme_icon = None
        tb.Separator(header).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._update_theme_btn()

        # 1) Playlist URL
        tb.Label(frame, text="Playlist or video link:").grid(row=1, column=0, sticky="w", **pad)
        url_row = tb.Frame(frame)
        url_row.grid(row=1, column=1, sticky="ew", **pad)
        url_row.columnconfigure(0, weight=1)
        self.url_var = tk.StringVar(value=self.cfg["last_url"])
        self.url_entry = tb.Entry(url_row, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.load_btn = tb.Button(url_row, text="Load Playlist", bootstyle="info",
                                  command=self.load_playlist, width=14)
        self.load_btn.grid(row=0, column=1, padx=(6, 0))

        # 2) Media type + format + quality + resolution
        opt = tb.Frame(frame)
        opt.grid(row=2, column=0, columnspan=2, sticky="ew", **pad)

        self.media_var = tk.StringVar(value=self.cfg["media"])
        tb.Label(opt, text="Download:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.rad_music = tb.Radiobutton(
            opt, text=" Music ", bootstyle="primary-toolbutton",
            variable=self.media_var, value="Music", command=self._on_media_change)
        self.rad_music.grid(row=0, column=1)
        self.rad_video = tb.Radiobutton(
            opt, text=" Video ", bootstyle="primary-toolbutton",
            variable=self.media_var, value="Video", command=self._on_media_change)
        self.rad_video.grid(row=0, column=2, padx=(0, 16))

        tb.Label(opt, text="Format:").grid(row=0, column=3, sticky="w")
        self.format_var = tk.StringVar(value=self.cfg["format"])
        self.format_combo = tb.Combobox(
            opt, textvariable=self.format_var, state=READONLY, width=12,
            values=list(core.AUDIO_FORMATS.keys()))
        self.format_combo.grid(row=0, column=4, sticky="w", padx=(2, 14))

        tb.Label(opt, text="Quality:").grid(row=0, column=5, sticky="w")
        self.quality_var = tk.StringVar(value=self.cfg["quality"])
        self.quality_combo = tb.Combobox(
            opt, textvariable=self.quality_var, state=READONLY, width=6,
            values=core.QUALITIES)
        self.quality_combo.grid(row=0, column=6, sticky="w", padx=(2, 14))

        tb.Label(opt, text="Res:").grid(row=0, column=7, sticky="w")
        self.res_var = tk.StringVar(value=self.cfg["resolution"])
        self.res_combo = tb.Combobox(
            opt, textvariable=self.res_var, state=DISABLED, width=8,
            values=core.VIDEO_RESOLUTIONS)
        self.res_combo.grid(row=0, column=8, sticky="w", padx=(2, 0))

        self._on_media_change()

        # 3) Output folder + Fix blocked + toggles
        dir_row = tb.Frame(frame)
        dir_row.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)
        dir_row.columnconfigure(1, weight=1)
        tb.Label(dir_row, text="Save to:").grid(row=0, column=0, sticky="w")
        self.dir_var = tk.StringVar(value=self.cfg["output_dir"])
        tb.Entry(dir_row, textvariable=self.dir_var).grid(row=0, column=1, sticky="ew",
                                                          padx=(6, 0))
        tb.Button(dir_row, text="Browse...", bootstyle="secondary",
                  command=self._browse_dir).grid(row=0, column=2, padx=(6, 0))

        self.thumb_var = tk.BooleanVar(value=self.cfg["thumbnail"])
        self.thumb_cb = tb.Checkbutton(
            dir_row, text="Thumbnail", bootstyle="success-round-toggle",
            variable=self.thumb_var)
        self.thumb_cb.grid(row=0, column=3, padx=(16, 0))

        self.fix_btn = tb.Button(
            dir_row, text="Fix blocked (cookies.txt)", bootstyle="secondary",
            command=self._choose_cookie_file, width=22)
        self.fix_btn.grid(row=0, column=4, padx=(16, 0))
        self.cookie_status_var = tk.StringVar(value="")
        self.cookie_lbl = tb.Label(dir_row, textvariable=self.cookie_status_var,
                                   bootstyle="secondary")
        self.cookie_lbl.grid(row=0, column=5, padx=(8, 0))
        self._refresh_cookie_status()

        # 4) Actions
        acts = tb.Frame(frame)
        acts.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)
        self.download_btn = tb.Button(acts, text="Download Checked", bootstyle="success",
                                      command=self.download_all)
        self.download_btn.grid(row=0, column=0, **pad)
        self.check_btn = tb.Button(acts, text="Check Status",
                                   bootstyle="primary", command=self.check_status)
        self.check_btn.grid(row=0, column=1, **pad)
        self.stop_btn = tb.Button(acts, text="Stop", bootstyle="danger",
                                  command=self.request_stop, state=DISABLED)
        self.stop_btn.grid(row=0, column=2, **pad)
        self.retry_btn = tb.Button(acts, text="Retry Failed", bootstyle="warning",
                                   command=self.retry_failed, state=DISABLED)
        self.retry_btn.grid(row=0, column=3, **pad)

        self.parallel_var = tb.BooleanVar(value=self.cfg.get("parallel", False))
        self.parallel_cb = tb.Checkbutton(
            acts, text="Multi-download", bootstyle="success-round-toggle",
            variable=self.parallel_var, command=self._on_parallel_toggle)
        self.parallel_cb.grid(row=0, column=4, padx=(14, 0))
        self._restore_jobs = max(2, min(int(self.cfg.get("parallel_jobs", 3) or 3), 6))
        self.concurrency_var = tk.StringVar(
            value=str(self._restore_jobs if self.parallel_var.get() else 1))
        self.concurrency_combo = tb.Combobox(
            acts, textvariable=self.concurrency_var, state=READONLY, width=3,
            values=[str(x) for x in range(1, 7)])
        self.concurrency_combo.grid(row=0, column=5, padx=(4, 0))
        self._on_parallel_toggle()

        # 5) Content: song table (full width)
        content = tb.Frame(frame)
        content.grid(row=5, column=0, columnspan=2, sticky="nsew", **pad)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)

        table_frame = tb.Frame(content)
        table_frame.grid(row=0, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(1, weight=1)

        filter_row = tb.Frame(table_frame)
        filter_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        tb.Label(filter_row, text="Search:").pack(side="left")
        self.filter_var = tk.StringVar(value="")
        self.filter_var.trace_add("write", lambda *a: self._apply_filter())
        tb.Entry(filter_row, textvariable=self.filter_var).pack(
            side="left", fill="x", expand=True, padx=(4, 0))
        tb.Button(filter_row, text="Tick all", bootstyle="secondary", width=8,
                  command=lambda: self._check_all(True)).pack(side="left", padx=(4, 0))
        tb.Button(filter_row, text="Untick all", bootstyle="secondary", width=9,
                  command=lambda: self._check_all(False)).pack(side="left", padx=(4, 0))

        self.style.configure("Treeview", rowheight=66)
        self.tree = tb.Treeview(
            table_frame, columns=("pick", "title", "artist", "status"),
            show="tree headings", height=14)
        self.tree.heading("#0", text="")
        self.tree.heading("pick", text="\u2713")
        self.tree.heading("title", text="Song")
        self.tree.heading("artist", text="Artist")
        self.tree.heading("status", text="Status")
        self.tree.column("#0", width=100, anchor="center", stretch=False)
        self.tree.column("pick", width=34, anchor="center", stretch=False)
        self.tree.column("title", width=360, anchor="w")
        self.tree.column("artist", width=170, anchor="w")
        self.tree.column("status", width=130, anchor="center")
        self.tree.grid(row=1, column=0, sticky="nsew")

        vsb = tb.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vsb.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<space>", self._on_space_toggle)

        # 6) Progress + status
        prog_row = tb.Frame(frame)
        prog_row.grid(row=6, column=0, columnspan=2, sticky="ew", **pad)
        prog_row.columnconfigure(0, weight=1)
        self.progress = tb.Progressbar(prog_row, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.detail_var = tk.StringVar(value="")
        tb.Label(prog_row, textvariable=self.detail_var).grid(
            row=0, column=1, padx=(12, 0), sticky="e")
        self.status_var = tk.StringVar(value="Ready.")
        tb.Label(frame, textvariable=self.status_var).grid(
            row=7, column=0, columnspan=2, sticky="w", **pad)

        # 7) Log
        self.log = scrolledtext.ScrolledText(frame, height=7, wrap="word",
                                             relief="flat", borderwidth=0, state=tk.DISABLED)
        self.log.grid(row=8, column=0, columnspan=2, sticky="ew", **pad)

    def _configure_tags(self):
        colors = self.style.colors
        self.tree.tag_configure("ok", foreground=getattr(colors, "success", "#198754"))
        self.tree.tag_configure("missing", foreground=getattr(colors, "danger", "#dc3545"))
        self.tree.tag_configure("busy", foreground=getattr(colors, "info", "#0d6efd"))

    def _apply_theme(self, dark):
        self.is_dark = dark
        self.style.theme_use("darkly" if dark else "litera")
        self.cfg["theme"] = "dark" if dark else "light"
        colors = self.style.colors
        try:
            self.root.configure(bg=getattr(colors, "bg", None) or self.style.cget("bg"))
        except Exception:
            pass
        self._configure_tags()
        bg = getattr(colors, "bg", None) or self.style.cget("bg")
        fg = getattr(colors, "fg", None) or "#000000"
        try:
            self.log.config(bg=bg, fg=fg, insertbackground=fg)
            self.url_entry.configure(style="TEntry")
        except Exception:
            pass
        self._update_theme_btn()
        self._bar_style("")
        self._save_settings()

    def _update_theme_btn(self):
        try:
            icon_name = "sun" if self.is_dark else "moon"
            try:
                self._theme_icon = tb.Icon(icon_name, size=18, color="fg")
                self.theme_btn.configure(image=self._theme_icon, text="")
            except Exception:
                self.theme_btn.configure(
                    image="", text="\u2600" if self.is_dark else "\u263d")
            target = "light" if self.is_dark else "dark"
            try:
                tb.ToolTip(self.theme_btn, text=f"Switch to {target} mode",
                           bootstyle="dark" if not self.is_dark else "light")
            except Exception:
                pass
        except Exception:
            pass

    def toggle_theme(self):
        self._apply_theme(not self.is_dark)
        self._log(">>> Switched to " + ("dark" if self.is_dark else "light") + " theme.")

    # ------------------------------------------------------------- helpers
    def _browse_dir(self):
        chosen = filedialog.askdirectory(
            initialdir=self.dir_var.get() or os.path.expanduser("~"))
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
        ok, count, youtube, msg = core.validate_cookie_file(path)
        if ok:
            self.cfg["cookie_path"] = path
            self._save_settings()
            self._refresh_cookie_status()
            self._log(f">>> Fix blocked: using cookies file "
                      f"'{os.path.basename(path)}' ({count} cookies, "
                      f"{youtube} for YouTube/Google).")
        else:
            self._log(f">>> Fix blocked: rejected '{path}' - {msg}.")

    def _refresh_cookie_status(self):
        path = self.cfg.get("cookie_path", "")
        if path:
            ok, count, _youtube, _msg = core.validate_cookie_file(path)
            if ok:
                self.cookie_lbl.configure(bootstyle="success")
                self.cookie_status_var.set(
                    f"cookies: {os.path.basename(path)} ({count})")
                return
        self.cookie_lbl.configure(bootstyle="secondary")
        self.cookie_status_var.set("no cookies file")

    def _enqueue(self, msg):
        self.msg_queue.put(msg)

    def _poll_queue(self):
        try:
            while True:
                self._handle_msg(self.msg_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)

    def _handle_msg(self, msg):
        kind = msg[0]
        if kind == "log":
            self._log(msg[1])
        elif kind == "status":
            self.status_var.set(msg[1])
        elif kind == "progress":
            status, downloaded, total, _fname, speed, eta = msg[1:]
            if total:
                n = self._expected_n or 1
                frac = downloaded / total
                overall = ((self._song_i - 1) + frac) / n * 100
                self.progress["value"] = min(overall, 100.0)
                now = time.monotonic()
                if now - self._last_detail >= 0.25:
                    self._last_detail = now
                    text = (f"Song {self._song_i}/{n} · {int(frac * 100)}%"
                            f" · {self._fmt(downloaded)} of {self._fmt(total)}")
                    if speed:
                        text += f" · {self._fmt_speed(speed)}"
                    if eta:
                        text += f" · ETA {self._fmt_eta(eta)}"
                    self.detail_var.set(text)
        elif kind == "song_index":
            self._song_i = msg[1]
        elif kind == "tick":
            done, active, total = msg[1:]
            self.progress["value"] = done
            self.detail_var.set(
                f"{done}/{total} done · {active} downloading now")
        elif kind == "row_status":
            vid, text = msg[1:]
            self._set_row_status(vid, text)
        elif kind == "row_progress":
            vid, downloaded, total, speed = msg[1:]
            if total:
                pct = int(downloaded / total * 100)
                text = f"Downloading {pct}%"
                if speed:
                    text += f" · {self._fmt_speed(speed)}"
                self._set_row_status(vid, text)
        elif kind == "set_expected":
            self._expected_n = msg[1] or 1
            self.progress.configure(maximum=self._expected_n, value=0)
            self._bar_style("info-striped")
        elif kind == "reset_progress":
            self.progress["value"] = 0
            self.detail_var.set("")
        elif kind == "ask_rename":
            self._show_rename_dialog(msg[1])
        elif kind == "setup_tree":
            self._populate_tree(msg[1])
        elif kind == "mark_statuses":
            existing = msg[1]
            for e in self.entries:
                if core.is_saved_match(existing, e["title"]):
                    self._set_row_status(e["id"], "Downloaded", keep="ok")
                else:
                    self._set_row_status(e["id"], "Missing", keep="missing")
        elif kind == "refresh_statuses":
            existing = msg[1]
            for e in self.entries:
                vid = e["id"]
                cur = self.status_by_vid.get(vid, "")
                if vid in self.failed or vid in self.unavailable or "skipped" in cur.lower():
                    continue
                if core.is_saved_match(existing, e["title"]):
                    self._set_row_status(vid, "Downloaded", keep="ok")
                else:
                    self._set_row_status(vid, "Missing", keep="missing")
        elif kind == "row_thumb":
            vid, img = msg[1:]
            iid = self.iid_by_id.get(vid)
            if img is not None and iid:
                try:
                    photo = ImageTk.PhotoImage(img)
                except Exception:
                    return
                self.row_thumbs[vid] = photo
                self.tree.item(iid, image=photo)
        elif kind == "finished":
            self.worker_alive = False
            self.stop_requested = False
            self.stop_btn.config(state=DISABLED)
            self._set_busy(False)
            self.status_var.set(msg[1])
            self.detail_var.set("")
            self._bar_style("danger" if self.failed else "success")
            if msg[2]:
                tb.Messagebox.show_info(msg[2], title="Finished")

    def _bar_style(self, name):
        try:
            self.progress.configure(bootstyle=name or "default")
        except Exception:
            try:
                self.progress.configure(style="success-striped"
                                        if name == "info-striped" else name)
            except Exception:
                pass

    @staticmethod
    def _fmt(n):
        try:
            n = float(n or 0)
        except (TypeError, ValueError):
            return "0 B"
        if n >= 1 << 20:
            return f"{n / (1 << 20):.1f} MB"
        if n >= 1 << 10:
            return f"{n / (1 << 10):.0f} KB"
        return f"{int(n)} B"

    @staticmethod
    def _fmt_speed(bps):
        try:
            bps = float(bps or 0)
        except (TypeError, ValueError):
            return "--"
        if bps <= 0:
            return "--"
        if bps >= 1 << 30:
            return f"{bps / (1 << 30):.1f} GiB/s"
        if bps >= 1 << 20:
            return f"{bps / (1 << 20):.1f} MiB/s"
        if bps >= 1 << 10:
            return f"{bps / (1 << 10):.0f} KiB/s"
        return f"{bps:.0f} B/s"

    @staticmethod
    def _fmt_eta(eta):
        try:
            eta = int(eta or 0)
        except (TypeError, ValueError):
            return "--"
        if eta <= 0:
            return "--"
        m, s = divmod(eta, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _set_row_status(self, vid, text, keep=None):
        iid = self.iid_by_id.get(vid)
        if not iid:
            return
        dot = "\u25cf "
        display = text if text.startswith(dot) else dot + text
        self.status_by_vid[vid] = display
        self.tree.set(iid, "status", display)
        tag = keep or self._status_tag(text)
        self.tree.item(iid, tags=(tag,) if tag else "")

    def _status_tag(self, text):
        if ("unavailable" in text.lower() or "missing" in text.lower()
                or "failed" in text.lower()):
            return "missing"
        if "download" in text.lower() and "ed" not in text.lower():
            return "busy"
        if "downloaded" in text.lower() or "skipped" in text.lower():
            return "ok"
        if "pending" in text.lower():
            return "busy"
        return ""

    @staticmethod
    def _is_unavailable(reason):
        """True when YouTube says the video is permanently gone
        (removed / private / deleted) rather than a network or bot-check glitch."""
        rl = (reason or "").lower()
        markers = (
            "video unavailable", "private video", "removed", "no longer available",
            "has been deleted", "not available", "is unavailable",
        )
        return any(m in rl for m in markers)

    def _record_failure(self, vid, title, reason, cookie_used):
        """Classify a download failure: permanently-removed videos get an
        'Unavailable' status (not retried), everything else becomes a Failed."""
        if self._is_unavailable(reason):
            self.unavailable[vid] = reason
            self.failed.pop(vid, None)
            Q = self._enqueue
            Q(("log", f"UNAVAILABLE: {title} - removed from YouTube "
                      f"({reason})"))
            Q(("row_status", vid, "Unavailable"))
            return
        self.failed[vid] = reason
        rl = reason.lower()
        hint = ""
        if any(k in rl for k in ("sign in", "age", "confirm", "premium", "auth")):
            if cookie_used:
                hint = (". cookies were used but YouTube still refused "
                        "this one - confirm it actually plays in your "
                        "signed-in browser, then try a fresh cookies "
                        "export")
            else:
                hint = (". It plays in your browser? Click 'Fix blocked "
                        "(cookies.txt)', choose your signed-in cookies.txt, "
                        "then press Retry Failed")
        self._enqueue(("log", f"FAILED: {title} - {reason}{hint}"))
        self._enqueue(("row_status", vid, "Failed"))

    def _log(self, text):
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def _set_busy(self, busy):
        state = DISABLED if busy else "normal"
        self.load_btn.config(state=state)
        self.download_btn.config(state=state)
        self.check_btn.config(state=state)
        self.rad_music.config(state=state)
        self.rad_video.config(state=state)
        self.thumb_cb.config(state=state)
        self.parallel_cb.config(state=state)
        self.concurrency_combo.config(
            state=DISABLED if busy else
            ("readonly" if self.parallel_var.get() else "disabled"))
        self.stop_btn.config(state="normal" if busy else DISABLED)
        self.retry_btn.config(state=DISABLED if busy else ("normal" if self.failed else DISABLED))
        if not busy:
            self._on_media_change()

    def _on_parallel_toggle(self):
        on = bool(self.parallel_var.get())
        if on:
            self.concurrency_combo.config(state="readonly")
            if self._parallel_jobs() < 2:
                self.concurrency_var.set(str(self._restore_jobs))
        else:
            self.concurrency_combo.config(state="disabled")
            if self._parallel_jobs() >= 2:
                self._restore_jobs = self._parallel_jobs()
            self.concurrency_var.set("1")

    def _parallel_jobs(self):
        try:
            jobs = int(self.concurrency_var.get() or 1)
        except (TypeError, ValueError):
            jobs = 1
        return max(1, min(jobs, 6))

    def _save_settings(self):
        self.cfg.update(
            {
                "last_url": self.url_var.get().strip(),
                "output_dir": self.dir_var.get().strip(),
                "format": self.format_var.get(),
                "quality": self.quality_var.get(),
                "media": self.media_var.get(),
                "resolution": self.res_var.get(),
                "thumbnail": self.thumb_var.get(),
                "theme": "dark" if self.is_dark else "light",
                "parallel": self._parallel_jobs() >= 2,
                "parallel_jobs": self._parallel_jobs(),
            }
        )
        save_config(self.cfg)

    def request_stop(self):
        self.stop_requested = True
        core.abort_ffmpeg()
        self._log(">>> Stop requested. Aborting current song...")

    def _check_prereqs(self):
        if not core.ffmpeg_available():
            tb.Messagebox.show_error(
                "ffmpeg is required to convert audio / merge video.\n\n"
                "Install it (e.g. 'winget install Gyan.FFmpeg'), then restart this app.",
                title="ffmpeg not found",
            )
            return False
        if not self.url_var.get().strip():
            tb.Messagebox.show_warning(
                "Please paste a YouTube playlist or video link first.",
                title="Missing link")
            return False
        return True

    def _target_dir(self):
        base = self.dir_var.get().strip() or os.path.expanduser("~")
        os.makedirs(base, exist_ok=True)
        return base

    def _quality_value(self):
        q = self.quality_var.get()
        return q if q and q != "Best" else "192"

    def _on_media_change(self):
        is_video = self.media_var.get() == "Video"
        self.format_combo.config(state=DISABLED if is_video else READONLY)
        self.quality_combo.config(state=DISABLED if is_video else READONLY)
        self.res_combo.config(state=READONLY if is_video else DISABLED)

    # ------------------------------------------------------------- checkboxes
    def _toggle_checked(self, vid):
        self.checked[vid] = not self.checked.get(vid, True)
        iid = self.iid_by_id.get(vid)
        if iid:
            self.tree.set(iid, "pick", "\u2713" if self.checked[vid] else "")

    def _check_all(self, on):
        for vid in self.checked:
            self.checked[vid] = bool(on)
        mark = "\u2713" if on else ""
        for iid, vid in self.vid_by_iid.items():
            self.tree.set(iid, "pick", mark)

    def _checked_ids(self):
        return [vid for vid, on in self.checked.items() if on]

    def _on_tree_click(self, event):
        if self.tree.identify_column(event.x) == "#1":
            iid = self.tree.identify_row(event.y)
            vid = self.vid_by_iid.get(iid)
            if vid:
                self._toggle_checked(vid)
                return "break"
        return None

    def _on_space_toggle(self, _event=None):
        for iid in self.tree.selection():
            vid = self.vid_by_iid.get(iid)
            if vid:
                self._toggle_checked(vid)
        return "break"

    # ------------------------------------------------------------- tree
    def _populate_tree(self, entries):
        self.tree.delete(*self.tree.get_children())
        self.iid_by_id.clear()
        self.vid_by_iid.clear()
        self.checked.clear()
        self.row_order.clear()
        self.status_by_vid.clear()
        self.row_thumbs.clear()
        for e in entries:
            self.checked[e["id"]] = True
            iid = self.tree.insert(
                "", tk.END, values=("\u2713", e["title"], e["uploader"], "New"))
            self.iid_by_id[e["id"]] = iid
            self.vid_by_iid[iid] = e["id"]
            self.row_order.append(iid)
            self._enqueue_thumb_job(e["id"])

    def _matches_filter(self, iid, query):
        values = self.tree.item(iid, "values")
        text = f"{values[1]} {values[2]}".lower()
        return query in text

    def _apply_filter(self):
        query = self.filter_var.get().strip().lower()
        children = list(self.tree.get_children(""))
        visible = [iid for iid in self.row_order if self._matches_filter(iid, query)] \
            if query else list(self.row_order)
        hidden = set(children) - set(visible)
        for iid in hidden:
            self.tree.detach(iid)
        index = 0
        for iid in visible:
            if iid not in children:
                self.tree.move(iid, "", min(index, len(self.tree.get_children(""))))
            index += 1

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        vid = self.vid_by_iid.get(iid)
        if vid and vid in self.failed:
            self.tree.selection_set(iid)
            menu = tk.Menu(self.root, tearoff=0)
            menu.add_command(label="Retry this song",
                             command=lambda: self._retry_single(vid))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

    # ------------------------------------------------------------- rename prompt
    def _ask_rename(self, entry):
        """Block worker thread until the user answers [skip|rename|cancel]."""
        ev = threading.Event()
        vid = entry["id"]
        self._ask_events[vid] = ev
        self._ask_answers[vid] = None
        self._enqueue(("ask_rename", entry))
        ev.wait(3600)
        self._ask_events.pop(vid, None)
        return self._ask_answers.pop(vid, None) or "cancel"

    def _show_rename_dialog(self, entry):
        vid = entry["id"]
        if vid not in self._ask_events:
            return
        win = tb.Toplevel(self.root)
        win.title("Name already exists")
        win.transient(self.root)
        win.resizable(False, False)
        result = {"v": "cancel"}

        frm = tb.Frame(win, padding=14)
        frm.pack(fill="both", expand=True)
        tb.Label(
            frm,
            text=f"The song below has the same name as a file already saved:\n\n"
                 f"  '{entry['title']}'\n\n"
                 "What should I do with this download?",
            justify="left", wraplength=400).pack(anchor="w")

        buttons = tb.Frame(frm)
        buttons.pack(fill="x", pady=(14, 0))

        def decide(v):
            result["v"] = v
            win.destroy()

        for text, value, style in (
                ("Skip this song", "skip", "secondary"),
                ("Rename to 'Title (2)'", "rename", "info"),
                ("Cancel rest", "cancel", "danger")):
            tb.Button(buttons, text=text, bootstyle=style, width=18,
                      command=lambda v=value: decide(v)).pack(side="left", padx=4)

        win.grab_set()
        win.wait_window()
        self._ask_answers[vid] = result["v"]
        if vid in self._ask_events:
            self._ask_events[vid].set()

    # ------------------------------------------------------------- thumbnails
    def _ensure_thumb_workers(self, count=4):
        if self._thumb_workers:
            return
        for _ in range(count):
            t = threading.Thread(target=self._thumb_worker, daemon=True)
            t.start()
            self._thumb_workers.append(t)

    def _enqueue_thumb_job(self, vid):
        self._ensure_thumb_workers()
        self._thumb_jobs.put(vid)

    def _thumb_worker(self):
        while True:
            vid = self._thumb_jobs.get()
            if vid is None:
                self._thumb_jobs.task_done()
                return
            try:
                url = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = resp.read()
                img = Image.open(io.BytesIO(data)).convert("RGBA")
                img.thumbnail((90, 56))
                mask = Image.new("L", img.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle(
                    [0, 0, img.width - 1, img.height - 1], radius=10, fill=255)
                img.putalpha(mask)
                self._enqueue(("row_thumb", vid, img))
            except Exception:
                self._enqueue(("row_thumb", vid, None))
            finally:
                self._thumb_jobs.task_done()

    # ------------------------------------------------------------- public actions
    def load_playlist(self):
        if not self._check_prereqs():
            return
        self._save_settings()
        self._start_worker("load", self.url_var.get().strip())

    def download_all(self):
        if not self._check_prereqs():
            return
        self._save_settings()
        self._start_worker("download")

    def retry_failed(self):
        if not self.failed:
            return
        if not self._check_prereqs():
            return
        self._save_settings()
        self._start_worker("retry", None, list(self.failed.keys()))

    def check_status(self):
        if not self._check_prereqs():
            return
        self._save_settings()
        self._start_worker("check")

    # ------------------------------------------------------------- worker
    def _snapshot(self):
        """Copy UI settings (safe to read only on the Tk main thread)."""
        cookie_path = self.cfg.get("cookie_path", "") or ""
        if cookie_path:
            ok, _c, _y, _m = core.validate_cookie_file(cookie_path)
            if not ok:
                cookie_path = ""
        for e in self.entries:
            self.checked.setdefault(e["id"], True)
        return {
            "url": self.url_var.get().strip(),
            "dir": self.dir_var.get().strip() or os.path.expanduser("~"),
            "media": self.media_var.get(),
            "format": self.format_var.get(),
            "quality": self.quality_var.get(),
            "resolution": self.res_var.get(),
            "thumbnail": self.thumb_var.get(),
            "cookie_path": cookie_path,
            "selected": self._checked_ids(),
            "parallel": self._parallel_jobs() >= 2,
            "parallel_jobs": self._parallel_jobs(),
        }

    def _start_worker(self, action, url=None, extra=None):
        if self.worker_alive:
            self._log(">>> Still busy, wait for the current job to finish.")
            return
        self.worker_alive = True
        self.stop_requested = False
        self._set_busy(True)
        snap = self._snapshot()
        threading.Thread(target=self._worker, args=(action, url, extra, snap),
                         daemon=True).start()

    def _retry_single(self, vid):
        if not self._check_prereqs():
            return
        self._save_settings()
        self._start_worker("retry", None, [vid])

    def _worker(self, action, url=None, extra=None, snap=None):
        Q = self._enqueue
        final_status = "Ready."
        summary = None
        snap = snap or {}
        cookiefile = snap.get("cookie_path") or ""
        fix = "cookies.txt" if cookiefile else ""
        cookie_used = bool(cookiefile)
        try:
            if action == "load" or not self.entries:
                target = url or snap.get("url") or ""
                Q(("log", f"Fetching: {target}"))
                Q(("status", "Fetching metadata..."))
                title, entries = core.fetch_playlist(target, fix, cookiefile)
                self.playlist_title = title
                self.entries = entries
                Q(("setup_tree", entries))
                Q(("log", f"{title} - {len(entries)} song(s)"))
                final_status = f"Loaded {len(entries)} song(s)."
                Q(("reset_progress",))
                Q(("status", final_status))
                if action == "load":
                    return

            entries = self.entries
            download_dir = snap["dir"]
            os.makedirs(download_dir, exist_ok=True)
            thumbs_before = core.snapshot_thumbnails(download_dir)
            core.cleanup_partials(download_dir)
            is_video = snap.get("media") == "Video"
            codec = core.AUDIO_FORMATS[snap["format"]]["codec"] if not is_video else "mp3"
            quality = snap["quality"] if (snap.get("quality") and snap["quality"] != "Best") \
                else "192"
            resolution = snap["resolution"] if is_video else "Best"
            embed_thumb = bool(snap.get("thumbnail"))

            if cookie_used:
                Q(("log", f">>> Fix blocked: using signed-in cookies file "
                          f"'{os.path.basename(cookiefile)}'."))
            else:
                Q(("log", ">>> Fix blocked: no cookies file chosen yet. If some "
                          "videos fail, click 'Fix blocked (cookies.txt)', pick your "
                          "signed-in cookies.txt, then press Retry Failed."))

            Q(("log", f"Scanning files in: {download_dir}"))
            existing, _ = core.check_missing(download_dir, entries)
            Q(("mark_statuses", existing))
            present_ids = {e["id"] for e in entries
                           if core.normalize_title(e["title"]) in existing}

            if action == "retry":
                ids = set(extra or [])
                pending = [e for e in entries if e["id"] in ids]
                if not pending:
                    final_status = "Nothing to retry."
                    Q(("log", final_status))
                    Q(("status", final_status))
                    return
                Q(("log", f"Retrying {len(pending)} failed song(s)..."))
            elif action == "check":
                n_missing = len(entries) - len(present_ids)
                Q(("log", f"Checked {len(entries)} song(s) in "
                          f"'{download_dir}': {len(present_ids)} already downloaded, "
                          f"{n_missing} missing."))
                Q(("mark_statuses", existing))
                final_status = (f"{len(present_ids)} downloaded, "
                                f"{n_missing} missing.")
                Q(("status", final_status))
                return
            else:
                selected = set(snap.get("selected") or [])
                if not selected:
                    final_status = "Nothing selected - tick songs first, then download."
                    Q(("log", ">>> No songs are ticked. Tick the songs you want "
                              "to download, then press 'Download Checked'."))
                    Q(("status", final_status))
                    return
                missing = [e for e in entries
                           if core.normalize_title(e["title"]) not in existing
                           and e["id"] in selected]
                if not missing:
                    final_status = ("All ticked songs are already downloaded "
                                    "- nothing missing.")
                    Q(("log", final_status))
                    Q(("status", final_status))
                    return
                Q(("log", f"{len(missing)} song(s) to download. "
                          f"{len(entries) - len(missing)} already present, "
                          f"{sum(1 for e in entries if e['id'] not in selected)} "
                          f"not ticked."))
                pending = missing
            pool = pending
            Q(("log", f"Downloading {len(pool)} song(s) as "
                       f"{'Video' if is_video else 'Music'} "
                       f"({quality} {codec}{' @ ' + resolution if is_video else ''}) "
                       f"to: {download_dir}"))

            target_ext = core.AUDIO_FORMATS[snap["format"]]["ext"] \
                if not is_video else "mp4"
            Q(("set_expected", len(pool)))
            jobs = int(snap.get("parallel_jobs") or 1)
            parallel_on = jobs >= 2 and len(pool) >= 2
            if parallel_on:
                downloaded_count, skipped_count = self._download_parallel(
                    pool, snap, download_dir, is_video, codec, quality, resolution,
                    embed_thumb, fix, cookiefile, target_ext, cookie_used, jobs)
            else:
                downloaded_count, skipped_count = self._download_sequential(
                    pool, snap, download_dir, is_video, codec, quality, resolution,
                    embed_thumb, fix, cookiefile, target_ext, cookie_used)

            core.cleanup_partials(download_dir)
            core.cleanup_foreign_junk(download_dir, thumbs_before)
            existing_latest = core.scan_saved_titles(download_dir)
            Q(("refresh_statuses", existing_latest))

            Q(("reset_progress",))
            parts = [f"Downloaded {downloaded_count} song(s)"]
            if skipped_count:
                parts.append(f"{skipped_count} skipped")
            if self.failed:
                parts.append(f"{len(self.failed)} failed")
            if self.unavailable:
                parts.append(f"{len(self.unavailable)} unavailable")
            if self.stop_requested:
                parts.append("stopped")
            final_status = "; ".join(parts).rstrip("; ") + "."
            summary = final_status
            Q(("log", final_status))
        except Exception as exc:
            import traceback
            traceback.print_exc()
            final_status = f"Error: {exc}"
            Q(("log", f"ERROR: {exc}"))
        finally:
            Q(("finished", final_status, summary))

    # ----------------------------------------------------- download modes
    def _download_sequential(self, pool, snap, download_dir, is_video, codec,
                             quality, resolution, embed_thumb, fix, cookiefile,
                             target_ext, cookie_used):
        """Original one-at-a-time downloader (used when Multi-download is off)."""
        Q = self._enqueue
        downloaded_count = 0
        skipped_count = 0
        for i, e in enumerate(pool, 1):
            if self.stop_requested:
                Q(("log", ">>> Stopped by user."))
                break
            vid = e["id"]
            Q(("song_index", i, len(pool)))
            Q(("row_status", vid, "Waiting..."))
            Q(("status", f"[{i}/{len(pool)}] {e['title']}"))

            outtmpls = {}
            if core.title_file_exists(download_dir, e["title"]):
                choice = self._ask_rename(e)
                if choice == "skip":
                    skipped_count += 1
                    Q(("log", f"Skipped (already saved): {e['title']}"))
                    Q(("row_status", vid, "Skipped"))
                    continue
                if choice == "cancel":
                    self.stop_requested = True
                    Q(("log", ">>> Cancelled by user, stopping."))
                    break
                stem = core.unique_stem(download_dir, e["title"])
                outtmpls[e["url"]] = os.path.join(download_dir, stem) + ".%(ext)s"
                Q(("log", f"Renaming to: {stem}.{target_ext}"))

            Q(("row_status", vid, "Downloading..."))
            _row_tick = time.monotonic()

            def song_cb(status, downloaded, total, fname, speed, eta, _vid=vid):
                nonlocal _row_tick
                Q(("progress", status, downloaded, total, fname, speed, eta))
                if time.monotonic() - _row_tick >= 0.4:
                    _row_tick = time.monotonic()
                    Q(("row_progress", _vid, downloaded, total, speed or 0))

            try:
                done, errors = core.download_urls(
                    [e["url"]], download_dir,
                    media_type=snap.get("media"),
                    codec=codec,
                    quality=quality,
                    resolution=resolution,
                    embed_thumbnail=embed_thumb,
                    progress_cb=song_cb,
                    fix=fix,
                    outtmpls=outtmpls or None,
                    cookiefile=cookiefile,
                    cancel_check=lambda: self.stop_requested,
                )
            except core.DownloadCancelled:
                Q(("log", ">>> Stopped by user."))
                Q(("progress", "stopped", 0, 0, "", 0, None))
                break
            except Exception as exc:
                errors = [str(exc)]
                done = 0
            if done:
                downloaded_count += 1
                self.failed.pop(vid, None)
                self.unavailable.pop(vid, None)
                Q(("row_status", vid, "Downloaded"))
            else:
                reason = errors[0] if errors else "unknown error"
                self._record_failure(vid, e["title"], reason, cookie_used)
            Q(("progress", "finished", 0, 0, "", 0, None))
        return downloaded_count, skipped_count

    def _download_parallel(self, pool, snap, download_dir, is_video, codec,
                           quality, resolution, embed_thumb, fix, cookiefile,
                           target_ext, cookie_used, jobs):
        """Download several songs at once using a worker thread pool."""
        Q = self._enqueue
        total = len(pool)
        lock = threading.Lock()
        state = {"downloaded": 0, "skipped": 0, "active": 0, "done": 0}

        core.warm_session()

        # Build the batch up front (rename dialogs are main-thread-only) and
        # reserve unique filenames so same-titled songs never collide.
        batch = []
        reserved = set()
        for e in pool:
            if self.stop_requested:
                Q(("log", ">>> Stopped by user."))
                break
            exists = core.title_file_exists(download_dir, e["title"])
            if exists:
                choice = self._ask_rename(e)
                if choice == "skip":
                    state["skipped"] += 1
                    Q(("log", f"Skipped (already saved): {e['title']}"))
                    Q(("row_status", e["id"], "Skipped"))
                    continue
                if choice == "cancel":
                    self.stop_requested = True
                    Q(("log", ">>> Cancelled by user, stopping."))
                    break
            stem = core.unique_stem(download_dir, e["title"], reserved)
            reserved.add(stem)
            outtmpl = os.path.join(download_dir, stem) + ".%(ext)s"
            if exists:
                Q(("log", f"Renaming to: {stem}.{target_ext}"))
            batch.append((e, outtmpl, stem))
        if state["skipped"]:
            total -= state["skipped"]

        if self.stop_requested or not batch:
            return state["downloaded"], state["skipped"]

        state["active"] = min(len(batch), jobs)

        def dl_one(item):
            if self.stop_requested:
                return
            e, outtmpl, _stem = item
            vid = e["id"]
            Q(("row_status", vid, "Downloading..."))
            outtmpls = {e["url"]: outtmpl}
            _row_tick = time.monotonic()

            def song_cb(status, downloaded, totalb, fname, speed, eta,
                        _vid=vid):
                nonlocal _row_tick
                Q(("progress", status, downloaded, totalb, fname, speed, eta))
                if time.monotonic() - _row_tick >= 0.4:
                    _row_tick = time.monotonic()
                    Q(("row_progress", _vid, downloaded, totalb, speed or 0))

            try:
                done, errors = core.download_urls(
                    [e["url"]], download_dir,
                    media_type=snap.get("media"),
                    codec=codec,
                    quality=quality,
                    resolution=resolution,
                    embed_thumbnail=embed_thumb,
                    progress_cb=song_cb,
                    fix=fix,
                    outtmpls=outtmpls,
                    cookiefile=cookiefile,
                    cancel_check=lambda: self.stop_requested,
                )
            except core.DownloadCancelled:
                with lock:
                    state["done"] += 1
                    state["active"] -= 1
                    done_n = state["done"]
                    active_n = state["active"]
                Q(("log", f"Cancelled: {e['title']}"))
                Q(("tick", done_n, active_n, total))
                return
            except Exception as exc:
                errors = [str(exc)]
                done = 0
            if done:
                with lock:
                    state["downloaded"] += 1
                    self.failed.pop(vid, None)
                    self.unavailable.pop(vid, None)
                Q(("row_status", vid, "Downloaded"))
            else:
                reason = errors[0] if errors else "unknown error"
                with lock:
                    self._record_failure(vid, e["title"], reason, cookie_used)
            with lock:
                state["done"] += 1
                state["active"] -= 1
                done_n = state["done"]
                active_n = state["active"]
            Q(("tick", done_n, active_n, total))

        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = []
            for item in batch:
                if self.stop_requested:
                    break
                futures.append(executor.submit(dl_one, item))
            if self.stop_requested:
                for f in futures:
                    try:
                        f.cancel()
                    except Exception:
                        pass
            else:
                stopped = False
                for fut in concurrent.futures.as_completed(futures):
                    if self.stop_requested:
                        stopped = True
                        for f in futures:
                            try:
                                if not f.done():
                                    f.cancel()
                            except Exception:
                                pass
                        break
                    try:
                        fut.result()
                    except Exception:
                        pass
        return state["downloaded"], state["skipped"]

    def _on_close(self):
        if not self._closed:
            self._closed = True
            self.stop_requested = True
            core.abort_ffmpeg()
            for _ in self._thumb_workers:
                self._thumb_jobs.put(None)
            self._save_settings()
            d = self.dir_var.get().strip()
            if d and os.path.isdir(d):
                core.cleanup_partials(d)
        self.root.destroy()


def main():
    root = tb.Window(
        title="YouTube Playlist Downloader",
        themename="darkly",
        size=(1120, 800),
        minsize=(920, 680),
    )
    icon = _resource_path("icon.ico")
    if os.path.isfile(icon):
        try:
            root.iconbitmap(icon)
        except Exception:
            pass
    App(root)
    try:
        root.mainloop()
    finally:
        os._exit(0)


if __name__ == "__main__":
    main()