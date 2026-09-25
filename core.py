"""Core logic for the YouTube playlist music downloader."""

import os
import re
import shutil
import subprocess
import threading
import unicodedata
import urllib.parse

from yt_dlp import YoutubeDL
from yt_dlp.networking.impersonate import ImpersonateTarget
from yt_dlp.utils import DownloadCancelled as YTDownloadCancelled

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

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# Extensions this app produces as finished songs; anything else with the same
# stem is a leftover source (e.g. the raw '.webm' behind an MP3 conversion).
FINAL_MEDIA_EXTS = (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".mp4")

_session_lock = threading.Lock()

_proc_lock = threading.Lock()
_active_procs = []


def _is_ffmpeg_args(args):
    """Best-effort: is this subprocess a yt-dlp ffmpeg/avconv invocation?"""
    exe = args[0] if isinstance(args, (list, tuple)) and args else args
    return os.path.basename(str(exe)).lower().startswith(("ffmpeg", "avconv"))


def _install_popen_tracker():
    """Track yt-dlp's ffmpeg subprocesses so Stop can kill them mid-conversion.

    Modern yt-dlp runs ffmpeg through yt_dlp.utils.Popen.run(); we wrap that
    to record running processes (for a moment only) and expose abort_ffmpeg().
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
                            or kwargs.get("errors") or kwargs.get("universal_newlines")):
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

        Popen.run = classmethod(tracked_run)
    except Exception:
        pass


def abort_ffmpeg():
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


def warm_session():
    """Initialize yt-dlp's networking/session machinery once.

    Parallel workers each build their own YoutubeDL instance; the first one to
    be created triggers one-time setup (curl_cffi/impersonation session
    creation) which can contend when several threads race at once. Build one
    instance up front, under a lock, so the pool starts cleanly.
    """
    try:
        with _session_lock:
            with YoutubeDL({"quiet": True, "skip_download": True}):
                pass
    except Exception:
        pass


class DownloadCancelled(Exception):
    """Raised from a progress hook to cleanly abort the current download."""


def _ffmpeg_winget_dir():
    """Locate the ffmpeg bin folder installed via winget, if any."""
    base = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Microsoft",
        "WinGet",
        "Packages",
    )
    if not os.path.isdir(base):
        return None
    for pkg in os.listdir(base):
        bin_dir = os.path.join(base, pkg, "ffmpeg-*-full_build", "bin")
        for maybe in __import__("glob").glob(bin_dir):
            if os.path.isfile(os.path.join(maybe, "ffmpeg.exe")):
                return maybe
    return None


def ffmpeg_available() -> bool:
    """Return True if ffmpeg is installed and reachable (auto-detects winget installs)."""
    try:
        if shutil.which("ffmpeg"):
            return True
    except Exception:
        pass
    return bool(_ffmpeg_winget_dir())


def _ensure_ffmpeg_on_path():
    """Make ffmpeg reachable for yt-dlp by prepending a known location to PATH."""
    if shutil.which("ffmpeg"):
        return
    winget = _ffmpeg_winget_dir()
    if winget:
        os.environ["PATH"] = winget + os.pathsep + os.environ.get("PATH", "")


def sanitize_folder_name(name: str) -> str:
    """Turn a playlist title into a safe Windows folder name."""
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip().rstrip(".")
    return name[:120] or "playlist"


def normalize_title(name: str) -> str:
    """Normalize a title so playlist entries match saved file names.

    Lowercases and strips the characters that Windows removes from file names,
    so 'Artist - Song (Official Video)' maps to the name on disk. Also converts
    the full-width look-alike glyphs that yt-dlp substitutes for illegal file
    characters (e.g. '＂' for '"' and '⧸' for '/') back to their ASCII forms.
    """
    if not name:
        return ""
    # Convert full-width Unicode look-alikes to ASCII ('＂' -> '"', '？' -> '?').
    # NFKC leaves the big solidus glyphs untouched, so map those manually.
    s = (
        unicodedata.normalize("NFKC", name)
        .replace("\u29F8", "/")
        .replace("\u29F9", "\\")
        .replace("\uA789", ":")
        .replace("\uFF0F", "/")
        .replace("\uFF3C", "\\")
    )
    s = s.lower()
    # yt-dlp replaces Windows-illegal filename characters ('<':'"\/|?*') with '#'
    # when saving files, so strip that too. This keeps titles like
    # 'A: B | C' (saved as 'A# B # C') matching their folder names.
    s = re.sub(r'[<>:"/\\|?*#]', "", s)
    return " ".join(s.split())


def _video_format(resolution: str) -> str:
    """Build a yt-dlp format selector for the requested resolution."""
    if resolution == "1080p":
        return "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
    if resolution == "720p":
        return "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    if resolution == "480p":
        return "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
    return "bestvideo+bestaudio/best"


def _existing_titles(download_dir: str) -> set:
    """Return the set of normalized titles already present as files."""
    found = set()
    for root, _dirs, files in os.walk(download_dir):
        for f in files:
            if f.lower().endswith(IMAGE_EXTS):
                continue
            if _is_partial_file(f):
                continue
            found.add(normalize_title(os.path.splitext(f)[0]))
    return found


def _is_partial_file(name: str) -> bool:
    """True for leftover download fragments that are never finished songs."""
    low = name.lower()
    return low.endswith((".part", ".ytdl")) or ".temp" in low


def _try_remove(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def cleanup_partials(download_dir: str):
    """Delete leftover partial-download and thumbnail files.

    Aborted runs can leave '<name>.part' / '<name>.ytdl' / '<name>.temp.*'
    fragments, and when thumbnail embedding was interrupted, '<name>.webp'
    artwork next to the finished song. Junk in one-level subfolders (created by
    older builds that split titles on '/') is removed too, and any now-empty
    leftover folders are deleted.
    """
    if not os.path.isdir(download_dir):
        return

    def clean_dir(directory):
        removed_any = False
        try:
            names = os.listdir(directory)
        except OSError:
            return False
        media_stems = set()
        partial_stems = set()
        for name in names:
            low = name.lower()
            if _is_partial_file(name):
                partial_stems.add(
                    os.path.splitext(os.path.splitext(name)[0])[0].lower())
                continue
            if low.endswith(IMAGE_EXTS):
                continue
            media_stems.add(os.path.splitext(name)[0].lower())
        final_stems = set()
        for name in names:
            stem, ext = os.path.splitext(name)
            if ext.lower() in FINAL_MEDIA_EXTS:
                final_stems.add(stem.lower())
        for name in names:
            path = os.path.join(directory, name)
            low = name.lower()
            if _is_partial_file(name):
                if _try_remove(path):
                    removed_any = True
                continue
            stem = os.path.splitext(name)[0].lower()
            ext = os.path.splitext(name)[1].lower()
            if low.endswith((".webp", ".jpg", ".jpeg", ".png")) and (
                    stem in media_stems or stem in partial_stems):
                if _try_remove(path):
                    removed_any = True
                continue
            # raw source left behind by an interrupted conversion (e.g. '.webm'
            # when the converted '.mp3' already exists)
            if ext not in FINAL_MEDIA_EXTS and stem in final_stems:
                if _try_remove(path):
                    removed_any = True
        return removed_any

    clean_dir(download_dir)
    try:
        names = os.listdir(download_dir)
    except OSError:
        return
    for name in names:
        sub = os.path.join(download_dir, name)
        if not os.path.isdir(sub):
            continue
        removed_any = clean_dir(sub)
        if not removed_any:
            continue
        try:
            if not os.listdir(sub):
                os.rmdir(sub)
        except OSError:
            pass


def snapshot_thumbnails(download_dir: str) -> set:
    """Return the names of image files present now (before a download run).

    Used together with cleanup_foreign_junk() so thumbnails downloaded *during*
    the run can be removed even when no media/partial file survives to match
    them (e.g. an aborted song whose .part yt-dlp already deleted).
    """
    if not os.path.isdir(download_dir):
        return set()
    try:
        names = os.listdir(download_dir)
    except OSError:
        return set()
    return {n for n in names if n.lower().endswith(IMAGE_EXTS)}


def cleanup_foreign_junk(download_dir: str, before_names=frozenset()):
    """Delete image files that appeared since ``before_names`` was captured.

    These are thumbnail downloads yt-dlp left behind (never finished songs).
    Files already present before the run are preserved.
    """
    if not os.path.isdir(download_dir):
        return
    try:
        names = os.listdir(download_dir)
    except OSError:
        return
    for name in names:
        if name not in before_names and name.lower().endswith(IMAGE_EXTS):
            _try_remove(os.path.join(download_dir, name))


def _impersonate_supported() -> bool:
    try:
        import curl_cffi  # noqa: F401
        return True
    except Exception:
        return False


def _find_node() -> str:
    try:
        exe = shutil.which("node")
        if exe:
            return exe
    except Exception:
        pass
    for candidate in (
        r"C:\Program Files\nodejs\node.exe",
        os.path.join(os.environ.get("PROGRAMFILES", ""), "nodejs", "node.exe"),
        os.environ.get("PROGRAMFILES(X86)", "") + r"\nodejs\node.exe",
    ):
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def _cookies_txt_path() -> str:
    try:
        import sys
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "cookies.txt")


def validate_cookie_file(path):
    """Validate a Netscape-format cookies.txt for YouTube/Google cookies.

    Returns (ok, cookie_count, youtube_cookie_count, message).
    """
    if not path or not os.path.isfile(path):
        return False, 0, 0, "file not found"
    is_netscape = False
    count = 0
    domains = set()
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    if line.lower().startswith("# netscape"):
                        is_netscape = True
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    count += 1
                    domains.add(parts[0].lower().lstrip("."))
    except OSError:
        return False, 0, 0, "could not read the file"
    youtube = sum(1 for d in domains if "youtube.com" in d or "google.com" in d)
    if not count:
        msg = "the file contains no cookies"
    elif not is_netscape:
        msg = ("not a Netscape cookies.txt export - in your browser extensions, "
               "choose 'Netscape' or 'Header' format when exporting")
    elif not youtube:
        msg = ("no youtube.com / google.com cookies found - export again from the "
               "browser profile you are signed into on YouTube")
    else:
        msg = "OK"
    ok = bool(count) and is_netscape and bool(youtube)
    return ok, count, youtube, msg


def _youtube_session_opts(fix: str = "", cookiefile: str = ""):
    """Build yt-dlp options that dodge YouTube bot protection."""
    opts = {}
    if _impersonate_supported():
        try:
            opts["impersonate"] = ImpersonateTarget.from_str("chrome")
        except Exception:
            pass
    node = _find_node()
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
    elif fix in ("chrome", "edge", "firefox", "brave", "opera"):
        opts["cookiesfrombrowser"] = (fix,)
    return opts


def title_file_exists(directory: str, title: str) -> bool:
    """True if any file in directory has the same (normalized) name as title."""
    target = normalize_title(title)
    if not target:
        return False
    try:
        names = os.listdir(directory)
    except OSError:
        return False
    for f in names:
        if f.lower().endswith(IMAGE_EXTS):
            continue
        if normalize_title(os.path.splitext(f)[0]) == target:
            return True
    return False


def safe_stem(name: str) -> str:
    """Turn a song title into a Windows-safe file stem (no path separators).

    Uses yt-dlp's own sanitizer so parallel/download names look exactly like
    the titles (e.g. '"' -> '＂', '/' -> '⧸') instead of being mangled. This
    also guarantees no '/', '\' or other illegal char can become a path
    separator when the stem is joined into an output path.
    """
    from yt_dlp.utils import sanitize_filename
    stem = sanitize_filename(name or "")
    return (stem[:120].rstrip(" .")) or "song"


def unique_stem(directory: str, base_title: str, reserved=()) -> str:
    """Return a non-colliding file stem (no extension) for base_title.

    reserved is an optional extra collection of stems (no extension) that are
    treated like already-existing names - used to avoid two parallel downloads
    of same-titled songs picking the same filename.
    """
    reserved = set(s.lower() for s in (reserved or ()))
    base = safe_stem(os.path.splitext(base_title)[0])
    stem = base
    target = normalize_title(base)
    i = 2
    while True:
        try:
            names = os.listdir(directory)
        except OSError:
            names = []
        clash = (stem.lower() in reserved)
        if not clash:
            for f in names:
                if f.lower().endswith(IMAGE_EXTS):
                    continue
                # Compare normalized stems so full-width/illegal-char names
                # saved by yt-dlp still count as collisions.
                f_stem = os.path.splitext(f)[0]
                if target and normalize_title(f_stem) == target:
                    clash = True
                    break
                if f_stem.lower() == stem.lower():
                    clash = True
                    break
        if not clash:
            return stem
        stem = f"{base} ({i})"
        target = normalize_title(stem)
        i += 1


def looks_like_single_video(url: str) -> bool:
    """True when url points to a single video, not a playlist.

    YouTube decorates shared watch links with a 'list' parameter even when the
    link is just one video ('watch?v=ID&list=...'). Without this check yt-dlp
    would extract the *playlist* context instead of the video.
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
    qs = urllib.parse.parse_qs(parsed.query)
    return bool(qs.get("v"))


