"""Tests for :mod:`musicdl.paths`.

The important property is that app-owned state (settings, cookies) never lands
inside the source tree or the package directory, and that ffmpeg/Node lookup
degrades to "not found" instead of raising when nothing is installed.
"""

import os

import pytest

from musicdl import paths


class TestBaseDir:
    def test_does_not_write_inside_the_package(self, monkeypatch):
        """Regression: state used to be written next to paths.py itself."""
        monkeypatch.setenv("APPDATA", "/tmp/paths-test-appdata")
        monkeypatch.setenv("LOCALAPPDATA", "/tmp/paths-test-localappdata")
        base = paths._base_dir()
        package_dir = os.path.dirname(os.path.abspath(paths.__file__))
        assert not os.path.abspath(base).startswith(package_dir)

    def test_does_not_write_inside_the_source_tree(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "user_config_dir", lambda: str(tmp_path / "cfg"))
        monkeypatch.setattr(paths, "user_data_dir", lambda: str(tmp_path / "data"))
        base = paths._base_dir()
        assert os.path.abspath(base).startswith(str(tmp_path))

    def test_result_is_writable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths, "user_config_dir", lambda: str(tmp_path / "cfg"))
        monkeypatch.setattr(paths, "user_data_dir", lambda: str(tmp_path / "data"))
        probe = os.path.join(paths._base_dir(), ".probe")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("x")
        assert os.path.exists(probe)


class TestResolveUserPath:
    def test_expands_tilde(self):
        assert paths.resolve_user_path("~/Music") == os.path.expanduser("~/Music")

    def test_expands_env_vars(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MD_TEST_DIR", str(tmp_path))
        assert paths.resolve_user_path("$MD_TEST_DIR/songs") == f"{tmp_path}/songs"

    def test_blank_returns_fallback(self):
        assert paths.resolve_user_path("   ", "/fallback") == "/fallback"
        assert paths.resolve_user_path(None, "/fallback") == "/fallback"

    def test_no_fallback_and_blank(self):
        assert paths.resolve_user_path("") == ""


class TestDefaultDownloadDir:
    def test_is_absolute_and_ends_with_playlists(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XDG_MUSIC_DIR", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-user-dirs"))
        result = paths.default_download_dir()
        assert os.path.isabs(result)
        assert result.endswith(os.path.join("Music", "Playlists"))


class TestExternalToolDiscovery:
    def test_find_ffmpeg_dir_returns_string(self):
        # Never raises, whether or not ffmpeg is installed.
        assert isinstance(paths.find_ffmpeg_dir(), str)

    def test_find_node_returns_string(self):
        assert isinstance(paths.find_node(), str)

    def test_candidates_are_existing_directories(self, monkeypatch):
        monkeypatch.setattr(paths, "is_windows", lambda: False)
        monkeypatch.setattr(paths.sys, "platform", "linux")
        assert all(os.path.isdir(d) for d in paths.ffmpeg_candidates())

    def test_falls_back_when_nothing_found(self, monkeypatch, tmp_path):
        monkeypatch.setattr(paths.shutil, "which", lambda *_a, **_k: None)
        monkeypatch.setattr(paths, "ffmpeg_candidates", lambda: [])
        assert paths.find_ffmpeg_dir() == ""


class TestResourcePath:
    def test_points_into_the_resource_dir(self):
        icon = paths.resource_path("icon.ico")
        assert icon.endswith(os.path.join("icon.ico"))
        assert os.path.dirname(icon) == paths.resource_dir()


class TestMigrateLegacyFiles:
    def test_moves_config_from_source_dir(self, monkeypatch, tmp_path):
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "config.json").write_text("{}", encoding="utf-8")
        target = tmp_path / "target"
        monkeypatch.setattr(paths, "legacy_files",
                            lambda: [str(legacy_dir / "config.json")])
        monkeypatch.setattr(paths, "_base_dir", lambda: str(target))

        moved = paths.migrate_legacy_files()
        assert moved == [str(target / "config.json")]
        assert (target / "config.json").exists()

    def test_never_overwrites_existing(self, monkeypatch, tmp_path):
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "config.json").write_text("new", encoding="utf-8")
        target = tmp_path / "target"
        target.mkdir()
        (target / "config.json").write_text("existing", encoding="utf-8")
        monkeypatch.setattr(paths, "legacy_files",
                            lambda: [str(legacy_dir / "config.json")])
        monkeypatch.setattr(paths, "_base_dir", lambda: str(target))

        assert paths.migrate_legacy_files() == []
        assert (target / "config.json").read_text() == "existing"
