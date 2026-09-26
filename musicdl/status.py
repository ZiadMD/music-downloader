"""Row status: turning a status phrase into a glyph, a word and a colour role.

This is the one piece of song-list logic that both toolkits must agree on
exactly, so it lives in neither. The Tk list and the Qt list both call
:func:`describe`, and a test asserts the two produce identical output - a
divergence here would mean a status that reads one way in one UI and another
way in the other, which is worse than either being wrong alone.

Three things come out of a status:

* a **semantic role** (``ok`` / ``busy`` / ``missing`` / ``muted``), which is
  what the colour is looked up from, so the two themes can pick different
  values for the same meaning
* a **glyph**, so the state is legible without colour vision
* a **word**, so it is unambiguous rather than merely distinguishable

Colour is never the only signal. Neither is the glyph, and neither is the
word. Two of the three would be redundant; all three together are what make
the list usable in a dark room, on a bad monitor, and with any colour vision
deficiency.
"""

from __future__ import annotations

from .ui.tokens import STATUS_ICONS

__all__ = ["describe", "StatusView", "role_for", "glyph_key", "is_terminal_failure"]

# Maps a status word onto a semantic role. The keys are the phrases that
# actually reach the UI; the roles are the four colour questions that matter.
ROLES = {
    "ok": "ok",
    "downloaded": "ok",
    "skipped": "ok",
    "missing": "missing",
    "failed": "missing",
    "unavailable": "missing",
    "downloading": "busy",
    "waiting": "busy",
    "pending": "busy",
    # The neutral default: a row nobody has examined yet.
    "not": "muted",
    "new": "muted",
}

# Phrases that resolve to a colour role but still need their own glyph.
#
# The role drives the colour; the glyph is a separate question. "Downloaded"
# and "Skipped" are both `ok` - the same good outcome - but they are not the
# same event, and giving them the same glyph made a deliberately skipped song
# indistinguishable from a downloaded one at a glance. The word in the
# tooltip still carried the difference, but the column exists to be scanned,
# not read. So roles may be shared while glyphs stay distinct.
GLYPH_OVERRIDES = {
    "skipped": "skipped",
    "unavailable": "unavailable",
    "failed": "failed",
}


class StatusView:
    """A resolved status: what to draw, and which token role to draw it in."""

    __slots__ = ("role", "glyph", "word", "text")

    def __init__(self, role: str, glyph: str, word: str, text: str) -> None:
        self.role = role
        self.glyph = glyph
        self.word = word
        self.text = text

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StatusView):
            return NotImplemented
        return (self.role, self.glyph, self.word,
                self.text) == (other.role, other.glyph, other.word, other.text)

    def __hash__(self) -> int:
        return hash((self.role, self.glyph, self.word, self.text))

    def __repr__(self) -> str:
        return (f"StatusView(role={self.role!r}, glyph={self.glyph!r}, "
                f"word={self.word!r})")


def role_for(phrase: str) -> str:
    """The semantic role for a status phrase.

    Phrases arrive in three shapes: a bare word ("Failed"), a word with an
    ellipsis ("Waiting..."), and a word with a live reading ("Downloading
    42% · 1.4 MiB/s"). Matching on the first whitespace-delimited token
    handles all three, but the trailing punctuation has to come off first or
    "Downloading..." never matches its own key.
    """
    first = (phrase or "").split(" ", 1)[0].lower().rstrip(".…")
    return ROLES.get(first, "muted")


def glyph_key(phrase: str) -> str:
    """The token key a status phrase's glyph is looked up under.

    This is the *key*, not the character: ``skipped``, ``ok``, ``busy`` and so
    on. Callers that need to draw the glyph rather than set it as text - Qt,
    which draws shapes because the UI font has none of the status characters -
    need the key so they can map it to their own drawing. Tk needs the
    character and gets it from :func:`describe`.

    Exposed rather than kept private so the phrase parsing happens once. When
    the delegate had its own copy, a test guarding the glyph lookup passed
    against a model using the shared helper and a delegate that had silently
    diverged from it - the guard was testing the copy.
    """
    first = (phrase or "").split(" ", 1)[0].lower().rstrip(".…")
    return GLYPH_OVERRIDES.get(first, ROLES.get(first, "muted"))


def describe(phrase: str) -> StatusView:
    """Resolve a raw status phrase into a glyph, a word and a colour role.

    The glyph is prepended here rather than at the call site, so it is never
    doubled up when a status is set twice, and so both toolkits render the
    identical string.
    """
    role = role_for(phrase)
    # The glyph is looked up by the specific phrase where one exists, and
    # falls back to the role's glyph. See GLYPH_OVERRIDES for why those
    # differ from the role.
    key = glyph_key(phrase)
    # Keep the live reading if there is one: "Downloading 42% · 1.4 MiB/s" is
    # more useful than "Downloading", and the column is sized for the worst
    # case so it never reflows.
    text = (phrase or "").strip() or "Not downloaded"
    word = text.split(" ", 1)[-1] if " " in text else text
    return StatusView(role, STATUS_ICONS.get(key, STATUS_ICONS["muted"]),
                      word, text)


def is_terminal_failure(phrase: str) -> bool:
    """True for states that will not change on their own.

    Used to decide whether a refresh may overwrite a row: a row that is
    downloading, or that failed in a way the user might retry, should not be
    quietly reset by a background status check.
    """
    return role_for(phrase) in ("busy", "missing")
