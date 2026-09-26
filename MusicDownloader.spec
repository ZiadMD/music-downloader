# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Music Downloader.

Build with:
    uv sync --extra dev
    uv run pyinstaller MusicDownloader.spec
"""
from PyInstaller.utils.hooks import collect_all

# ttkbootstrap ships its themes/icons as package data and yt_dlp as an
# importable namespace package, so both need collecting rather than analysis.
datas = [('icon.ico', '.')]
binaries = []
hiddenimports = ['PIL._tkinter_finder']

for package in ('ttkbootstrap', 'yt_dlp', 'musicdl', 'PySide6'):
    collected = collect_all(package)
    datas += collected[0]
    binaries += collected[1]
    hiddenimports += collected[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'pandas', 'IPython', 'tensorflow', 'pytest', 'pyright'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MusicDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
