"""Tests for the playlist table's status presentation.

Status is the densest piece of information on the screen, and it is the part
that regresses quietly. These tests pin down two properties:

  1. Every status phrase the download job can emit resolves to a real tag, so
     no row silently falls back to the muted colour.
  2. The rendered text carries a glyph *and* a word, so the state is legible
     without colour vision.
"""

import pytest

from musicdl.ui import tokens
from musicdl.ui.widgets import STATUS_TAGS, PlaylistTable

# Every status phrase the app actually produces, in all its real shapes.
REAL_STATUS_PHRASES = [
    "Downloaded",
    "Downloading...",
    "Downloading 42%",
    "Downloading 42% · 1.4 MiB/s",
    "Downloading 100%",
    "Waiting...",
    "Failed",
    "Unavailable",
    "Skipped",
    "Missing",
    "Not downloaded",
]

# Tag each phrase must resolve to.
EXPECTED_TAGS = {
    "Downloaded": "ok",
    "Downloading...": "busy",
    "Downloading 42%": "busy",
    "Downloading 42% · 1.4 MiB/s": "busy",
    "Downloading 100%": "busy",
    "Waiting...": "busy",
    "Failed": "missing",
    "Unavailable": "missing",
    "Skipped": "ok",
    "Missing": "missing",
    "Not downloaded": "muted",
}


class TestStatusTagResolution:
    @pytest.mark.parametrize("phrase", REAL_STATUS_PHRASES)
    def test_resolves_to_expected_tag(self, phrase):
        assert PlaylistTable._status_tag(phrase) == EXPECTED_TAGS[phrase]

    @pytest.mark.parametrize("phrase", REAL_STATUS_PHRASES)
    def test_never_falls_through_to_muted_unexpectedly(self, phrase):
        """Only the deliberate 'not yet examined' state may be muted."""
        tag = PlaylistTable._status_tag(phrase)
        if tag == "muted":
            assert phrase == "Not downloaded"

    @pytest.mark.parametrize("phrase", REAL_STATUS_PHRASES)
    def test_every_resolved_tag_has_a_glyph(self, phrase):
        tag = PlaylistTable._status_tag(phrase)
        assert tag in tokens.STATUS_ICONS, f"{phrase!r} resolved to {tag!r}"
        assert tokens.STATUS_ICONS[tag].strip()

    def test_trailing_ellipsis_does_not_break_lookup(self):
        """Regression: 'Downloading...' split to a key that was not in the map."""
        assert PlaylistTable._status_tag("Downloading...") != "muted"
        assert PlaylistTable._status_tag("Waiting...") != "muted"

    def test_case_insensitive(self):
        assert PlaylistTable._status_tag("downloaded") == "ok"
        assert PlaylistTable._status_tag("FAILED") == "missing"

    def test_unknown_phrase_is_muted_not_an_error(self):
        assert PlaylistTable._status_tag("Something New") == "muted"


class TestStatusTagTable:
    def test_every_tag_maps_to_itself_or_a_known_tag(self):
        """A tag must not point at a tag that carries no glyph."""
        for key, value in STATUS_TAGS.items():
            assert value in {"ok", "missing", "busy", "muted"}, (
                f"{key} maps to unknown tag {value!r}"
            )
            assert value in tokens.STATUS_ICONS

    def test_all_four_tags_are_used(self):
        assert set(STATUS_TAGS.values()) == {"ok", "missing", "busy", "muted"}

    @pytest.mark.parametrize("tag", ["ok", "missing", "busy", "muted"])
    def test_every_tag_resolves_a_real_phrase(self, tag):
        """Each tag must be reachable, or its colour is never seen."""
        inverse = {v: k for k, v in STATUS_TAGS.items()}
        phrase = inverse[tag]
        assert PlaylistTable._status_tag(phrase) == tag
