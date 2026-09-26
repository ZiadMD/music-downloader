# Music Downloader

A modern desktop GUI for downloading YouTube playlists as **music** or **video**, built on
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ttkbootstrap](https://ttkbootstrap.readthedocs.io/).

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- Load a YouTube **playlist** or a **single** video / music link
- Pick exactly what you want: **tick** individual songs, or tick/untick all
- Per-song status: **Downloaded / Missing / Failed / Unavailable / Skipped**
- Music output as **MP3, M4A (AAC), FLAC, WAV, OGG (Vorbis) or OPUS** at 128–320 kbps
- Video output as a merged **MP4** at 480p / 720p / 1080p / Best
- Live per-row and overall progress, speed, ETA and a running log
- Graceful same-name handling (**Skip / Rename / Cancel**)
- One-click **Retry Failed**, plus right-click retry on a single row
- Optional multi-download (1–6 parallel jobs)
- Built-in **"Fix blocked"** helper for YouTube's bot check (browser cookies / `cookies.txt`)
- Live search filter, light and dark themes

## Requirements

- Python **3.11+**
- [FFmpeg](https://ffmpeg.org/download.html) on your `PATH` — required for audio conversion
  and video merging. On Windows: `winget install Gyan.FFmpeg`

## Install and run

This project uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync                 # create the environment and install dependencies
uv run python main.py   # launch the app
```

Or with plain pip:

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -e .
python main.py
```

### Optional: better handling of bot-blocked videos

```bash
uv sync --extra botworkaround
```

## Building a standalone executable

```bash
uv sync --extra dev
uv run pyinstaller MusicDownloader.spec
```

The built app lands in `dist/`.

## Project layout

```
main.py                  launch script (also the PyInstaller entry point)
musicdl/
  __main__.py            `python -m musicdl`
  paths.py               cross-platform paths; ffmpeg & Node.js discovery
  config.py              settings load/validate/save
  naming.py              title <-> filename normalization, safe stems
  cleanup.py             partial-download and orphan-artwork sweeping
  cookies.py             cookies.txt validation
  formatting.py          bytes / speed / ETA / plural formatting
  core.py                yt-dlp boundary: metadata fetch + downloads
  ui/
    app.py               main window: widget state and rendering
    downloader.py        the download job (headless, queue-driven)
    widgets.py           playlist table + background thumbnail loader
    dialogs.py           modal rename prompt
    theme.py             OS theme detection and the ttkbootstrap palette
tests/                   pytest suite for everything above
```

The `ui` subpackage is kept separate from the headless modules so the download
logic can be imported and tested without a display.

## Development

```bash
uv sync --extra dev
uv run pytest      # test suite
uv run pyright     # type check
```

## Settings

Settings are written to `config.json` in a per-user directory
(`%APPDATA%` on Windows, `~/Library/Application Support` on macOS,
`~/.config/music-downloader` on Linux), falling back to a folder beside the
executable when that is writable. `config.json` and `cookies.txt` are
git-ignored; see `config.example.json` for the available keys.

## How "Fix blocked (cookies.txt)" works

Some videos are refused unless YouTube sees you as signed in. The app can:

1. Read a **Netscape-format `cookies.txt`** you export from a browser extension while
   signed in to YouTube (or)
2. Use `--cookies-from-browser` for Chrome / Edge / Firefox / Brave / Opera.

The app validates the file before use and tells you how many cookies it found and how many
are for YouTube/Google. See the in-app hint for the full flow.

## License

MIT
