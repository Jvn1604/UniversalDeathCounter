# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Universal Death Counter.

Build locally (Windows, from the project root):
    pyinstaller packaging/UniversalDeathCounter.spec

Produces a single-file executable at dist/UniversalDeathCounter.exe with
the app icon baked in and themes/icons bundled as data files.
"""

import sys
from pathlib import Path

block_cipher = None

# Resolve project root relative to this spec file so the build works
# regardless of the current working directory it's invoked from.
PROJECT_ROOT = Path(SPECPATH).resolve().parent

# collect_submodules("src") silently skips some modules (e.g. src.ui.main_window,
# src.database.database), causing ModuleNotFoundError at runtime. Walk the
# filesystem instead and force every module under src/ into hiddenimports.
SRC_MODULES = sorted(
    ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
    for path in (PROJECT_ROOT / "src").rglob("*.py")
    if "__pycache__" not in path.parts
)
SRC_MODULES = [m.removesuffix(".__init__") for m in SRC_MODULES]

a = Analysis(
    [str(PROJECT_ROOT / "src" / "app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "src" / "themes" / "dark.qss"), "src/themes"),
        (str(PROJECT_ROOT / "src" / "themes" / "light.qss"), "src/themes"),
        (str(PROJECT_ROOT / "assets" / "icons"), "assets/icons"),
    ],
    hiddenimports=["keyboard", *SRC_MODULES],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="UniversalDeathCounter",
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
    icon=str(PROJECT_ROOT / "assets" / "icons" / "app_icon.ico"),
)
