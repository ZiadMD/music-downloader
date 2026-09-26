"""YouTube playlist metadata and download orchestration.

This module is the boundary between the UI and yt-dlp. It owns the yt-dlp
option construction, the progress/cancellation hooks, and the process tracking
that makes Stop responsive. It deliberately does not re-export the helpers it
uses - callers import those from the module that owns them:

- :mod:`musicdl.naming`  - filename normalization and safe stems
- :mod:`musicdl.cookies` - cookies.txt validation
- :mod:`musicdl.paths`   - ffmpeg / Node.js discovery
- :mod:`musicdl.cleanup` - partial-file sweeping
"""

import contextlib
import os
import shutil
import subprocess
import threading
import urllib.parse
from typing import Any, cast

from yt_dlp import YoutubeDL
from yt_dlp.networking.impersonate import ImpersonateTarget
from yt_dlp.utils import DownloadCancelled as YTDownloadCancelled

from . import paths
from .naming import existing_titles, normalize_title

# ------------------------------------------------------------------- options
AUDIO_FORMATS = {
    "MP3": {"codec": "mp3", "ext": "mp3", "quality": "192"},
    "M4A (AAC)": {"codec": "m4a", "ext": "m4a", "quality": "192"},
    "FLAC": {"codec": "flac", "ext": "flac", "quality": "192"},
    "WAV": {"codec": "wav", "ext": "wav", "quality": "192"},
    "OGG (Vorbis)": {"codec": "vorbis", "ext": "ogg", "quality": "192"},
    "OPUS": {"codec": "opus", "ext": "opus", "quality": "192"},
}

QUALITIES = ["192", "128", "256", "320", "Best"]
VIDEO_RESOLUTIONS = ["Best", "1080p", "720p", "480p"]
MEDIA_TYPES = ["Music", "Video"]

COOKIE_BROWSERS = ("chrome", "edge", "firefox", "brave", "opera")

DEFAULT_QUALITY = "192"

_session_lock = threading.Lock()
_proc_lock = threading.Lock()
_active_procs = []


class DownloadCancelled(Exception):
    """Raised from a progress hook to cleanly abort the current download."""


def _ydl(params: dict):
    """Construct a YoutubeDL from a plain options dict.

    yt-dlp's stubs declare ``params`` as its internal ``_Params`` TypedDict,
    but every key we pass is a documented public option. This helper is the
    single place that crosses that boundary, so the rest of the module can
    build plain dicts and stay type-checked.
    """
    return YoutubeDL(cast(Any, params))


# ---------------------------------------------------- ffmpeg subprocess tracking
def _is_ffmpeg_args(args) -> bool:
    """Best-effort: is this subprocess a yt-dlp ffmpeg/avconv invocation?"""
    exe = args[0] if isinstance(args, (list, tuple)) and args else args
    return os.path.basename(str(exe)).lower().startswith(("ffmpeg", "avconv"))


def _install_popen_tracker() -> None:
    """Track yt-dlp's ffmpeg subprocesses so Stop can kill them mid-conversion.

    yt-dlp runs ffmpeg through ``yt_dlp.utils.Popen.run()``; we wrap it to
    record running processes (for a moment only) and expose
    :func:`abort_ffmpeg`. Best-effort by design: a change to yt-dlp internals
    must never break downloads, so any failure here is swallowed.
    """
    try:
        from yt_dlp.utils import Popen

        def tracked_run(cls, *args, timeout=None, input=None, **kwargs):
            if input is not None and kwargs.get("stdin") is None:
                kwargs["stdin"] = subprocess.PIPE
            with cls(*args, **kwargs) as proc:
                tracked = _is_ffmpeg_args(args)
                if tracked:
                    with _proc_lock:
                        _active_procs.append(proc)
                try:
                    default = b""
                    if (kwargs.get("text") or kwargs.get("encoding")
                            or kwargs.get("errors")
                            or kwargs.get("universal_newlines")):
                        default = ""
                    stdout, stderr = proc.communicate_or_kill(
                        input=input, timeout=timeout)
                    return stdout or default, stderr or default, proc.returncode
                finally:
                    if tracked:
                        with _proc_lock:
                            try:
                                _active_procs.remove(proc)
                            except ValueError:
                                pass

        # Deliberately replaces a yt-dlp internal whose signature may change;
        # the whole hook is best-effort so a mismatch cannot break downloads.
        with contextlib.suppress(TypeError, AttributeError):
            cast(Any, Popen).run = classmethod(tracked_run)
    except Exception:
        pass


