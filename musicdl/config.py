"""Loading, validating and persisting the app's settings.

The settings file is user-owned state, so everything read from disk is treated
as untrusted: unknown keys are dropped, values outside the allowed set fall
back to defaults, and an ``output_dir`` pointing at a path that no longer
exists (a stale absolute path from another machine) is replaced. Saves are
best-effort - a read-only install directory must not crash the app.
"""

import json
import os

from . import paths

THEMES = ("dark", "light")


def _defaults() -> dict:
    return {
        "last_url": "",
        "output_dir": "",
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


def _clamp_jobs(value) -> int:
    """Coerce a stored job count into the 1-6 range the UI allows.

    ``None`` means 'never set', so it falls back to the default; an explicit
    ``0`` is clamped up to 1 rather than treated as missing.
    """
    if value is None or value == "":
        return 3
    try:
        return max(1, min(int(value), 6))
    except (TypeError, ValueError):
        return 3


def load() -> dict:
    """Load settings, carrying over a legacy config and repairing bad values."""
    for moved in paths.migrate_legacy_files():
        print(f"Moved existing settings to: {moved}")

    cfg = _defaults()
    try:
        with open(paths.config_file(), "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            cfg.update(loaded)
    except (OSError, ValueError):
        pass

    # A saved output_dir can point at a folder that no longer exists, or one
    # from a different machine entirely; fall back rather than fail later.
    out = (cfg.get("output_dir") or "").strip()
    if not out or not os.path.isdir(os.path.expanduser(out)):
        cfg["output_dir"] = paths.default_download_dir()

    from . import core  # imported late: core imports this module's siblings

    if cfg.get("format") not in core.AUDIO_FORMATS:
        cfg["format"] = "MP3"
    if cfg.get("quality") not in core.QUALITIES:
        cfg["quality"] = "192"
    if cfg.get("resolution") not in core.VIDEO_RESOLUTIONS:
        cfg["resolution"] = "Best"
    if cfg.get("media") not in core.MEDIA_TYPES:
        cfg["media"] = "Music"

    if cfg.get("theme") not in THEMES:
        cfg["theme"] = "dark"
    cfg["thumbnail"] = bool(cfg.get("thumbnail", True))
    cfg["parallel"] = bool(cfg.get("parallel", False))
    cfg["parallel_jobs"] = _clamp_jobs(cfg.get("parallel_jobs"))
    cfg["last_url"] = (cfg.get("last_url") or "").strip()
    cfg["cookie_path"] = (cfg.get("cookie_path") or "").strip()
    return cfg


def save(cfg: dict) -> None:
    """Write settings to disk. Silently ignores a read-only location."""
    try:
        with open(paths.config_file(), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except OSError:
        pass
