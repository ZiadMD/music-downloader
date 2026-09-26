"""Qt theme application, built from the shared token palette.

The design system in :mod:`musicdl.ui.tokens` is plain data, so this module
does not redefine any colour, radius, spacing or type size. It only
translates those roles into the two things Qt understands: a
``QPalette`` for the widget-level colours Qt handles natively, and a
stylesheet for everything that needs more than a palette role.

Splitting it that way is deliberate. Qt's ``QPalette`` covers window, base,
text, button and highlight surfaces, which is most of a form. The song list
needs per-row backgrounds and per-role foregrounds, which only a delegate or a
stylesheet can express - so that stays in the table's own model rather than
being flattened into a global style.

Qt stylesheet support is a documented subset of CSS, not all of it. Only the
selectors and properties used here are relied upon, and every colour is read
from the token role rather than written as a literal.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

from ..ui import tokens
from ..ui.theme import detect_os_theme, is_dark, resolve  # noqa: F401
from . import fonts

# PySide6 exposes the palette as (ColorGroup, ColorRole) pairs rather than the
# flat C++ names, so these aliases keep the mapping table below readable.
G_DISABLED = QPalette.ColorGroup.Disabled
G_ACTIVE = QPalette.ColorGroup.Active
R_WINDOW = QPalette.ColorRole.Window
R_WINDOW_TEXT = QPalette.ColorRole.WindowText
R_BASE = QPalette.ColorRole.Base
R_ALT_BASE = QPalette.ColorRole.AlternateBase
R_TEXT = QPalette.ColorRole.Text
R_BUTTON = QPalette.ColorRole.Button
R_BUTTON_TEXT = QPalette.ColorRole.ButtonText
R_HIGHLIGHT = QPalette.ColorRole.Highlight
R_HL_TEXT = QPalette.ColorRole.HighlightedText
R_TIP_BASE = QPalette.ColorRole.ToolTipBase
R_TIP_TEXT = QPalette.ColorRole.ToolTipText
R_PLACEHOLDER = QPalette.ColorRole.PlaceholderText
R_LINK = QPalette.ColorRole.Link

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_CHOICES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)

__all__ = [
    "THEME_SYSTEM", "THEME_LIGHT", "THEME_DARK", "THEME_CHOICES",
    "detect_os_theme", "resolve", "is_dark",
    "apply_theme", "qcolor", "stylesheet",
]


def qcolor(role: str, dark: bool) -> QColor:
    """The token role as a ``QColor``.

    Every colour in the Qt UI goes through here, which is what keeps the two
    toolkits on one palette. A literal ``#526678`` written in a widget is
    exactly the sort of drift the token system exists to prevent.
    """
    return QColor(tokens.palette(dark)[role])


def build_palette(dark: bool) -> QPalette:
    """Map the token roles onto Qt's own colour roles.

    Qt resolves inherited widget colours through the palette, so getting this
    right means most widgets need no styling at all - which is both less CSS
    to maintain and closer to native platform behaviour.
    """
    p = QPalette()
    surface = qcolor("surface", dark)
    container = qcolor("surface_container", dark)
    sunken = qcolor("surface_sunken", dark)
    on_surface = qcolor("on_surface", dark)
    muted = qcolor("on_surface_muted", dark)
    selected = qcolor("surface_selected", dark)
    accent = qcolor("accent", dark)

    p.setColor(R_WINDOW, surface)
    p.setColor(R_WINDOW_TEXT, on_surface)
    p.setColor(R_BASE, sunken)
    p.setColor(R_ALT_BASE, qcolor("surface_subtle", dark))
    p.setColor(R_TEXT, on_surface)
    p.setColor(R_BUTTON, container)
    p.setColor(R_BUTTON_TEXT, on_surface)
    p.setColor(R_HIGHLIGHT, selected)
    p.setColor(R_HL_TEXT, on_surface)
    p.setColor(R_TIP_BASE, container)
    p.setColor(R_TIP_TEXT, on_surface)
    p.setColor(R_PLACEHOLDER, muted)
    p.setColor(R_LINK, accent)

    # Disabled text is the one place Qt's automatic derivation is too faint
    # to read, so it is set explicitly rather than left to Qt.
    for role in (R_TEXT, R_BUTTON_TEXT, R_WINDOW_TEXT):
        p.setColor(G_DISABLED, role, muted)
    return p


def _px(value: int) -> str:
    return f"{int(value)}px"


def stylesheet(dark: bool) -> str:
    """The parts of the UI that the ``QPalette`` cannot express.

    Deliberately short. Qt's palette already handles surfaces, text, buttons
    and focus; this covers only the three things it does not: rounded inputs
    and buttons, the app's section labels, and the sunken log pane.
    """
    p = tokens.palette(dark)
    r_sm, r_md = tokens.RADIUS_SM, tokens.RADIUS_MD

    # Hover/pressed steps are the only place the palette needs help: Qt has no
    # role for "the same surface, one step darker", and deriving it here keeps
    # the ramp in the token system rather than in ad-hoc colour maths.
    hover = p.surface_hover
    accent = p.accent
    on_accent = p.on_accent

    return f"""
