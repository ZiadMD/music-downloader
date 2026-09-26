"""Tests for :mod:`musicdl.naming`.

The matching rules here are subtle: a playlist title has to line up with a
filename yt-dlp actually wrote, including its substitution of characters
Windows forbids. These tests pin that behaviour down.
"""

import pytest

from musicdl.naming import (
    existing_titles,
    is_image_file,
    is_partial_file,
    is_saved_match,
    normalize_title,
    safe_stem,
    sanitize_folder_name,
    title_file_exists,
    unique_stem,
)


class TestNormalizeTitle:
    def test_empty(self):
        assert normalize_title("") == ""

    def test_none(self):
        assert normalize_title(None) == ""

    def test_lowercases_and_collapses_space(self):
        assert normalize_title("  Hello   World  ") == "hello world"

    def test_strips_windows_illegal_chars(self):
        # ':' and '|' vanish, and the resulting double space is collapsed.
        assert normalize_title("A: B | C") == "a b c"

    def test_folds_fullwidth_lookalikes(self):
        # yt-dlp writes these glyphs in place of " : / \"
        assert normalize_title("Song＂Title") == "songtitle"
        assert normalize_title("a⧸b") == "ab"
        assert normalize_title("a／b") == "ab"
        assert normalize_title("a꞉b") == "ab"

    def test_matches_ytdlp_saved_name(self):
        """A title and the name yt-dlp wrote for it must normalize equal."""
        title = 'Artist - "Best" Song / Part 1'
        saved = "Artist - ＂Best＂ Song ⧸ Part 1"
        assert normalize_title(title) == normalize_title(saved)

    def test_strips_hash_replacement(self):
        # yt-dlp replaces illegal chars with '#' when saving.
        assert normalize_title("A# B") == "a b"
        assert normalize_title("A: B") == normalize_title("A# B")


class TestSanitizeFolderName:
    def test_removes_illegal_chars(self):
        assert sanitize_folder_name('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij"

    def test_trailing_dot_removed(self):
        assert sanitize_folder_name("name...") == "name"

    def test_truncates_long_names(self):
        assert len(sanitize_folder_name("x" * 500)) == 120

    def test_empty_falls_back(self):
        assert sanitize_folder_name("") == "playlist"
        assert sanitize_folder_name("///") == "playlist"

    def test_reserved_device_name_escaped(self):
        assert sanitize_folder_name("CON") == "_CON"
        assert sanitize_folder_name("com1") == "_com1"


class TestSafeStem:
    def test_no_path_separators(self):
        stem = safe_stem("AC/DC - Back in Black")
        assert "/" not in stem
        assert "\\" not in stem

    def test_empty_falls_back(self):
        assert safe_stem("") == "song"

    def test_truncates(self):
        assert len(safe_stem("y" * 400)) <= 120

    def test_reserved_name_escaped(self):
        assert safe_stem("nul").lower() == "_nul"


class TestFileClassification:
    @pytest.mark.parametrize("name", ["a.jpg", "a.JPEG", "b.png", "c.webp", "d.bmp"])
    def test_images(self, name):
        assert is_image_file(name)

    @pytest.mark.parametrize("name", ["a.mp3", "b.part", "c.ytdl", "d.temp.mp4", "e.MP3"])
    def test_non_images(self, name):
        assert not is_image_file(name)

    @pytest.mark.parametrize("name,expected", [
        ("a.part", True), ("a.ytdl", True), ("a.temp.mp4", True),
        ("a.mp3", False), ("a.jpg", False),
    ])
    def test_partials(self, name, expected):
        assert is_partial_file(name) is expected


class TestExistingTitles:
    def test_skips_images_and_partials(self, tmp_path):
        (tmp_path / "Song A.mp3").touch()
        (tmp_path / "Song A.jpg").touch()
        (tmp_path / "Song B.part").touch()
        found = existing_titles(str(tmp_path))
        assert "song a" in found
        assert "song b" not in found

    def test_walks_subfolders(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "Deep Song.mp3").touch()
        assert "deep song" in existing_titles(str(tmp_path))

    def test_missing_dir(self, tmp_path):
        assert existing_titles(str(tmp_path / "nope")) == set()


class TestTitleFileExists:
    def test_finds_by_normalized_name(self, tmp_path):
        (tmp_path / "Song＂One.mp3").touch()
        assert title_file_exists(str(tmp_path), "Song\"One")

    def test_ignores_images(self, tmp_path):
        (tmp_path / "Cover.jpg").touch()
        assert not title_file_exists(str(tmp_path), "Cover")

    def test_empty_title(self, tmp_path):
        assert title_file_exists(str(tmp_path), "") is False


class TestUniqueStem:
    def test_first_use_keeps_title(self, tmp_path):
        assert unique_stem(str(tmp_path), "My Song") == "My Song"

    def test_second_use_gets_numbered_suffix(self, tmp_path):
        (tmp_path / "My Song.mp3").touch()
        assert unique_stem(str(tmp_path), "My Song") == "My Song (2)"

    def test_third_use(self, tmp_path):
        (tmp_path / "My Song.mp3").touch()
        (tmp_path / "My Song (2).mp3").touch()
        assert unique_stem(str(tmp_path), "My Song") == "My Song (3)"

    def test_reserved_avoids_collision(self, tmp_path):
        assert unique_stem(str(tmp_path), "Song", reserved={"Song"}) == "Song (2)"

    def test_ignores_images_when_checking(self, tmp_path):
        (tmp_path / "Song.jpg").touch()
        assert unique_stem(str(tmp_path), "Song") == "Song"


class TestIsSavedMatch:
    def test_exact(self):
        assert is_saved_match({"my song"}, "My Song")

    def test_numbered_variant(self):
        assert is_saved_match({"my song (2)"}, "My Song")

    def test_does_not_match_unrelated(self):
        assert not is_saved_match({"other song"}, "My Song")

    def test_does_not_match_similar_prefix(self):
        # 'my song live' must not count as 'my song'
        assert not is_saved_match({"my song live"}, "My Song")
