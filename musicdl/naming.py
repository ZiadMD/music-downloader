"""Filename/title normalization and safe-path helpers.

Two related but distinct concerns live here:

- :func:`sanitize_folder_name` / :func:`safe_stem` produce *filesystem* names.
- :func:`normalize_title` produces a *comparison* key used to match a playlist
  entry against files already on disk.

They differ because yt-dlp rewrites characters Windows forbids (``"`` -> ``＂``,
``/`` -> ``⧸``) when it saves a file, so a naive lowercase comparison would not
match. :func:`normalize_title` folds those substitutions back to ASCII so a
playlist title lines up with the name yt-dlp actually wrote.
"""

import os
import re
import unicodedata

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

# Extensions this app produces as finished songs; anything else sharing a stem
# is a leftover source file (e.g. the raw '.webm' behind an MP3 conversion).
FINAL_MEDIA_EXTS = (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".mp4")

# Full-width / CJK look-alike glyphs yt-dlp substitutes for illegal characters.
# NFKC leaves the big solidus untouched, so those are mapped manually.
_GLYPH_MAP = {
    "⧸": "/",   # big solidus
    "⧹": "\\",  # reversed big solidus
    "꞉": ":",   # modifier letter colon
    "／": "/",   # fullwidth solidus
    "＼": "\\",  # fullwidth reverse solidus
}

# Characters Windows forbids, plus the '#' yt-dlp uses as its replacement.
_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*#]')

# Reserved device names on Windows; a file called 'CON.mp3' is unusable.
_WIN_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

MAX_NAME_LEN = 120


def sanitize_folder_name(name: str) -> str:
    """Turn a playlist title into a safe folder name."""
    name = _ILLEGAL_RE.sub("", name or "").strip().rstrip(".")
    name = name[:MAX_NAME_LEN].strip().rstrip(".")
    if name.lower() in _WIN_RESERVED:
        name = f"_{name}"
    return name or "playlist"


def normalize_title(name: str | None) -> str:
    """Normalize a title into a comparison key for matching saved files.

    Lowercases, folds full-width look-alikes back to ASCII, strips the
    characters Windows removes from file names, and collapses whitespace. So
    ``'Artist - Song (Official Video)'`` matches the name on disk regardless
    of which illegal glyphs yt-dlp substituted in.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name)
    for glyph, ascii_char in _GLYPH_MAP.items():
        s = s.replace(glyph, ascii_char)
    s = _ILLEGAL_RE.sub("", s.lower())
    return " ".join(s.split())


def safe_stem(name: str) -> str:
    """Turn a song title into a filesystem-safe stem with no path separators.

    Uses yt-dlp's own sanitizer so names look exactly like the titles instead
    of being mangled differently, and guarantees no ``/`` or ``\\`` can become
    a path separator when the stem is joined into an output path.
    """
    from yt_dlp.utils import sanitize_filename

    stem = sanitize_filename(name or "")[:MAX_NAME_LEN].rstrip(" .")
    if stem.lower() in _WIN_RESERVED:
        stem = f"_{stem}"
    return stem or "song"


def is_image_file(name: str) -> bool:
    return name.lower().endswith(IMAGE_EXTS)


def is_partial_file(name: str) -> bool:
    """True for leftover download fragments that never become finished songs."""
    low = name.lower()
    return low.endswith((".part", ".ytdl")) or ".temp" in low


def existing_titles(download_dir: str) -> set:
    """Normalized titles of all finished media files under ``download_dir``."""
    found = set()
    for _root, _dirs, files in os.walk(download_dir):
        for f in files:
            if is_image_file(f) or is_partial_file(f):
                continue
            found.add(normalize_title(os.path.splitext(f)[0]))
    return found


def title_file_exists(directory: str, title: str) -> bool:
    """True if any file in ``directory`` has the same normalized name as ``title``."""
    target = normalize_title(title)
    if not target:
        return False
    try:
        names = os.listdir(directory)
    except OSError:
        return False
    for f in names:
        if is_image_file(f):
            continue
        if normalize_title(os.path.splitext(f)[0]) == target:
            return True
    return False


def unique_stem(directory: str, base_title: str, reserved=()) -> str:
    """Return a non-colliding file stem (no extension) for ``base_title``.

    ``reserved`` is an extra set of stems treated as already taken, so two
    parallel downloads of same-titled songs never pick the same filename.
    """
    reserved = {s.lower() for s in (reserved or ())}
    base = safe_stem(os.path.splitext(base_title)[0])
    stem = base
    target = normalize_title(base)
    i = 2
    while True:
        clash = stem.lower() in reserved
        if not clash:
            try:
                names = os.listdir(directory)
            except OSError:
                names = []
            for f in names:
                if is_image_file(f):
                    continue
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


def is_saved_match(existing: set, title: str) -> bool:
    """True if ``title`` (or a numbered ``Title (n)`` variant) is in ``existing``."""
    base = normalize_title(title)
    if base in existing:
        return True
    prefix = base + " ("
    return any(
        c.startswith(prefix) and c.endswith(")") and c[len(prefix):-1].isdigit()
        for c in existing
    )
