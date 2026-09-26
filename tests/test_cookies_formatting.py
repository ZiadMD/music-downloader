"""Tests for :mod:`musicdl.cookies` and :mod:`musicdl.formatting`."""

import pytest

from musicdl.cookies import validate_cookie_file
from musicdl.formatting import fmt_bytes, fmt_eta, fmt_speed, plural

NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n"
# domain, include-subdomains, path, secure, expiry, name, value
YT_COOKIE = ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc123\n"
OTHER_COOKIE = ".example.com\tTRUE\t/\tFALSE\t0\tk\tv\n"
GOOGLE_COOKIE = ".google.com\tTRUE\t/\tFALSE\t0\tNID\txyz\n"


def write_cookies(tmp_path, *lines, name="cookies.txt"):
    path = tmp_path / name
    path.write_text("".join(lines), encoding="utf-8")
    return str(path)


class TestValidateCookieFile:
    def test_missing_path(self, tmp_path):
        ok, count, yt, msg = validate_cookie_file(str(tmp_path / "nope.txt"))
        assert (ok, count, yt) == (False, 0, 0)
        assert msg == "file not found"

    def test_none_path(self):
        assert validate_cookie_file(None)[0] is False

    def test_valid_youtube_file(self, tmp_path):
        path = write_cookies(tmp_path, NETSCAPE_HEADER, YT_COOKIE, GOOGLE_COOKIE)
        ok, count, yt, msg = validate_cookie_file(path)
        assert ok is True
        assert count == 2
        assert yt == 2
        assert msg == "OK"

    def test_rejects_empty_file(self, tmp_path):
        path = write_cookies(tmp_path, NETSCAPE_HEADER)
        ok, count, _, msg = validate_cookie_file(path)
        assert ok is False
        assert count == 0
        assert "no cookies" in msg

    def test_rejects_non_netscape_format(self, tmp_path):
        # Real cookie lines, but the file lacks the '# Netscape HTTP Cookie
        # File' marker that browser extensions include.
        path = write_cookies(tmp_path, YT_COOKIE)
        ok, count, _, msg = validate_cookie_file(path)
        assert ok is False
        assert count == 1
        assert "Netscape" in msg

    def test_rejects_when_no_youtube_cookies(self, tmp_path):
        path = write_cookies(tmp_path, NETSCAPE_HEADER, OTHER_COOKIE)
        ok, count, yt, msg = validate_cookie_file(path)
        assert ok is False
        assert count == 1
        assert yt == 0
        assert "no youtube.com" in msg

    def test_skips_comments_and_blank_lines(self, tmp_path):
        path = write_cookies(tmp_path, NETSCAPE_HEADER, "# a comment\n",
                             "\n", YT_COOKIE)
        ok, count, _, _ = validate_cookie_file(path)
        assert ok is True
        assert count == 1

    def test_handles_utf8_bom(self, tmp_path):
        path = tmp_path / "cookies.txt"
        path.write_text(NETSCAPE_HEADER + YT_COOKIE, encoding="utf-8-sig")
        assert validate_cookie_file(str(path))[0] is True


class TestFmtBytes:
    @pytest.mark.parametrize("value,expected", [
        (0, "0 B"), (512, "512 B"), (1024, "1 KB"),
        (1536, "2 KB"), (1048576, "1.0 MB"), (1073741824, "1.0 GB"),
    ])
    def test_formats(self, value, expected):
        assert fmt_bytes(value) == expected

    def test_none_and_garbage(self):
        assert fmt_bytes(None) == "0 B"
        assert fmt_bytes("nope") == "0 B"


class TestFmtSpeed:
    @pytest.mark.parametrize("value,expected", [
        (0, "--"), (None, "--"), (-5, "--"), ("x", "--"),
        (512, "512 B/s"), (2048, "2 KiB/s"),
        (1048576, "1.0 MiB/s"), (1073741824, "1.0 GiB/s"),
    ])
    def test_formats(self, value, expected):
        assert fmt_speed(value) == expected


class TestFmtEta:
    @pytest.mark.parametrize("value,expected", [
        (0, "--"), (None, "--"), (-3, "--"),
        (45, "0:45"), (90, "1:30"), (3600, "1:00:00"), (3725, "1:02:05"),
    ])
    def test_formats(self, value, expected):
        assert fmt_eta(value) == expected


class TestPlural:
    @pytest.mark.parametrize("n,expected", [
        (0, "0 songs"), (1, "1 song"), (2, "2 songs"),
    ])
    def test_default_plural(self, n, expected):
        assert plural(n, "song") == expected

    def test_irregular(self):
        assert plural(2, "failed song") == "2 failed songs"