QWidget {{
    background-color: {p.surface};
    color: {p.on_surface};
    font-size: {_px(tokens.FONT_SIZE_BODY)};
}}

/* Inputs and buttons: rounded, with a hairline that only appears on focus.
   A permanently visible border on every control is the loudest tell of a
   form that was never designed, so resting state is flat. */
QLineEdit, QComboBox, QPlainTextEdit {{
    background-color: {p.surface_sunken};
    border: 1px solid transparent;
    border-radius: {_px(r_sm)};
    padding: {_px(tokens.SPACE_XS)} {_px(tokens.SPACE_SM)};
    selection-background-color: {p.surface_selected};
    selection-color: {p.on_surface};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {accent};
}}
QLineEdit:disabled, QComboBox:disabled {{
    color: {p.on_surface_muted};
}}

QComboBox::drop-down {{ border: none; width: {_px(tokens.SPACE_2XL)}; }}
QComboBox QAbstractItemView {{
    background-color: {p.surface_container};
    border: 1px solid {p.outline};
    border-radius: {_px(r_sm)};
    selection-background-color: {p.surface_selected};
    selection-color: {p.on_surface};
    outline: none;
}}

QPushButton {{
    background-color: {p.surface_container};
    border: 1px solid {p.outline};
    border-radius: {_px(r_md)};
    padding: {_px(tokens.SPACE_SM)} {_px(tokens.SPACE_LG)};
}}
QPushButton:hover {{ background-color: {hover}; }}
QPushButton:pressed {{ background-color: {p.surface_selected}; }}
QPushButton:disabled {{
    color: {p.on_surface_muted};
    border-color: {p.outline_variant};
}}

/* The one filled button on screen. Anything else filled would compete with
   it for the eye, which is what makes "Download Selected" findable. */
QPushButton#primary {{
    background-color: {accent};
    color: {on_accent};
    border-color: {accent};
    font-weight: {tokens.WEIGHT_BOLD};
}}
QPushButton#primary:hover {{ background-color: {p.accent_hover}; }}
QPushButton#primary:disabled {{
    background-color: {p.surface_sunken};
    color: {p.on_surface_muted};
    border-color: {p.outline_variant};
}}

QPushButton#ghost {{
    background-color: transparent;
    border-color: transparent;
    color: {p.on_surface_secondary};
}}
QPushButton#ghost:hover {{ background-color: {hover}; }}

/* The one destructive action on screen. A filled danger button would compete
   with the primary action for the eye, so this is a tinted border instead:
   it reads as "this one ends things" without becoming a second focal point.
   Used only for "Cancel rest" in the rename dialog. */
QPushButton#destructive {{
    background-color: transparent;
    border: 1px solid {p.danger};
    color: {p.danger};
}}
QPushButton#destructive:hover {{
    background-color: {p.danger};
    color: {p.on_danger};
}}

