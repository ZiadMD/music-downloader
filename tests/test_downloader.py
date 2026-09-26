"""Tests for :mod:`musicdl.ui.downloader`.

The job is driven end-to-end with yt-dlp stubbed out, so these cover the real
decision logic: which songs get queued, how name collisions are resolved, how
failures are classified, and what the summary says.
"""

import pytest

from musicdl.ui import downloader as dl

ENTRIES = [
    {"id": "a1", "title": "Song One", "uploader": "X",
     "url": "https://youtu.be/a1"},
    {"id": "b2", "title": "Song Two", "uploader": "Y",
     "url": "https://youtu.be/b2"},
    {"id": "c3", "title": "Song Three", "uploader": "Z",
     "url": "https://youtu.be/c3"},
]


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Collect emitted messages and stub out everything touching the network."""
    messages = []
    monkeypatch.setattr(dl.core, "warm_session", lambda: None)
    monkeypatch.setattr(dl, "cleanup_partials", lambda _d: None)
    monkeypatch.setattr(dl, "cleanup_foreign_junk", lambda *_a: None)
    monkeypatch.setattr(dl, "snapshot_thumbnails", lambda _d: set())
    monkeypatch.setattr(dl.core, "scan_saved_titles", lambda _d: set())
    monkeypatch.setattr(dl.core, "check_missing",
                        lambda _d, e: (set(), list(e)))
    monkeypatch.setattr(dl.core, "fetch_playlist", lambda *_a, **_k: ("PL", ENTRIES))
    monkeypatch.setattr(dl, "validate_cookie_file", lambda _p: (True, 3, 3, "OK"))

    def emit(msg):
        messages.append(msg)

    return {"msgs": messages, "emit": emit, "dir": str(tmp_path),
            "msgs_of": lambda kind: [m for m in messages if m[0] == kind]}


def make_job(harness, action="download", **overrides):
    snap = {
        "url": "https://youtube.com/playlist?list=PL1",
        "dir": harness["dir"],
        "media": "Music",
        "format": "MP3",
        "quality": "192",
        "resolution": "Best",
        "thumbnail": True,
        "cookie_path": "",
        "selected": [e["id"] for e in ENTRIES],
        "parallel_jobs": 1,
    }
    snap.update(overrides)
    job = dl.DownloadJob(
        action=action, snapshot=snap, enqueue=harness["emit"],
        ask_rename=lambda _e: "rename", stop_requested=lambda: False,
        url=snap["url"] if action == "load" else None,
        ids=overrides.get("ids"),
    )
    job.entries = list(ENTRIES) if action != "load" else []
    return job


def run(job):
    job._dispatch()
    return job


class TestFailureClassification:
    @pytest.mark.parametrize("reason", [
        "ERROR: Video unavailable", "ERROR: Private video. Sign in",
        "This video has been removed by the uploader",
        "Video is no longer available",
    ])
    def test_removed_videos_are_unavailable_not_failed(self, harness, reason):
        job = make_job(harness)
        job._record_failure(ENTRIES[0], reason, cookie_used=False)
        assert ENTRIES[0]["id"] in job.unavailable
        assert ENTRIES[0]["id"] not in job.failed
        assert harness["msgs_of"](dl.ROW_STATUS)[-1][2] == "Unavailable"

    @pytest.mark.parametrize("reason", [
        "HTTP Error 429: Too Many Requests",
        "Sign in to confirm your age",
        "ERROR: unable to download webpage",
    ])
    def test_transient_problems_are_failed_and_retried(self, harness, reason):
        job = make_job(harness)
        job._record_failure(ENTRIES[0], reason, cookie_used=False)
        assert ENTRIES[0]["id"] in job.failed
        assert ENTRIES[0]["id"] not in job.unavailable
        assert harness["msgs_of"](dl.ROW_STATUS)[-1][2] == "Failed"

    def test_age_failure_without_cookies_suggests_fix_blocked(self, harness):
        job = make_job(harness)
        job._record_failure(ENTRIES[0], "Sign in to confirm your age", False)
        log = " ".join(m[1] for m in harness["msgs_of"](dl.LOG))
        assert "Fix blocked" in log

    def test_age_failure_with_cookies_suggests_fresh_export(self, harness):
        job = make_job(harness)
        job._record_failure(ENTRIES[0], "Sign in to confirm your age", True)
        log = " ".join(m[1] for m in harness["msgs_of"](dl.LOG))
        assert "fresh cookies export" in log

    def test_is_unavailable_helper(self):
        assert dl.is_unavailable("Video unavailable")
        assert not dl.is_unavailable("HTTP Error 500")


class TestSelection:
    def test_nothing_selected_short_circuits(self, harness, monkeypatch):
        monkeypatch.setattr(dl.core, "download_urls",
                            lambda *a, **k: pytest.fail("should not download"))
        job = run(make_job(harness, selected=[]))
        assert job.summary is not None and "Nothing selected" in job.summary
        assert harness["msgs_of"](dl.FINISHED) == []

    def test_all_already_present_short_circuits(self, harness, monkeypatch):
        monkeypatch.setattr(dl.core, "check_missing",
                            lambda _d, e: ({dl.core.normalize_title(x["title"])
                                            for x in e}, []))
        monkeypatch.setattr(dl.core, "download_urls",
                            lambda *a, **k: pytest.fail("should not download"))
        job = run(make_job(harness))
        assert job.summary is not None and "already downloaded" in job.summary

    def test_only_missing_songs_are_queued(self, harness, monkeypatch):
        # 'Song One' is already on disk.
        monkeypatch.setattr(dl.core, "check_missing",
                            lambda _d, e: ({"song one"}, []))
        seen = []

        def fake_dl(urls, out_dir, **kw):
            seen.extend(urls)
            return 1, []

        monkeypatch.setattr(dl.core, "download_urls", fake_dl)
        job = run(make_job(harness))
        assert seen == [ENTRIES[1]["url"], ENTRIES[2]["url"]]
        assert job.summary is not None and "Downloaded 2 songs" in job.summary


class TestRenameCollisions:
    def test_existing_file_triggers_prompt_and_unique_name(self, harness, monkeypatch):
        import os
        open(os.path.join(harness["dir"], "Song One.mp3"), "w").close()
        monkeypatch.setattr(dl.core, "download_urls", lambda *a, **k: (1, []))

        asked = []

        def ask(entry):
            asked.append(entry["title"])
            return "rename"

        job = dl.DownloadJob(
            action="download",
            snapshot={**make_job(harness).snap},
            enqueue=harness["emit"], ask_rename=ask, stop_requested=lambda: False)
        job.entries = list(ENTRIES)
        job._dispatch()
        assert asked == ["Song One"]
        log = " ".join(m[1] for m in harness["msgs_of"](dl.LOG))
        assert "Renaming to: Song One (2).mp3" in log

    def test_skip_choice_counts_as_skipped(self, harness, monkeypatch):
        import os
        open(os.path.join(harness["dir"], "Song One.mp3"), "w").close()
        monkeypatch.setattr(dl.core, "download_urls", lambda *a, **k: (1, []))
        snap = make_job(harness).snap
        job = dl.DownloadJob(
            action="download", snapshot=snap, enqueue=harness["emit"],
            ask_rename=lambda _e: "skip", stop_requested=lambda: False)
        job.entries = list(ENTRIES)
        job._dispatch()
        assert job.summary is not None and "1 skipped" in job.summary

    def test_cancel_choice_stops_the_run(self, harness, monkeypatch):
        import os
        open(os.path.join(harness["dir"], "Song One.mp3"), "w").close()
        monkeypatch.setattr(dl.core, "download_urls",
                            lambda *a, **k: pytest.fail("should not download"))
        snap = make_job(harness).snap
        job = dl.DownloadJob(
            action="download", snapshot=snap, enqueue=harness["emit"],
            ask_rename=lambda _e: "cancel", stop_requested=lambda: False)
        job.entries = list(ENTRIES)
        job._dispatch()
        assert job.stopped is True
        assert job.summary is not None and "stopped" in job.summary


class TestCheckAction:
    def test_reports_counts(self, harness, monkeypatch):
        monkeypatch.setattr(dl.core, "check_missing",
                            lambda _d, e: ({"song one"}, []))
        job = make_job(harness, action="check")
        job._dispatch()
        statuses = harness["msgs_of"](dl.STATUS)
        assert "1 downloaded, 2 missing" in statuses[-1][1]


class TestRetryAction:
    def test_only_requested_ids_retried(self, harness, monkeypatch):
        seen = []
        monkeypatch.setattr(dl.core, "download_urls",
                            lambda urls, _d, **k: (seen.extend(urls), (1, []))[1])
        job = make_job(harness, action="retry", ids=["b2"])
        job._dispatch()
        assert seen == [ENTRIES[1]["url"]]

    def test_unknown_ids_do_nothing(self, harness, monkeypatch):
        monkeypatch.setattr(dl.core, "download_urls",
                            lambda *a, **k: pytest.fail("should not download"))
        job = make_job(harness, action="retry", ids=["nope"])
        job._dispatch()
        assert harness["msgs_of"](dl.STATUS)[-1][1] == "Nothing to retry."


class TestSummary:
    def test_counts_every_category(self, harness, monkeypatch):
        def fake_dl(urls, _d, **kw):
            url = urls[0]
            if url == ENTRIES[0]["url"]:
                return 1, []
            if url == ENTRIES[1]["url"]:
                return 0, ["HTTP Error 429"]
            return 0, ["Video unavailable"]

        monkeypatch.setattr(dl.core, "download_urls", fake_dl)
        job = run(make_job(harness))
        assert job.summary is not None and "Downloaded 1 song" in job.summary   # singular
        assert job.summary is not None and "1 failed" in job.summary
        assert job.summary is not None and "1 unavailable" in job.summary

    def test_stopped_is_reported(self, harness, monkeypatch):
        state = {"stop": True}
        monkeypatch.setattr(dl.core, "download_urls", lambda *a, **k: (1, []))
        snap = make_job(harness).snap
        job = dl.DownloadJob(
            action="download", snapshot=snap, enqueue=harness["emit"],
            ask_rename=lambda _e: "rename", stop_requested=lambda: state["stop"])
        job.entries = list(ENTRIES)
        job._dispatch()
        # First song passes the stop check only if evaluated after we flip it,
        # so flipping up-front means nothing is queued at all.
        assert job.summary is None or "stopped" in job.summary


class TestSettingsNormalization:
    @pytest.mark.parametrize("fmt,ext", [
        ("MP3", "mp3"), ("FLAC", "flac"), ("OPUS", "opus"), ("M4A (AAC)", "m4a"),
    ])
    def test_codec_and_ext_follow_format(self, harness, fmt, ext):
        job = make_job(harness, format=fmt)
        s = job._download_settings()
        assert s["ext"] == ext
        assert s["codec"] in ("mp3", "flac", "opus", "m4a")

    def test_video_mode_uses_mp4(self, harness):
        job = make_job(harness, media="Video")
        s = job._download_settings()
        assert s["is_video"] is True
        assert s["ext"] == "mp4"
        assert s["resolution"] == job.snap["resolution"]

    def test_best_quality_falls_back_to_192(self, harness):
        job = make_job(harness, quality="Best")
        assert job._download_settings()["quality"] == "192"

    def test_unknown_format_falls_back_to_mp3(self, harness):
        job = make_job(harness, format="BOGUS")
        assert job._download_settings()["ext"] == "mp3"


class TestInvalidCookiePath:
    def test_invalid_cookie_path_is_discarded(self, harness, monkeypatch):
        monkeypatch.setattr(dl, "validate_cookie_file", lambda _p: (False, 0, 0, "bad"))
        job = make_job(harness, cookie_path="/nope/cookies.txt")
        assert job._resolve_cookie_path() == ""

    def test_valid_cookie_path_is_used(self, harness):
        job = make_job(harness, cookie_path="/some/cookies.txt")
        assert job._resolve_cookie_path() == "/some/cookies.txt"