def abort_ffmpeg() -> None:
    """Kill any ffmpeg subprocess yt-dlp currently has running.

    Called from the main thread when the user hits Stop, so conversions abort
    immediately instead of running to completion first.
    """
    with _proc_lock:
        procs = list(_active_procs)
    for p in procs:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass


_install_popen_tracker()


def warm_session() -> None:
    """Initialize yt-dlp's networking/session machinery once.

    Parallel workers each build their own YoutubeDL instance; the first one to
    be created triggers one-time setup (curl_cffi/impersonation session
    creation) which can contend when several threads race at once. Build one
    instance up front, under a lock, so the pool starts cleanly.
    """
    try:
        with _session_lock:
            with _ydl({"quiet": True, "skip_download": True}):
                pass
    except Exception:
        pass


def ffmpeg_available() -> bool:
    """True if ffmpeg is installed and reachable.

    Checks PATH first, then the usual per-platform install locations
    (winget/Chocolatey on Windows, Homebrew on macOS, distro packages on
    Linux) so the app works without a manual PATH change.
    """
    try:
        if shutil.which("ffmpeg"):
            return True
    except Exception:
        pass
    return bool(paths.find_ffmpeg_dir())


def _ensure_ffmpeg_on_path() -> None:
    """Make ffmpeg reachable for yt-dlp by prepending a known location to PATH."""
    if shutil.which("ffmpeg"):
        return
    found = paths.find_ffmpeg_dir()
    if found:
        os.environ["PATH"] = found + os.pathsep + os.environ.get("PATH", "")


# --------------------------------------------------------------- session options
def _impersonate_supported() -> bool:
    """True if curl_cffi is installed, enabling yt-dlp's TLS impersonation."""
    try:
        import curl_cffi
    except ImportError:
        return False
    return curl_cffi is not None


def _cookies_txt_path() -> str:
    """Default location of the app's Netscape cookies.txt."""
    return paths.cookies_file()


def _youtube_session_opts(fix: str = "", cookiefile: str = ""):
    """Build yt-dlp options that work around YouTube's bot protection.

    ``fix`` selects where cookies come from: a browser name from
    :data:`COOKIE_BROWSERS`, or ``"cookies.txt"`` for the app's own file. An
    explicit ``cookiefile`` path always wins.
    """
    opts = {}
    if _impersonate_supported():
        try:
            opts["impersonate"] = ImpersonateTarget.from_str("chrome")
        except Exception:
            pass
    node = paths.find_node()
    if node:
        opts["js_runtimes"] = {"node": {"path": node}}
    opts["remote_components"] = ["ejs:github"]

    cookiefile = (cookiefile or "").strip()
    if cookiefile and os.path.isfile(cookiefile):
        opts["cookiefile"] = cookiefile
        return opts

    fix = (fix or "").strip().lower()
    if fix == "cookies.txt":
        path = _cookies_txt_path()
        if os.path.isfile(path):
            opts["cookiefile"] = path
    elif fix in COOKIE_BROWSERS:
        opts["cookiesfrombrowser"] = (fix,)
    return opts