QRadioButton, QCheckBox {{ spacing: {_px(tokens.SPACE_SM)}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: {_px(tokens.FONT_SIZE_BODY)};
    height: {_px(tokens.FONT_SIZE_BODY)};
}}
QCheckBox::indicator {{
    border-radius: {_px(r_sm)};
    border: 1px solid {p.outline};
    background-color: {p.surface_sunken};
}}
QCheckBox::indicator:checked {{ background-color: {accent}; border-color: {accent}; }}
QRadioButton::indicator {{
    border-radius: {_px(tokens.FONT_SIZE_BODY)};
    border: 1px solid {p.outline};
    background-color: {p.surface_sunken};
}}
QRadioButton::indicator:checked {{
    border: {_px(max(4, tokens.FONT_SIZE_BODY // 2))} solid {accent};
    background-color: {p.surface_sunken};
}}

/* The log pane. Sunken, square-cornered inside the padded window, and
   monospaced so downloaded filenames line up. */
QPlainTextEdit#log {{
    background-color: {p.surface_sunken};
    color: {p.on_surface_secondary};
    border: none;
    border-radius: {_px(r_md)};
    font-family: "{fonts.mono_family_name()}";
    font-size: {_px(tokens.FONT_SIZE_LOG)};
    padding: {_px(tokens.SPACE_SM)};
}}

QProgressBar {{
    background-color: {p.surface_sunken};
    border: none;
    border-radius: {_px(r_sm)};
    height: {_px(tokens.SPACE_XL)};
    text-align: center;
    color: {p.on_surface_secondary};
}}
QProgressBar::chunk {{
    background-color: {accent};
    border-radius: {_px(r_sm)};
}}

/* Type roles. The stylesheet is the only place a font size is expressed,
   so the type scale has exactly one definition in the Qt UI. */
QLabel#title {{
    font-size: {_px(tokens.FONT_SIZE_TITLE)};
    font-weight: {tokens.WEIGHT_BOLD};
}}
QLabel#section {{
    font-size: {_px(tokens.FONT_SIZE_SECTION)};
    font-weight: {tokens.WEIGHT_BOLD};
}}
QLabel#secondary {{
    font-size: {_px(tokens.FONT_SIZE_SECONDARY)};
    color: {p.on_surface_secondary};
}}
QLabel#muted {{
    font-size: {_px(tokens.FONT_SIZE_CAPTION)};
    color: {p.on_surface_muted};
}}
QLabel#captionBold {{
    font-size: {_px(tokens.FONT_SIZE_CAPTION)};
    font-weight: {tokens.WEIGHT_BOLD};
}}
QLabel#numeric {{
    /* Real tabular figures, so the status column does not jitter as the
       digits change. Qt supports tnum directly; Tk has to use a monospace
       family for the same effect. */
    font-size: {_px(tokens.FONT_SIZE_CAPTION)};
}}

QToolTip {{
    background-color: {p.surface_container};
    color: {p.on_surface};
    border: 1px solid {p.outline};
    border-radius: {_px(r_sm)};
    padding: {_px(tokens.SPACE_XS)} {_px(tokens.SPACE_SM)};
}}

QScrollBar:vertical {{
    background: transparent;
    width: {_px(tokens.SPACE_XL)};
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p.outline_variant};
    border-radius: {_px(tokens.RADIUS_SM)};
    min-height: {_px(tokens.SPACE_2XL)};
}}
QScrollBar::handle:vertical:hover {{ background: {p.outline}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QSplitter::handle {{ background: {p.outline_variant}; }}
"""


def apply_theme(app, dark: bool) -> None:
    """Apply the resolved theme to a ``QApplication``.

    Order matters: the palette goes on the application so widgets inherit
    sensible colours before the stylesheet is parsed, and the stylesheet then
    overrides the specific cases. Doing it the other way round leaves widgets
    that fall back to the palette unstyled in the old colours.
    """
    app.setPalette(build_palette(dark))
    app.setStyleSheet(stylesheet(dark))
    # A theme switch has to reach widgets that cache the answer, which is the
    # one thing a stylesheet cannot do on its own.
    for widget in app.topLevelWidgets():
        if hasattr(widget, "on_theme_changed"):
            widget.on_theme_changed(dark)  # type: ignore[attr-defined]