def fetch_playlist(playlist_url: str, fix: str = "", cookiefile: str = ""):
    """Fetch playlist metadata. Returns (playlist_title, list of entry dicts).

    Accepts a full playlist URL or a single video/music link (becomes a
    one-song list). Each entry dict has keys: id, title, uploader, url.
    """
    single = looks_like_single_video(playlist_url)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "socket_timeout": 30,
    }
    if single:
        # A 'watch?v=ID&list=...' link must download just the video, and a
        # single video needs a full extract to get its title/artist back.
        opts["noplaylist"] = True
        opts["extract_flat"] = False
    else:
        opts["extract_flat"] = True
    opts.update(_youtube_session_opts(fix, cookiefile))
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
    info = info or {}
    entries = info.get("entries") or []
    if not entries and info.get("id"):
        entries = [info]
    if not entries:
        raise ValueError("No playlist found. Make sure the link points to a YouTube playlist or video.")
    if info.get("entries"):
        playlist_title = info.get("title") or "Playlist"
    else:
        playlist_title = "Single video"
    parsed = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id")
        if not vid:
            continue
        parsed.append(
            {
                "id": vid,
                "title": e.get("title") or e.get("fulltitle") or "Unknown title",
                "uploader": e.get("uploader") or e.get("channel") or "Unknown artist",
                "url": f"https://www.youtube.com/watch?v={vid}",
            }
        )
    return playlist_title, parsed


