"""Removal of partial downloads, orphan artwork and leftover source media.

An interrupted run leaves debris behind: ``<name>.part`` / ``<name>.ytdl`` /
``<name>.temp.*`` fragments, ``<name>.webp`` artwork whose embedding never
finished, the raw ``.webm`` behind a finished ``.mp3``, and one-level subfolders
left by older builds. :func:`cleanup_partials` sweeps those, and
:func:`cleanup_foreign_junk` removes artwork downloaded *during* a run even when
no partial survives to match it.
"""

import os

from .naming import (
    FINAL_MEDIA_EXTS,
    is_image_file,
    is_partial_file,
)


def _try_remove(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _stems(name: str) -> tuple:
    """Return (stem, extension) lowercased."""
    stem, ext = os.path.splitext(name)
    return stem.lower(), ext.lower()


def _clean_one_dir(directory: str) -> bool:
    """Clean a single directory. Returns True if anything was removed."""
    try:
        names = os.listdir(directory)
    except OSError:
        return False

    media_stems, partial_stems, final_stems = set(), set(), set()
    for name in names:
        stem, ext = _stems(name)
        if is_partial_file(name):
            partial_stems.add(os.path.splitext(stem)[0])
        elif is_image_file(name):
            continue
        else:
            media_stems.add(stem)
            if ext in FINAL_MEDIA_EXTS:
                final_stems.add(stem)

    removed_any = False
    for name in names:
        path = os.path.join(directory, name)
        stem, ext = _stems(name)

        if is_partial_file(name):
            removed_any |= _try_remove(path)
            continue
        # Artwork that belongs to a song present in this folder: never a
        # finished output, so safe to drop.
        if is_image_file(name) and (stem in media_stems or stem in partial_stems):
            removed_any |= _try_remove(path)
            continue
        # Raw source left by an interrupted conversion (e.g. '.webm' when the
        # converted '.mp3' already exists).
        if ext not in FINAL_MEDIA_EXTS and stem in final_stems:
            removed_any |= _try_remove(path)
    return removed_any


def cleanup_partials(download_dir: str) -> None:
    """Delete partial downloads, orphan artwork and leftover source media.

    Also cleans one level of subfolders and removes any that end up empty.
    """
    if not os.path.isdir(download_dir):
        return
    _clean_one_dir(download_dir)
    try:
        names = os.listdir(download_dir)
    except OSError:
        return
    for name in names:
        sub = os.path.join(download_dir, name)
        if not os.path.isdir(sub):
            continue
        if not _clean_one_dir(sub):
            continue
        try:
            if not os.listdir(sub):
                os.rmdir(sub)
        except OSError:
            pass


def snapshot_thumbnails(download_dir: str) -> frozenset:
    """Names of image files present *before* a download run.

    Paired with :func:`cleanup_foreign_junk` so artwork downloaded during the
    run can be removed even when no media or partial file survives to match it
    (e.g. an aborted song whose ``.part`` yt-dlp already deleted).
    """
    if not os.path.isdir(download_dir):
        return frozenset()
    try:
        names = os.listdir(download_dir)
    except OSError:
        return frozenset()
    return frozenset(n for n in names if is_image_file(n))


def cleanup_foreign_junk(download_dir: str, before_names=frozenset()) -> None:
    """Delete image files that appeared since ``before_names`` was captured.

    These are thumbnails yt-dlp left behind (never finished songs). Files
    already present before the run are preserved.
    """
    if not os.path.isdir(download_dir):
        return
    try:
        names = os.listdir(download_dir)
    except OSError:
        return
    for name in names:
        if name not in before_names and is_image_file(name):
            _try_remove(os.path.join(download_dir, name))
