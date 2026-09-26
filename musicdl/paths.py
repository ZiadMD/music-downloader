"""Cross-platform application paths and environment discovery.

Every filesystem location the app touches is resolved here, so nothing is
hardcoded to a particular OS, user name, or install directory. Three
categories of path are covered:

- **Application config** (settings)  -> per-user config dir
- **Application data** (cookies)     -> per-user data dir
- **Downloads**                      -> the user's Music folder

Writes also handle the read-only case of a Program Files install: if the
directory next to the executable is not writable, settings and cookies fall
back to the per-user directories above instead of failing silently.
"""

import os
import shutil
import sys

APP_NAME = "music-downloader"
APP_NAME_PRETTY = "Music Downloader"

# Legacy layout: config.json and cookies.txt were kept beside the script or the
# frozen executable. Used to migrate existing users on first run.
_LEGACY_NAMES = ("config.json", "cookies.txt")


# --------------------------------------------------------------- platform bits
def is_frozen() -> bool:
    """True when running from a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False))


def is_windows() -> bool:
    return os.name == "nt"


def resource_dir() -> str:
    """Directory containing bundled read-only resources (icon, data files)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def _writable(path: str) -> bool:
    """True if we can actually create/write inside ``path`` (created if needed)."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _base_dir() -> str:
    """Best writable base for app-owned data.

    Order matters:
      1. The OS per-user config directory, so state never accumulates inside
         the source tree (a side effect of running from a checkout) or the
         package directory.
      2. A folder beside the executable, so a portable install stays
         self-contained. Skipped when frozen on a read-only location such as
         Program Files, which is what makes the portable form opt-in.
    """
    candidates = [user_config_dir(), user_data_dir()]
    if is_frozen():
        candidates.append(os.path.dirname(sys.executable))
    candidates.append(os.path.join(os.path.expanduser("~"), f".{APP_NAME}"))
    for cand in candidates:
        if cand and _writable(cand):
            return cand
    return os.path.expanduser("~")


def resolve_user_path(raw: str | None, fallback: str = "") -> str:
    """Expand ``~`` and environment variables in a user-supplied path.

    Returns ``fallback`` when ``raw`` is empty, so callers always get a usable
    directory rather than having to re-check for blanks.
    """
    raw = (raw or "").strip()
    if not raw:
        return fallback
    return os.path.expanduser(os.path.expandvars(raw))


# ------------------------------------------------------------- user directories
def user_config_dir() -> str:
    """Per-user configuration directory for this app."""
    if is_windows():
        base = (os.environ.get("APPDATA")
                or os.path.join(os.path.expanduser("~"), "AppData", "Roaming"))
        return os.path.join(base, APP_NAME_PRETTY)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", APP_NAME_PRETTY)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME)


def user_data_dir() -> str:
    """Per-user data directory for this app (cookies, logs, caches)."""
    if is_windows():
        base = (os.environ.get("LOCALAPPDATA")
                or os.path.join(os.path.expanduser("~"), "AppData", "Local"))
        return os.path.join(base, APP_NAME_PRETTY)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", APP_NAME_PRETTY)
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_NAME)


def home_dir() -> str:
    return os.path.expanduser("~")


def default_download_dir() -> str:
    """Where downloads go when the user has not chosen a folder.

    Uses the OS music folder when we can find it, else ``~/Music/Playlists``.
    """
    if is_windows():
        for env in ("USERPROFILE",):
            home = os.environ.get(env)
            if home:
                return os.path.join(home, "Music", "Playlists")
    if sys.platform == "darwin":
        return os.path.join(home_dir(), "Music", "Playlists")
    base = os.environ.get("XDG_MUSIC_DIR")
    if not base:
        cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            home_dir(), ".config")
        base = _read_xdg_music_dir(cfg) or os.path.join(home_dir(), "Music")
    return os.path.join(base, "Playlists")


def _read_xdg_music_dir(user_config_root: str) -> str:
    """Parse ``~/.config/user-dirs.dirs`` for the configured music folder."""
    try:
        path = os.path.join(user_config_root, "user-dirs.dirs")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line.startswith("XDG_MUSIC_DIR"):
                    continue
                value = line.split("=", 1)[-1].strip().strip('"')
                value = value.replace("$HOME", home_dir())
                if value:
                    return value
    except OSError:
        pass
    return ""


# ------------------------------------------------------------------ app files
def config_file() -> str:
    """Path to the settings JSON file."""
    return os.path.join(_base_dir(), "config.json")


def cookies_file() -> str:
    """Path to the Netscape ``cookies.txt`` the app reads by default."""
    return os.path.join(_base_dir(), "cookies.txt")


def resource_path(name: str) -> str:
    """Path to a bundled read-only resource such as the app icon."""
    return os.path.join(resource_dir(), name)


def legacy_files() -> list:
    """Old app-owned files that may exist beside the script/executable."""
    base = (os.path.dirname(sys.executable) if is_frozen()
            else os.path.dirname(os.path.abspath(__file__)))
    return [os.path.join(base, name) for name in _LEGACY_NAMES]


def migrate_legacy_files() -> list:
    """Move legacy config/cookies next to the script into the app directory.

    Returns the list of destination paths that were written, so the caller can
    tell the user their settings were carried over. Never overwrites a file
    that already exists at the new location.
    """
    moved = []
    target_dir = _base_dir()
    os.makedirs(target_dir, exist_ok=True)
    for src in legacy_files():
        dst = os.path.join(target_dir, os.path.basename(src))
        if not os.path.isfile(src) or os.path.abspath(src) == os.path.abspath(dst):
            continue
        if os.path.exists(dst):
            continue
        try:
            shutil.move(src, dst)
            moved.append(dst)
        except OSError:
            pass
    return moved


# ------------------------------------------------------------ external tools
def ffmpeg_candidates() -> list:
    """Every directory that might hold an ffmpeg binary, in priority order.

    Works on Windows (winget / Chocolatey / manual), macOS (Homebrew) and
    Linux (distro packages) instead of assuming a single Windows layout.
    """
    dirs = []
    if is_windows():
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            winget = os.path.join(local, "Microsoft", "WinGet", "Packages")
            if os.path.isdir(winget):
                try:
                    for pkg in sorted(os.listdir(winget)):
                        # winget layout: <winget>/<pkg>/ffmpeg-<ver>-full_build/bin
                        pkg_dir = os.path.join(winget, pkg)
                        for sub in sorted(os.listdir(pkg_dir)):
                            if sub.lower().startswith("ffmpeg"):
                                dirs.append(os.path.join(pkg_dir, sub, "bin"))
                except OSError:
                    pass
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env)
            if base:
                dirs.append(os.path.join(base, "ffmpeg", "bin"))
                dirs.append(os.path.join(base, "ffmpeg"))
        choco = os.environ.get("ChocolateyInstall")
        if choco:
            dirs.append(os.path.join(choco, "bin"))
    elif sys.platform == "darwin":
        for base in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"):
            dirs.append(base)
    else:
        for base in ("/usr/local/bin", "/usr/bin", "/bin", "/snap/bin"):
            dirs.append(base)
    return [d for d in dirs if os.path.isdir(d)]


def find_ffmpeg_dir() -> str:
    """Return a directory containing an ffmpeg binary, or '' if none found."""
    try:
        if shutil.which("ffmpeg"):
            return ""
    except Exception:
        pass
    exe = "ffmpeg.exe" if is_windows() else "ffmpeg"
    for d in ffmpeg_candidates():
        if os.path.isfile(os.path.join(d, exe)):
            return d
    return ""


def node_candidates() -> list:
    """Directories that may hold a ``node`` binary (needed for YouTube's JS)."""
    dirs = []
    if is_windows():
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env)
            if base:
                dirs.append(os.path.join(base, "nodejs"))
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            dirs.append(os.path.join(local, "Programs", "nodejs"))
            dirs.append(os.path.join(local, "Volta", "bin"))
            dirs.append(os.path.join(local, "fnm_multishells"))
        appdata = os.environ.get("APPDATA")
        if appdata:
            dirs.append(os.path.join(appdata, "nvm"))
            dirs.append(os.path.join(appdata, "Volta", "bin"))
    else:
        for base in ("/usr/local/bin", "/usr/bin", "/bin", "/opt/homebrew/bin"):
            dirs.append(base)
        nvm = os.path.join(home_dir(), ".nvm", "versions", "node")
        if os.path.isdir(nvm):
            try:
                for ver in sorted(os.listdir(nvm), reverse=True):
                    dirs.append(os.path.join(nvm, ver, "bin"))
            except OSError:
                pass
        fnm = os.path.join(home_dir(), ".local", "share", "fnm", "node-versions")
        if os.path.isdir(fnm):
            try:
                for ver in sorted(os.listdir(fnm), reverse=True):
                    dirs.append(os.path.join(fnm, ver, "installation", "bin"))
            except OSError:
                pass
        volta = os.path.join(home_dir(), ".volta", "bin")
        if os.path.isdir(volta):
            dirs.append(volta)
    return [d for d in dirs if os.path.isdir(d)]


def find_node() -> str:
    """Return the full path to a ``node`` executable, or '' if not found."""
    try:
        exe = shutil.which("node")
        if exe:
            return exe
    except Exception:
        pass
    name = "node.exe" if is_windows() else "node"
    for d in node_candidates():
        full = os.path.join(d, name)
        if os.path.isfile(full):
            return full
    return ""
