"""Tests for :mod:`musicdl.config`.

Settings are user-owned state read from disk, so the important behaviour is
that malformed or stale values are repaired rather than propagated.
"""

import json

import pytest

from musicdl import config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point the app's config file at a temp dir and use a real output dir."""
    out = tmp_path / "music"
    out.mkdir()
    monkeypatch.setattr(config.paths, "config_file",
                        lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(config.paths, "migrate_legacy_files", lambda: [])
    monkeypatch.setattr(config.paths, "default_download_dir", lambda: str(out))
    return tmp_path


def write(root, values):
    """Write a settings dict to the isolated config file."""
    (root / "config.json").write_text(json.dumps(values), encoding="utf-8")


class TestLoadDefaults:
    def test_no_file_returns_defaults(self, isolated_config):
        cfg = config.load()
        assert cfg["format"] == "MP3"
        assert cfg["theme"] == "system"
        assert cfg["parallel_jobs"] == 3

    def test_output_dir_defaults_to_music_folder(self, isolated_config):
        assert config.load()["output_dir"] == str(isolated_config / "music")

    def test_corrupt_json_falls_back(self, isolated_config):
        (isolated_config / "config.json").write_text("{not json", encoding="utf-8")
        assert config.load()["format"] == "MP3"

    def test_non_dict_json_falls_back(self, isolated_config):
        (isolated_config / "config.json").write_text("[1, 2]", encoding="utf-8")
        assert config.load()["media"] == "Music"


class TestValueValidation:
    def test_invalid_enum_values_repaired(self, isolated_config):
        write(isolated_config, {
            "format": "NOT_A_FORMAT", "quality": "999",
            "media": "Film", "resolution": "4320p", "theme": "neon",
        })
        cfg = config.load()
        assert cfg["format"] == "MP3"
        assert cfg["quality"] == "192"
        assert cfg["media"] == "Music"
        assert cfg["resolution"] == "Best"
        assert cfg["theme"] == "system"

    @pytest.mark.parametrize("value", ["system", "light", "dark"])
    def test_valid_theme_preserved(self, isolated_config, value):
        write(isolated_config, {"theme": value})
        assert config.load()["theme"] == value

    @pytest.mark.parametrize("raw,expected", [
        (0, 1), (1, 1), (3, 3), (6, 6), (99, 6), (-5, 1),
        ("4", 4), (None, 3), ("abc", 3),
    ])
    def test_parallel_jobs_clamped(self, isolated_config, raw, expected):
        write(isolated_config, {"parallel_jobs": raw})
        assert config.load()["parallel_jobs"] == expected

    def test_stale_output_dir_replaced(self, isolated_config):
        write(isolated_config, {"output_dir": "C:\\Users\\Someone\\Temp"})
        assert config.load()["output_dir"] == str(isolated_config / "music")

    def test_blank_output_dir_replaced(self, isolated_config):
        write(isolated_config, {"output_dir": "   "})
        assert config.load()["output_dir"] == str(isolated_config / "music")

    def test_existing_output_dir_kept(self, isolated_config):
        keep = isolated_config / "keep"
        keep.mkdir()
        write(isolated_config, {"output_dir": str(keep)})
        assert config.load()["output_dir"] == str(keep)

    def test_strings_are_stripped(self, isolated_config):
        write(isolated_config, {"last_url": "  https://youtu.be/x  ", "cookie_path": "  a.txt "})
        cfg = config.load()
        assert cfg["last_url"] == "https://youtu.be/x"
        assert cfg["cookie_path"] == "a.txt"

    def test_booleans_coerced(self, isolated_config):
        write(isolated_config, {"thumbnail": 0, "parallel": "yes"})
        cfg = config.load()
        assert cfg["thumbnail"] is False
        assert cfg["parallel"] is True


class TestSave:
    def test_round_trips(self, isolated_config):
        cfg = config.load()
        cfg["format"] = "FLAC"
        config.save(cfg)
        assert config.load()["format"] == "FLAC"

    def test_read_only_location_is_silent(self, isolated_config, monkeypatch):
        def boom(*_a, **_k):
            raise OSError("read-only")

        monkeypatch.setattr("builtins.open", boom)
        config.save({"format": "MP3"})  # must not raise
