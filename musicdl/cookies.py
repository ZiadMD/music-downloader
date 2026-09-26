"""Validation of Netscape-format ``cookies.txt`` exports for YouTube.

Some YouTube videos are only served to signed-in clients. yt-dlp can supply
the session either from a ``cookies.txt`` file or straight out of a browser
profile; both routes funnel through here so the UI can tell the user *why* a
file was rejected instead of failing later with an opaque download error.
"""

import os

# yt-dlp's ``cookiesfrombrowser`` names this app offers.
BROWSERS = ("chrome", "edge", "firefox", "brave", "opera")

YOUTUBE_COOKIE_HINTS = ("youtube.com", "google.com")


def validate_cookie_file(path):
    """Validate a Netscape-format ``cookies.txt`` for YouTube/Google cookies.

    Returns ``(ok, cookie_count, youtube_cookie_count, message)`` where
    ``message`` is a human-readable explanation suitable for the log.
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

    youtube = sum(1 for d in domains if any(h in d for h in YOUTUBE_COOKIE_HINTS))
    if not count:
        msg = "the file contains no cookies"
    elif not is_netscape:
        msg = ("not a Netscape cookies.txt export - in your browser extensions, "
               "choose 'Netscape' or 'Header' format when exporting")
    elif not youtube:
        msg = ("no youtube.com / google.com cookies found - export again from "
               "the browser profile you are signed into on YouTube")
    else:
        msg = "OK"

    return bool(count) and is_netscape and bool(youtube), count, youtube, msg
