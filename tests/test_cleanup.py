"""Tests for :mod:`musicdl.cleanup`.

Cleanup runs against real directories because the interesting behaviour is all
filesystem interaction: what survives, what gets removed, and which empty
folders are cleaned up afterwards.
"""

from musicdl.cleanup import cleanup_foreign_junk, cleanup_partials, snapshot_thumbnails


def touch(directory, name):
    path = directory / name
    path.write_bytes(b"x")
    return path


class TestCleanupPartials:
    def test_removes_part_and_ytdl(self, tmp_path):
        touch(tmp_path, "a.mp3")
        touch(tmp_path, "b.part")
        touch(tmp_path, "c.ytdl")
        cleanup_partials(str(tmp_path))
        assert sorted(p.name for p in tmp_path.iterdir()) == ["a.mp3"]

    def test_removes_orphan_artwork_but_keeps_song(self, tmp_path):
        touch(tmp_path, "a.mp3")
        touch(tmp_path, "a.webp")
        cleanup_partials(str(tmp_path))
        assert sorted(p.name for p in tmp_path.iterdir()) == ["a.mp3"]

    def test_keeps_artwork_with_no_matching_song(self, tmp_path):
        # Artwork with no media and no partial is ambiguous: leave it alone.
        touch(tmp_path, "lonely.jpg")
        cleanup_partials(str(tmp_path))
        assert [p.name for p in tmp_path.iterdir()] == ["lonely.jpg"]

    def test_removes_raw_source_when_converted_exists(self, tmp_path):
        touch(tmp_path, "a.mp3")
        touch(tmp_path, "a.webm")
        cleanup_partials(str(tmp_path))
        assert [p.name for p in tmp_path.iterdir()] == ["a.mp3"]

    def test_keeps_raw_source_when_no_conversion(self, tmp_path):
        touch(tmp_path, "a.webm")
        cleanup_partials(str(tmp_path))
        assert [p.name for p in tmp_path.iterdir()] == ["a.webm"]

    def test_cleans_subfolders_and_removes_empty_ones(self, tmp_path):
        # A subfolder holding only junk becomes empty and is removed.
        junk_only = tmp_path / "junkdir"
        junk_only.mkdir()
        touch(junk_only, "orphan.part")
        cleanup_partials(str(tmp_path))
        assert not junk_only.exists()

    def test_cleans_subfolders_but_keeps_those_holding_songs(self, tmp_path):
        sub = tmp_path / "old"
        sub.mkdir()
        touch(sub, "song.mp3")
        touch(sub, "junk.part")
        cleanup_partials(str(tmp_path))
        assert sub.exists()
        assert [p.name for p in sub.iterdir()] == ["song.mp3"]

    def test_keeps_non_empty_subfolders(self, tmp_path):
        sub = tmp_path / "old"
        sub.mkdir()
        touch(sub, "song.mp3")
        cleanup_partials(str(tmp_path))
        assert sub.exists()
        assert [p.name for p in sub.iterdir()] == ["song.mp3"]

    def test_missing_dir_is_noop(self, tmp_path):
        cleanup_partials(str(tmp_path / "does-not-exist"))  # must not raise


class TestSnapshotAndForeignJunk:
    def test_snapshot_lists_images_only(self, tmp_path):
        touch(tmp_path, "a.mp3")
        touch(tmp_path, "b.jpg")
        assert snapshot_thumbnails(str(tmp_path)) == frozenset({"b.jpg"})

    def test_removes_images_added_during_run(self, tmp_path):
        touch(tmp_path, "kept.jpg")
        before = snapshot_thumbnails(str(tmp_path))
        touch(tmp_path, "arrived.jpg")
        cleanup_foreign_junk(str(tmp_path), before)
        assert [p.name for p in tmp_path.iterdir()] == ["kept.jpg"]

    def test_missing_dir_is_noop(self, tmp_path):
        assert snapshot_thumbnails(str(tmp_path / "nope")) == frozenset()
        cleanup_foreign_junk(str(tmp_path / "nope"))  # must not raise
