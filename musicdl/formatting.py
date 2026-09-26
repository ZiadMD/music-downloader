"""Human-readable formatting for byte counts, transfer rates and durations.

Pure presentation helpers, kept out of the UI layer so they are testable
without constructing a Tk window.
"""


def fmt_bytes(n) -> str:
    """Format a byte count, e.g. ``'4.2 MB'``. Unparseable input -> ``'0 B'``."""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "0 B"
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.0f} KB"
    return f"{int(n)} B"


def fmt_speed(bps) -> str:
    """Format a transfer rate, e.g. ``'1.4 MiB/s'``. Unknown -> ``'--'``."""
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


def fmt_eta(seconds) -> str:
    """Format a duration in seconds as ``M:SS`` or ``H:MM:SS``."""
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        return "--"
    if seconds <= 0:
        return "--"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def plural(n: int, singular: str, plural_form: str = "") -> str:
    """``plural(1, 'song') -> '1 song'``; ``plural(3, 'song') -> '3 songs'``."""
    word = singular if n == 1 else (plural_form or singular + "s")
    return f"{n} {word}"
