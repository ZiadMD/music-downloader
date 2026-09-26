"""Theme selection and application.

Three things live here:

* **Detecting** the OS light/dark preference on Windows, macOS and Linux.
* **Resolving** the user's choice into a concrete dark/light decision, using the
  three-state policy libadwaita uses: *System* follows the OS and stays
  overridable in either direction.
* **Applying** a theme, which means telling ttkbootstrap which bundled theme to
  load *and* then overriding the widget colours with our own token palette.

The last part matters more than it looks. ttkbootstrap's themes are the base
layer, but the app's surfaces, text and accents come from
:mod:`musicdl.ui.tokens` so the two modes are designed as a pair rather than
being one theme with inverted colours. Dark modes in particular need lighter,
less saturated accents, which a mechanical inversion gets wrong.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import ttkbootstrap as tb

from . import fonts, tokens

# User-facing theme choices. 'system' follows the OS and remains overridable;
# the other two pin the mode. This is libadwaita's PREFER_LIGHT / FORCE_LIGHT
# / FORCE_DARK matrix, which is the clearest formulation of the problem.
THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_CHOICES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)

# The bundled ttkbootstrap theme names, resolved through the token table so a
# ttkbootstrap upgrade is a one-line change. Callers should prefer
# :func:`ttk_theme` over reading these directly.
DARK = tokens.TTK_THEME["dark"]
LIGHT = tokens.TTK_THEME["light"]


def _run(cmd, timeout=3) -> str:
    """Run a short probe command and return stdout, or '' on any failure."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        ).stdout.strip()
    except Exception:
        return ""


def detect_os_theme() -> str:
    """Return the OS's light/dark preference as :data:`THEME_LIGHT` or
    :data:`THEME_DARK`.

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
            return THEME_DARK if not val else THEME_LIGHT

        if sys.platform == "darwin":
            out = _run(["defaults", "read", "-g", "AppleInterfaceStyle"])
            return THEME_DARK if out.lower() == "dark" else THEME_LIGHT

        if "dark" in (os.environ.get("GTK_THEME") or "").lower():
            return THEME_DARK
        if shutil.which("gsettings"):
            out = _run(["gsettings", "get", "org.gnome.desktop.interface",
                        "color-scheme"]).lower()
            if "dark" in out:
                return THEME_DARK
            if "light" in out:
                return THEME_LIGHT
    except Exception:
        pass
    return THEME_LIGHT


def resolve(choice: str) -> str:
    """Turn a stored theme choice into a concrete ``'light'`` or ``'dark'``.

    An unrecognised or missing value follows the OS, which is the respectful
    default on first run.
    """
    if choice in (THEME_LIGHT, THEME_DARK):
        return choice
    return detect_os_theme()


def ttk_theme(dark: bool) -> str:
    """The ttkbootstrap theme to load for a resolved mode."""
    return tokens.TTK_THEME["dark" if dark else "light"]


def is_dark(choice: str) -> bool:
    """True when a stored theme choice resolves to the dark palette."""
    return resolve(choice) == THEME_DARK


def apply(root, dark: bool) -> tb.Style:
    """Apply the resolved theme to a window and return its style.

    Two layers are set up. The ttkbootstrap theme supplies widget geometry and
    defaults; then the token palette is pushed on top for the surfaces, text
    and accents that define the app's look. The log pane is a plain
    ``tk.Text``, which ttkbootstrap does not theme at all, so it is retinted
    explicitly from the same palette.
    """
    style = tb.Style()
    style.theme_use(ttk_theme(dark))
    palette = tokens.palette(dark)

    style.configure(".", background=palette.surface,
                    foreground=palette.on_surface,
                    font=fonts.body())

    _configure_tree(style, palette)
    _configure_texts(root, palette)
    return style


def _configure_tree(style: tb.Style, palette: tokens.Palette) -> None:
    """Style the song list: opaque rows on the window surface, flat headings."""
    style.configure("Playlist.Treeview",
                    background=palette.surface,
                    fieldbackground=palette.surface,
                    foreground=palette.on_surface,
                    rowheight=tokens.ROW_HEIGHT,
                    font=fonts.body(),
                    borderwidth=0,
                    relief="flat")
    style.map("Playlist.Treeview",
              background=[("selected", palette.surface_selected)],
              foreground=[("selected", palette.on_surface)])
    style.configure("Playlist.Treeview.Heading",
                    background=palette.surface_container,
                    foreground=palette.on_surface_secondary,
                    font=fonts.caption_bold(),
                    relief="flat",
                    borderwidth=0,
                    padding=(tokens.SPACE_XS, tokens.SPACE_XS))
    style.map("Playlist.Treeview.Heading",
              background=[("active", palette.surface_hover)])


def _configure_texts(root, palette: tokens.Palette) -> None:
    """Retint plain ``tk.Text`` widgets, which ttkbootstrap cannot reach.

    Widgets register themselves on ``root._musicdl_text_widgets``.
    """
    for text in getattr(root, "_musicdl_text_widgets", ()):
        try:
            text.config(
                background=palette.surface_sunken,
                foreground=palette.on_surface_secondary,
                insertbackground=palette.on_surface,
                selectbackground=palette.selection,
                selectforeground=palette.on_surface,
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
            )
        except Exception:
            # A widget already destroyed must not stop the theme from being
            # applied to the rest of the window.
            pass
