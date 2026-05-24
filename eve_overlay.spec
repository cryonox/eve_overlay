# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_all

# Render the .ico from the shared icon artwork (same drawing as the tray icon).
sys.path.insert(0, os.path.dirname(os.path.abspath(SPEC)))
import icon as icon_art
_icon_path = os.path.abspath('icon.ico')
icon_art.write_ico(_icon_path)
print(f"[spec] wrote icon -> {_icon_path}")

# pystray / PIL ship data files and submodules that need full collection so the
# bundled exe can import them.
_extra_datas = []
_extra_binaries = []
_extra_hidden = []
for _mod in ('pystray', 'PIL'):
    _d, _b, _h = collect_all(_mod)
    _extra_datas += _d
    _extra_binaries += _b
    _extra_hidden += _h

a = Analysis(
    ['eve_overlay.py'],
    pathex=[],
    binaries=_extra_binaries,
    datas=_extra_datas,
    hiddenimports=[
        'pystray', 'pystray._win32',
        'PIL', 'PIL.Image', 'PIL.ImageDraw',
    ] + _extra_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='eve_overlay',
    icon=_icon_path,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,
)