# --------------------------------------------------------------------- metadata
def looks_like_single_video(url: str) -> bool:
    """True when ``url`` points to a single video, not a playlist.

    YouTube decorates shared watch links with a ``list`` parameter even when
    the link is just one video (``watch?v=ID&list=...``). Without this check
    yt-dlp would extract the *playlist* context instead of the video.
    """
    try:
        parsed = urllib.parse.urlparse(url or "")
    except ValueError:
        return False
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    if "youtu.be" in host:
        return True
    if any(seg in path for seg in ("/shorts/", "/embed/", "/live/")):
        return True
    if host.startswith("music.youtube.com") and "/watch/" in path:
        return True
    return bool(urllib.parse.parse_qs(parsed.query).get("v"))


def _entry_from_info(e) -> dict | None:
    """Reduce a yt-dlp entry to the four fields the UI needs, or None."""
    vid = e.get("id") if hasattr(e, "get") else None
    if not vid:
        return None
    return {
        "id": vid,
        "title": e.get("title") or e.get("fulltitle") or "Unknown title",
        "uploader": e.get("uploader") or e.get("channel") or "Unknown artist",
        "url": f"https://www.youtube.com/watch?v={vid}",
    }


def _fetch_opts(single: bool, fix: str, cookiefile: str) -> dict:
    """yt-dlp options for a metadata-only extract."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "socket_timeout": 30,
    }
    if single:
        # A 'watch?v=ID&list=...' link must download just the video, and a
        # single video needs a full extract to recover its title/artist.
        opts["noplaylist"] = True
        opts["extract_flat"] = False
    else:
        opts["extract_flat"] = True
    opts.update(_youtube_session_opts(fix, cookiefile))
    return opts


def fetch_playlist(playlist_url: str, fix: str = "", cookiefile: str = ""):
    """Fetch playlist metadata. Returns ``(playlist_title, [entry, ...])``.

    Accepts a full playlist URL or a single video/music link (which becomes a
    one-song list). Each entry has ``id``, ``title``, ``uploader`` and ``url``.
    """
    single = looks_like_single_video(playlist_url)
    with _ydl(_fetch_opts(single, fix, cookiefile)) as ydl:
        info = ydl.extract_info(playlist_url, download=False) or {}

    raw_entries = [e for e in (info.get("entries") or []) if e]
    if not raw_entries and info.get("id"):
        raw_entries = [info]
    entries = [e for e in (_entry_from_info(x) for x in raw_entries) if e]
    if not entries:
        raise ValueError("Nothing to load. Make sure the link points to a "
                         "YouTube playlist or video.")

    title = info.get("title") if info.get("entries") else "Single video"
    return title or "Playlist", entries


# ---------------------------------------------------------------------- download
def _video_format(resolution: str) -> str:
    """Build a yt-dlp format selector for the requested resolution."""
    if resolution in ("1080p", "720p", "480p"):
        height = resolution[:-1]
        return (f"bestvideo[height<={height}]+bestaudio/"
                f"best[height<={height}]/best")
    return "bestvideo+bestaudio/best"


def _make_progress_hook(note_progress, cancel_check=None):
    def hook(d):
        if cancel_check and cancel_check():
            abort_ffmpeg()
            raise YTDownloadCancelled("download cancelled by user")
        if d.get("status") in ("downloading", "finished"):
            note_progress(
                d["status"],
                d.get("downloaded_bytes") or 0,
                d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
                d.get("filename", ""),
                d.get("speed") or 0,
                d.get("eta"),
            )
    return hook


def _make_postprocessor_hook(cancel_check=None):
    """Abort postprocessing (e.g. ffmpeg conversions) when the user stops."""
    def hook(_d):
        if cancel_check and cancel_check():
            abort_ffmpeg()
            raise YTDownloadCancelled("download cancelled by user")
    return hook


def _build_opts(output_dir, media_type, codec, quality, resolution,
                embed_thumbnail, progress_cb, cancel_check, fix, cookiefile):
    """Assemble the yt-dlp option dict for one download run."""
    is_video = media_type == "Video"
    postprocessors = [{"key": "FFmpegMetadata", "add_chapters": False}]
    if not is_video:
        postprocessors.insert(0, {
            "key": "FFmpegExtractAudio",
            "preferredcodec": codec,
            "preferredquality": quality,
        })
    if embed_thumbnail:
        postprocessors.append({"key": "EmbedThumbnail"})

    opts = {
        "format": _video_format(resolution) if is_video else "bestaudio/best",
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "noplaylist": True,
        "writethumbnail": embed_thumbnail,
        "embedthumbnail": embed_thumbnail,
        "postprocessors": postprocessors,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": ([_make_progress_hook(progress_cb, cancel_check)]
                           if progress_cb else []),
        "postprocessor_hooks": ([_make_postprocessor_hook(cancel_check)]
                                if progress_cb else []),
        "retries": 5,
        "fragment_retries": 5,
        "continuedl": True,
        "noprogress": True,
        "consoletitle": False,
        "socket_timeout": 30,
    }
    if is_video:
        opts["merge_output_format"] = "mp4"
    opts.update(_youtube_session_opts(fix, cookiefile))
    return opts


def _set_outtmpl(params, template: str) -> None:
    """Point yt-dlp's ``outtmpl`` at ``template`` for the next download.

    ``params["outtmpl"]`` may be a plain string or a per-type mapping
    depending on what was passed in, so normalise it to the mapping form
    before setting the ``default`` entry we actually use.
    """
    current = params.get("outtmpl")
    if not isinstance(current, dict):
        params["outtmpl"] = {"default": template}
    else:
        current["default"] = template


def download_urls(
    urls,
    output_dir: str,
    media_type: str = "Music",
    codec: str = "mp3",
    quality: str = DEFAULT_QUALITY,
    resolution: str = "Best",
    embed_thumbnail: bool = True,
    progress_cb=None,
    fix: str = "",
    outtmpls: dict | None = None,
    cookiefile: str = "",
    cancel_check=None,
):
    """Download a list of URLs into ``output_dir``.

    ``media_type`` "Music" extracts audio (codec/quality); "Video" downloads a
    merged MP4 at ``resolution`` (bestvideo+bestaudio).

    ``fix`` enables the YouTube bot-protection workarounds (see
    :func:`_youtube_session_opts`). ``cookiefile``, when set, is a validated
    cookies.txt path and takes priority.

    ``outtmpls`` maps a url to an exact output template (used for automatic
    renames) - e.g. ``{"url": "/music/dir/Song (2).%(ext)s"}``.

    Returns ``(downloaded_count, errors)`` where ``errors`` lists one failure
    message per URL that failed.
    """
    os.makedirs(output_dir, exist_ok=True)
    _ensure_ffmpeg_on_path()

    opts = _build_opts(output_dir, media_type, codec, quality, resolution,
                       embed_thumbnail, progress_cb, cancel_check, fix, cookiefile)
    outtmpls = outtmpls or {}
    count = 0
    errors = []
    with _ydl(opts) as ydl:
        for url in urls:
            try:
                if url in outtmpls:
                    _set_outtmpl(ydl.params, outtmpls[url])
                ydl.download([url])
                if cancel_check and cancel_check():
                    raise DownloadCancelled("download cancelled by user")
                count += 1
            except (DownloadCancelled, YTDownloadCancelled):
                raise DownloadCancelled("download cancelled by user")
            except Exception as exc:  # per-song tolerance, report the reason
                if cancel_check and cancel_check():
                    raise DownloadCancelled("download cancelled by user")
                errors.append(f"{url}: {exc}")
    return count, errors


# ------------------------------------------------------------------- comparison
def check_missing(download_dir: str, entries):
    """Compare playlist entries with downloaded files by normalized title.

    Returns ``(existing_titles, missing_entries)``.
    """
    existing = existing_titles(download_dir)
    return existing, [e for e in entries
                      if normalize_title(e["title"]) not in existing]


def scan_saved_titles(download_dir: str) -> set:
    """Re-scan the folder now and return normalized titles of saved media."""
    return existing_titles(download_dir)
