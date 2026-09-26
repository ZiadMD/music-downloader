"""Theme selection: OS preference detection plus the app's colour palette."""

import os
import shutil
import subprocess
import sys

import ttkbootstrap as tb

# ttkbootstrap theme names used by the app.
DARK = "darkly"
LIGHT = "litera"


def _run(cmd, timeout=3) -> str:
    """Run a short probe command and return stdout, or '' on any failure."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        ).stdout.strip()
    except Exception:
        return ""


def detect_os_theme() -> str:
    """Return the OS's light/dark preference as a ttkbootstrap theme name.

    Reads the Windows personalisation registry key, the macOS
    ``AppleInterfaceStyle`` default, or the freedesktop/GTK colour-scheme
    setting, falling back to light when nothing is declared.
    """
    try:
        if os.name == "nt":
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return LIGHT if val else DARK

        if sys.platform == "darwin":
            out = _run(["defaults", "read", "-g", "AppleInterfaceStyle"])
            return DARK if out.lower() == "dark" else LIGHT

        if "dark" in (os.environ.get("GTK_THEME") or "").lower():
            return DARK
        if shutil.which("gsettings"):
            out = _run(["gsettings", "get", "org.gnome.desktop.interface",
                        "color-scheme"]).lower()
            if "dark" in out:
                return DARK
            if "light" in out:
                return LIGHT
    except Exception:
        pass
    return LIGHT


def is_dark_name(theme: str) -> bool:
    return theme == "dark"


def _color(colors, name, fallback):
    """Read a colour off the active palette, falling back when absent."""
    value = getattr(colors, name, None)
    return value or fallback


def apply(root, dark: bool) -> tb.Style:
    """Apply the requested theme to a ttkbootstrap window and return its style.

    tk.Text widgets are not themed by ttkbootstrap, so any the app registered
    on ``root._musicdl_text_widgets`` are retinted to match here.
    """
    style = tb.Style()
    style.theme_use(DARK if dark else LIGHT)
    colors = style.colors
    bg = _color(colors, "bg", "#1e1e1e" if dark else "#ffffff")
    fg = _color(colors, "fg", "#ffffff" if dark else "#000000")
    select_bg = _color(colors, "selectbg", bg)
    for text in getattr(root, "_musicdl_text_widgets", ()):
        try:
            text.config(bg=bg, fg=fg, insertbackground=fg, selectbackground=select_bg)
        except Exception:
            pass
    return style
