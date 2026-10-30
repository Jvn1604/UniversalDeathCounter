# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for DePhantom Universal Death Counter (DUDC).

Build locally (from the project root, on the OS you're building for):
    pyinstaller packaging/UniversalDeathCounter.spec

The same spec builds all three: on macOS it also wraps the folder in
dist/UniversalDeathCounter.app; on Linux, packaging/make_appimage.sh turns
the folder into an AppImage.

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
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

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


def _windows_version_info():
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    return VSVersionInfo(
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
    excludes=["yaml"],  # a dev tool's (pre-commit) dependency, never imported
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
    # Platform and touch plugins: Windows only needs qwindows.
    "PySide6/plugins/platforms/qdirect2d",
    "PySide6/plugins/platforms/qminimal",
    "PySide6/plugins/platforms/libqminimal",
    "PySide6/plugins/platforms/qoffscreen",
    "PySide6/plugins/platforms/libqoffscreen",
    "PySide6/plugins/platforms/libqvnc",
    "PySide6/plugins/platforms/libqlinuxfb",
    "PySide6/plugins/platforms/libqeglfs",
    "PySide6/plugins/egldeviceintegrations/",
    # macOS frameworks of the same unused Qt parts.
    "QtQuick.framework",
    "QtQml",
    "QtPdf.framework",
    "QtNetwork.framework",
    "QtVirtualKeyboard",
    "QtSvg.framework",
    "PySide6/plugins/generic/",
    # Image formats nobody picks as a background (SVG would need Qt6Svg anyway).
    "PySide6/plugins/imageformats/qtiff",
    "PySide6/plugins/imageformats/qicns",
    "PySide6/plugins/imageformats/qpdf",
    "PySide6/plugins/imageformats/qsvg",
    "PySide6/plugins/imageformats/qtga",
    "PySide6/plugins/imageformats/qwbmp",
    # A second OpenSSL that only Qt's (excluded) networking would load;
    # Python's own ssl uses libssl-3.dll / libcrypto-3.dll.
    "libssl-3-x64.dll",
    "libcrypto-3-x64.dll",
)


def _is_unused_qt(dest_path):
    # macOS and Linux wheels keep Qt's plugins under PySide6/Qt/plugins.
    path = dest_path.replace("\\", "/").replace("PySide6/Qt/plugins/", "PySide6/plugins/")
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
    # macOS turns the PNG into an .icns (needs Pillow at build time).
    icon=str(PROJECT_ROOT / "assets" / "icons" / ("app_icon_1024.png" if IS_MAC else "app_icon.ico")),
    version=_windows_version_info() if IS_WINDOWS else None,
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

if IS_MAC:
    app = BUNDLE(
        coll,
        name="UniversalDeathCounter.app",
        icon=str(PROJECT_ROOT / "assets" / "icons" / "app_icon_1024.png"),
        bundle_identifier="com.dephantom.universaldeathcounter",
        version=APP_VERSION,
        info_plist={
            "CFBundleName": "DUDC",
            "CFBundleDisplayName": "DePhantom Universal Death Counter",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSHumanReadableCopyright": "MIT License",
        },
    )
