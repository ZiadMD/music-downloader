"""UI layer for Music Downloader.

Kept as a separate subpackage so the headless modules (:mod:`musicdl.core`,
:mod:`musicdl.naming`, ...) can be imported — and tested — without pulling in
Tk. Import the concrete modules directly::

    from musicdl.ui import app
"""
