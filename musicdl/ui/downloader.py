"""The download job: a headless orchestrator that reports through callbacks.

Splitting this out of the Tk ``App`` keeps the interesting logic (which songs to
download, rename collisions, parallel batching, failure classification)
testable without a display, and keeps the UI class focused on rendering.

All progress is reported by putting tuples on a ``queue.Queue``; the UI drains
it on the Tk main thread. The job never touches a widget.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import core
from ..cleanup import (cleanup_foreign_junk, cleanup_partials,
                       snapshot_thumbnails)
from ..cookies import validate_cookie_file
from ..formatting import plural
from ..naming import normalize_title, title_file_exists, unique_stem

# Message kinds, mirrored by App._handle_msg.
LOG = "log"
STATUS = "status"
PROGRESS = "progress"
SONG_INDEX = "song_index"
TICK = "tick"
ROW_STATUS = "row_status"
ROW_PROGRESS = "row_progress"
SET_EXPECTED = "set_expected"
RESET_PROGRESS = "reset_progress"
ASK_RENAME = "ask_rename"
SETUP_TREE = "setup_tree"
MARK_STATUSES = "mark_statuses"
REFRESH_STATUSES = "refresh_statuses"
# Emitted by PlaylistTable's ThumbnailLoader, not by this module, but handled
# by the same queue pump.
ROW_THUMB = "row_thumb"
FINISHED = "finished"

# Rows are updated at most this often to avoid flooding the Tk event loop.
_ROW_TICK_SECONDS = 0.4

# Substrings that mean YouTube will never serve this video again.
_UNAVAILABLE_MARKERS = (
    "video unavailable", "private video", "removed", "no longer available",
    "has been deleted", "not available", "is unavailable",
)

# Failure text hinting at an age/sign-in/premium gate.
_AUTH_HINTS = ("sign in", "age", "confirm", "premium", "auth")


def is_unavailable(reason: str) -> bool:
    """True when the video is permanently gone (removed / private / deleted)
    rather than a network or bot-check glitch."""
    rl = (reason or "").lower()
    return any(m in rl for m in _UNAVAILABLE_MARKERS)


class DownloadJob:
    """Runs one 'load' / 'download' / 'check' / 'retry' action.

    Constructed on the Tk main thread; :meth:`start` spawns the worker.
    """

    def __init__(self, action, snapshot, enqueue, ask_rename,
                 stop_requested, url=None, ids=None):
        self.action = action
        self.url = url
        self.ids = list(ids or [])
        self.snap = snapshot
        self._emit = enqueue
        self._ask_rename = ask_rename
        self._stop_requested = stop_requested

        self.entries = []
        self.failed = {}        # vid -> failure reason
        self.unavailable = {}   # vid -> reason (removed / private)
        self.stopped = False
        self.summary = None

    # ---------------------------------------------------------------- helpers
    def _stopped(self) -> bool:
        return bool(self._stop_requested()) or self.stopped

    def _log(self, text):
        self._emit((LOG, text))

    def _status(self, text):
        self._emit((STATUS, text))

    def _record_failure(self, entry, reason, cookie_used):
        """Classify a failure and report it.

        Permanently-removed videos become 'Unavailable' (never retried);
        everything else becomes 'Failed' with a hint when a cookies export
        is likely to help.
        """
        vid, title = entry["id"], entry["title"]
        if is_unavailable(reason):
            self.unavailable[vid] = reason
            self.failed.pop(vid, None)
            self._log(f"UNAVAILABLE: {title} - removed from YouTube ({reason})")
            self._emit((ROW_STATUS, vid, "Unavailable"))
            return

        self.failed[vid] = reason
        hint = ""
        rl = reason.lower()
        if any(k in rl for k in _AUTH_HINTS):
            hint = (
                ". cookies were used but YouTube still refused this one - "
                "confirm it actually plays in your signed-in browser, then try "
                "a fresh cookies export"
                if cookie_used else
                ". It plays in your browser? Click 'Fix blocked (cookies.txt)', "
                "choose your signed-in cookies.txt, then press Retry Failed"
            )
        self._log(f"FAILED: {title} - {reason}{hint}")
        self._emit((ROW_STATUS, vid, "Failed"))

    def _resolve_cookie_path(self) -> str:
        """Return a usable cookies.txt path, or '' if the saved one is invalid."""
        path = (self.snap.get("cookie_path") or "").strip()
        if path and validate_cookie_file(path)[0]:
            return path
        return ""

    def _download_settings(self):
        """Normalize the snapshot into the values core.download_urls wants."""
        snap = self.snap
        is_video = snap.get("media") == "Video"
        fmt = snap.get("format")
        audio = core.AUDIO_FORMATS.get(fmt) or core.AUDIO_FORMATS["MP3"]
        quality = snap.get("quality")
        if not quality or quality == "Best":
            quality = core.DEFAULT_QUALITY
        return {
            "is_video": is_video,
            "codec": audio["codec"],
            "ext": "mp4" if is_video else audio["ext"],
            "quality": quality,
            "resolution": snap.get("resolution") if is_video else "Best",
            "thumbnail": bool(snap.get("thumbnail")),
        }

    # ------------------------------------------------------------ entry point
    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self._dispatch()
        except Exception as exc:  # never let the worker die silently
            import traceback

            traceback.print_exc()
            self._log(f"ERROR: {exc}")
            self._status(f"Error: {exc}")
        finally:
            self._emit((FINISHED, self.summary or "Ready.", self.summary))

    def _dispatch(self):
        action = self.action
        if action == "load" or not self.entries:
            self._load_entries()
            if action == "load":
                return

        settings = self._download_settings()
        existing, _missing = core.check_missing(self._dir, self.entries)
        self._emit((MARK_STATUSES, existing))

        if action == "retry":
            self._retry(existing, settings)
        elif action == "check":
            self._check(existing)
        else:
            self._download(existing, settings)

    # ------------------------------------------------------------------ stages
    def _load_entries(self):
        target = self.url or self.snap.get("url") or ""
        cookie_path = self._resolve_cookie_path()
        self._log(f"Fetching: {target}")
        self._status("Fetching metadata...")
        title, entries = core.fetch_playlist(
            target, fix="cookies.txt" if cookie_path else "", cookiefile=cookie_path)
        self.entries = entries
        self._emit((SETUP_TREE, entries))
        self._log(f"{title} - {plural(len(entries), 'song')}")
        self._emit((RESET_PROGRESS,))
        self._status(f"Loaded {plural(len(entries), 'song')}.")
        self.summary = None

    def _check(self, existing):
        present = {e["id"] for e in self.entries
                   if normalize_title(e["title"]) in existing}
        n_missing = len(self.entries) - len(present)
        self._log(f"Checked {plural(len(self.entries), 'song')} in "
                  f"'{self._dir}': {len(present)} already downloaded, "
                  f"{n_missing} missing.")
        self._emit((MARK_STATUSES, existing))
        self._status(f"{len(present)} downloaded, {n_missing} missing.")

    def _retry(self, existing, settings):
        wanted = set(self.ids)
        pending = [e for e in self.entries if e["id"] in wanted]
        if not pending:
            self._status("Nothing to retry.")
            self._log("Nothing to retry.")
            return
        self._log(f"Retrying {plural(len(pending), 'failed song')}...")
        self._run_pool(pending, settings)

    def _download(self, existing, settings):
        selected = set(self.snap.get("selected") or [])
        if not selected:
            self.summary = "Nothing selected - tick songs first, then download."
            self._log(">>> No songs are ticked. Tick the songs you want to "
                      "download, then press 'Download Checked'.")
            self._status(self.summary)
            return

        pending = [e for e in self.entries
                   if normalize_title(e["title"]) not in existing
                   and e["id"] in selected]
        if not pending:
            self.summary = "All ticked songs are already downloaded - nothing missing."
            self._log(self.summary)
            self._status(self.summary)
            return

        unticked = sum(1 for e in self.entries if e["id"] not in selected)
        self._log(f"{plural(len(pending), 'song')} to download. "
                  f"{len(self.entries) - len(pending)} already present, "
                  f"{unticked} not ticked.")
        self._run_pool(pending, settings)

    def _run_pool(self, pool, settings):
        """Set up the target folder, then run the pool sequentially or in parallel."""
        os.makedirs(self._dir, exist_ok=True)
        thumbs_before = snapshot_thumbnails(self._dir)
        cleanup_partials(self._dir)

        cookie_path = self._resolve_cookie_path()
        fix = "cookies.txt" if cookie_path else ""
        cookie_used = bool(cookie_path)
        if cookie_used:
            self._log(f">>> Fix blocked: using signed-in cookies file "
                      f"'{os.path.basename(cookie_path)}'.")
        else:
            self._log(">>> Fix blocked: no cookies file chosen yet. If some "
                      "videos fail, click 'Fix blocked (cookies.txt)', pick your "
                      "signed-in cookies.txt, then press Retry Failed.")

        self._log(f"Scanning files in: {self._dir}")
        quality, codec, ext = settings["quality"], settings["codec"], settings["ext"]
        self._log(f"Downloading {plural(len(pool), 'song')} as "
                  f"{'Video' if settings['is_video'] else 'Music'} "
                  f"({quality} {codec}"
                  f"{' @ ' + settings['resolution'] if settings['is_video'] else ''}) "
                  f"to: {self._dir}")

        self._emit((SET_EXPECTED, len(pool)))
        jobs = int(self.snap.get("parallel_jobs") or 1)
        if jobs >= 2 and len(pool) >= 2:
            downloaded, skipped = self._download_parallel(
                pool, settings, fix, cookie_path, cookie_used, jobs)
        else:
            downloaded, skipped = self._download_sequential(
                pool, settings, fix, cookie_path, cookie_used, ext)

        cleanup_partials(self._dir)
        cleanup_foreign_junk(self._dir, thumbs_before)
        self._emit((REFRESH_STATUSES, core.scan_saved_titles(self._dir)))
        self._emit((RESET_PROGRESS,))

        parts = [f"Downloaded {plural(downloaded, 'song')}"]
        if skipped:
            parts.append(f"{skipped} skipped")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        if self.unavailable:
            parts.append(f"{len(self.unavailable)} unavailable")
        if self._stopped():
            parts.append("stopped")
        self.summary = "; ".join(parts) + "."
        self._log(self.summary)

    @property
    def _dir(self) -> str:
        return self.snap["dir"]

    # ------------------------------------------------------------- plan build
    def _plan_batch(self, pool, target_ext):
        """Resolve name collisions up front, returning [(entry, outtmpl, stem)].

        Rename dialogs run on the Tk main thread, so every decision that needs
        one is collected here before any downloader thread starts. Reserved
        stems keep parallel downloads of same-titled songs from colliding.
        """
        batch = []
        reserved = set()
        skipped = 0
        for e in pool:
            if self._stopped():
                self._log(">>> Stopped by user.")
                break
            exists = title_file_exists(self._dir, e["title"])
            if exists:
                choice = self._ask_rename(e)
                if choice == "skip":
                    skipped += 1
                    self._log(f"Skipped (already saved): {e['title']}")
                    self._emit((ROW_STATUS, e["id"], "Skipped"))
                    continue
                if choice == "cancel":
                    self.stopped = True
                    self._log(">>> Cancelled by user, stopping.")
                    break
            stem = unique_stem(self._dir, e["title"], reserved)
            reserved.add(stem)
            if exists:
                self._log(f"Renaming to: {stem}.{target_ext}")
            batch.append((e, os.path.join(self._dir, stem) + ".%(ext)s", stem))
        return batch, skipped

    # ------------------------------------------------------------------ modes
    def _download_sequential(self, pool, settings, fix, cookiefile, cookie_used,
                             target_ext):
        """Download one song at a time (used when Multi-download is off)."""
        batch, skipped = self._plan_batch(pool, target_ext)
        downloaded = 0
        for i, (e, outtmpl, _stem) in enumerate(batch, 1):
            if self._stopped():
                break
            vid = e["id"]
            self._emit((SONG_INDEX, i, len(batch)))
            self._emit((ROW_STATUS, vid, "Waiting..."))
            self._status(f"[{i}/{len(batch)}] {e['title']}")
            self._emit((ROW_STATUS, vid, "Downloading..."))
            try:
                done, errors = self._download_one(e, outtmpl, settings, fix,
                                                  cookiefile)
            except core.DownloadCancelled:
                self._log(">>> Stopped by user.")
                break
            if done:
                downloaded += 1
                self.failed.pop(vid, None)
                self.unavailable.pop(vid, None)
                self._emit((ROW_STATUS, vid, "Downloaded"))
            else:
                self._record_failure(e, errors[0] if errors else "unknown error",
                                     cookie_used)
            self._emit((PROGRESS, "finished", 0, 0, "", 0, None))
        return downloaded, skipped

    def _download_parallel(self, pool, settings, fix, cookiefile, cookie_used,
                           jobs):
        """Download several songs at once using a thread pool."""
        core.warm_session()
        batch, skipped = self._plan_batch(pool, settings["ext"])
        total = len(pool) - skipped
        if self._stopped() or not batch:
            return 0, skipped

        state = {"downloaded": 0, "done": 0, "active": min(len(batch), jobs)}
        lock = threading.Lock()
        self._emit((TICK, 0, state["active"], total))

        def worker(item):
            e, outtmpl, _stem = item
            vid = e["id"]
            self._emit((ROW_STATUS, vid, "Downloading..."))
            try:
                done, errors = self._download_one(e, outtmpl, settings, fix,
                                                  cookiefile)
            except core.DownloadCancelled:
                done, errors = 0, ["cancelled"]
            if done:
                with lock:
                    state["downloaded"] += 1
                    self.failed.pop(vid, None)
                    self.unavailable.pop(vid, None)
                self._emit((ROW_STATUS, vid, "Downloaded"))
            elif errors != ["cancelled"]:
                with lock:
                    self._record_failure(e, errors[0] if errors else "unknown error",
                                         cookie_used)
            with lock:
                state["done"] += 1
                state["active"] -= 1
                done_n, active_n = state["done"], state["active"]
            self._emit((TICK, done_n, active_n, total))

        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = []
            for item in batch:
                if self._stopped():
                    break
                futures.append(executor.submit(worker, item))
            if self._stopped():
                for f in futures:
                    f.cancel()
            else:
                for fut in as_completed(futures):
                    if self._stopped():
                        for f in futures:
                            f.cancel()
                        break
                    try:
                        fut.result()
                    except Exception:
                        pass
        return state["downloaded"], skipped

    def _download_one(self, entry, outtmpl, settings, fix, cookiefile):
        """Run a single song's download, throttling row updates."""
        last = time.monotonic()
        vid = entry["id"]

        def on_progress(status, downloaded, total, _fname, speed, eta):
            nonlocal last
            self._emit((PROGRESS, status, downloaded, total, _fname, speed, eta))
            now = time.monotonic()
            if now - last >= _ROW_TICK_SECONDS:
                last = now
                self._emit((ROW_PROGRESS, vid, downloaded, total, speed or 0))

        return core.download_urls(
            [entry["url"]], self._dir,
            media_type=self.snap.get("media"),
            codec=settings["codec"],
            quality=settings["quality"],
            resolution=settings["resolution"],
            embed_thumbnail=settings["thumbnail"],
            progress_cb=on_progress,
            fix=fix,
            outtmpls={entry["url"]: outtmpl},
            cookiefile=cookiefile,
            cancel_check=self._stop_requested,
        )
