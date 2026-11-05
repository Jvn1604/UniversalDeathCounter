"""
Fonts that keep memory down: a list of fonts, or a character the font lacks,
makes Qt load every fallback font (about 45 MB). The themes name one font each,
and the app only shows characters that font has (icons instead of ticks).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]


def test_themes_name_one_font_at_a_time() -> None:
    sheets = [*ROOT.glob("src/themes/*.qss"), *ROOT.glob("themes/*.qss")]
    assert sheets
    for sheet in sheets:
        for declaration in re.findall(r"font-family:[^;]*;", sheet.read_text(encoding="utf-8")):
            assert "," not in declaration, (sheet.name, declaration)
            assert "Variable" not in declaration, (sheet.name, declaration)


# Characters drawn on purpose with a font that has them, and text that never
# shows in the app (web pages, comments).
_ALLOWED = {
    "src/overlay/designs.py": "死",  # the Kanji Seal, in a Japanese font
    "src/detection/matchers.py": "死",  # a docstring
    "src/hotkeys/mac_hotkeys.py": "⌘",  # macOS labels, in the Mac's font
}
_WEB_PAGES = ("src/utils/phone_remote.py", "src/utils/stream_overlay.py")


def test_the_app_only_shows_characters_its_font_has() -> None:
    from PySide6.QtGui import QFont, QRawFont
    from PySide6.QtWidgets import QApplication

    from src.utils.platform_info import IS_WINDOWS

    if not IS_WINDOWS:
        pytest.skip("checks Segoe UI, the Windows font")
    QApplication.instance() or QApplication([])
    font = QRawFont.fromFont(QFont("Segoe UI"))
    missing = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        name = path.relative_to(ROOT).as_posix()
        if name in _WEB_PAGES:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for char in line:
                if (ord(char) > 127 and char not in _ALLOWED.get(name, "")
                        and not font.supportsCharacter(ord(char))):
                    missing.append(f"{name}:{number} {char!r}")
    # Each would make Qt load every fallback font (about 45 MB) when shown.
    assert not missing, missing