def _make_progress_hook(note_progress, cancel_check=None):
    def hook(d):
        if cancel_check and cancel_check():
            abort_ffmpeg()
            raise YTDownloadCancelled("download cancelled by user")
        status = d.get("status")
        if status in ("downloading", "finished"):
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            speed = d.get("speed") or 0
            eta = d.get("eta")
            note_progress(status, downloaded, total, d.get("filename", ""), speed, eta)
    return hook


def _make_postprocessor_hook(cancel_check=None):
    """Abort postprocessing (e.g. ffmpeg conversions) when the user stops."""
    def hook(_d):
        if cancel_check and cancel_check():
            abort_ffmpeg()
            raise YTDownloadCancelled("download cancelled by user")
    return hook


def download_urls(
    urls,
    output_dir: str,
    media_type: str = "Music",
    codec: str = "mp3",
    quality: str = "192",
    resolution: str = "Best",
    embed_thumbnail: bool = True,
    progress_cb=None,
    fix: str = "",
    outtmpls: dict = None,
    cookiefile: str = "",
    cancel_check=None,
):
    """Download a list of URLs into output_dir.

    media_type "Music" extracts audio (codec/quality) and "Video" downloads a
    merged MP4 at the requested resolution (bestvideo+bestaudio).

    fix enables YouTube bot-protection workarounds ("chrome"/"edge"/"firefox"
    browser cookies, "cookies.txt" file, impersonation + JS runtime always).
    cookiefile, when set, is a validated cookies.txt path and takes priority.

    outtmpls maps a url to an exact output template (used for automatic
    renames) - e.g. {"url": r"C:\\dir\\Song (2).%(ext)s"}.

    Returns (downloaded_count, errors) where errors is a list of failure messages.
    """
    os.makedirs(output_dir, exist_ok=True)
    _ensure_ffmpeg_on_path()

    is_video = media_type == "Video"
    postprocessors = [
        {
            "key": "FFmpegMetadata",
            "add_chapters": False,
        },
    ]
    if not is_video:
        postprocessors.insert(
            0,
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": quality,
            },
        )
    if embed_thumbnail:
        postprocessors.append({"key": "EmbedThumbnail"})

    opts = {
        "format": _video_format(resolution) if is_video else "bestaudio/best",
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "merge_output_format": "mp4" if is_video else None,
        "noplaylist": True,
        "writethumbnail": embed_thumbnail,
        "embedthumbnail": embed_thumbnail,
        "postprocessors": postprocessors,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_make_progress_hook(progress_cb, cancel_check)]
                if progress_cb else [],
        "postprocessor_hooks": [_make_postprocessor_hook(cancel_check)]
                if progress_cb else [],
        "retries": 5,
        "fragment_retries": 5,
        "continuedl": True,
        "noprogress": True,
        "consoletitle": False,
        "socket_timeout": 30,
    }
    if opts["merge_output_format"] is None:
        del opts["merge_output_format"]
    opts.update(_youtube_session_opts(fix, cookiefile))

    outtmpls = outtmpls or {}
    count = 0
    errors = []
    with YoutubeDL(opts) as ydl:
        for url in urls:
            try:
                if url in outtmpls:
                    ydl.params["outtmpl"]["default"] = outtmpls[url]
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


def check_missing(download_dir: str, entries):
    """Compare playlist entries with downloaded files by normalized title.

    Returns (existing_titles set, missing_entries list).
    """
    existing = _existing_titles(download_dir)

    missing = [e for e in entries if normalize_title(e["title"]) not in existing]
    return existing, missing


def scan_saved_titles(download_dir: str) -> set:
    """Re-scan the folder now and return normalized titles of saved media files."""
    return _existing_titles(download_dir)


def is_saved_match(existing: set, title: str) -> bool:
    """True if title (or a numbered 'Title (n)' variant of it) is in existing."""
    base = normalize_title(title)
    if base in existing:
        return True
    prefix = base + " ("
    for cand in existing:
        if cand.startswith(prefix) and cand.endswith(")"):
            if cand[len(prefix):-1].isdigit():
                return True
    return False