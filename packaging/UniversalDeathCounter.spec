# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for DePhantom Universal Death Counter (DUDC).

Build locally (Windows, from the project root):
    pyinstaller packaging/UniversalDeathCounter.spec

Produces a folder build at dist/UniversalDeathCounter/ (the .exe plus its
libraries in _internal/). A folder build is used instead of a single-file
.exe because one-file builds unpack themselves to a temp folder at every
launch, which antivirus heuristics often flag. The installer ships the
whole folder, so users never see the difference. UPX compression is off
for the same reason.

The .exe also carries Windows version info (Properties → Details) read
from APP_VERSION in src/utils/constants.py, the single source of truth.
"""

import re
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

block_cipher = None

# Resolve project root relative to this spec file so the build works
# regardless of the current working directory it's invoked from.
PROJECT_ROOT = Path(SPECPATH).resolve().parent

APP_VERSION = re.search(
    r'^APP_VERSION: str = "([^"]+)"',
    (PROJECT_ROOT / "src" / "utils" / "constants.py").read_text(encoding="utf-8"),
    re.MULTILINE,
).group(1)
_numeric = [int(p) for p in re.findall(r"\d+", APP_VERSION)[:4]]
VERSION_TUPLE = tuple(_numeric + [0] * (4 - len(_numeric)))

VERSION_INFO = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "Jeeventhiran Sivanantham"),
                        StringStruct("FileDescription", "DePhantom Universal Death Counter (DUDC)"),
                        StringStruct("FileVersion", APP_VERSION),
                        StringStruct("InternalName", "UniversalDeathCounter"),
                        StringStruct("LegalCopyright", "MIT License"),
                        StringStruct("OriginalFilename", "UniversalDeathCounter.exe"),
                        StringStruct("ProductName", "DePhantom Universal Death Counter"),
                        StringStruct("ProductVersion", APP_VERSION),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

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
    hiddenimports=SRC_MODULES,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Keep the install lightweight: drop Qt parts the app never loads. At runtime
# the app needs only Qt Core/Gui/Widgets plus Charts (which itself loads
# Qt6OpenGL + Qt6OpenGLWidgets). PyInstaller's PySide6 hooks still bundle
# QML/Quick, PDF, Network, the virtual keyboard, the ~20 MB software OpenGL
# renderer (opengl32sw.dll), and translations, so filter them out here.
_UNUSED_QT = (
    "opengl32sw.dll",
    "Qt6Quick",
    "Qt6Qml",
    "Qt6Pdf",
    "Qt6Network",
    "Qt6VirtualKeyboard",
    "Qt6Svg",
    "PySide6/QtOpenGL.pyd",
    "PySide6/QtOpenGLWidgets.pyd",
    "PySide6/QtNetwork.pyd",
    "PySide6/translations/",
    "PySide6/plugins/networkinformation/",
    "PySide6/plugins/tls/",
    "PySide6/plugins/platforminputcontexts/",
    "PySide6/plugins/iconengines/",
)


def _is_unused_qt(dest_path):
    path = dest_path.replace("\\", "/")
    return any(part in path for part in _UNUSED_QT)


a.binaries = [entry for entry in a.binaries if not _is_unused_qt(entry[0])]
a.datas = [entry for entry in a.datas if not _is_unused_qt(entry[0])]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="UniversalDeathCounter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "assets" / "icons" / "app_icon.ico"),
    version=VERSION_INFO,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="UniversalDeathCounter",
)
