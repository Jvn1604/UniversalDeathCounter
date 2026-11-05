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


def _run_with_real_fonts(code: str) -> str:
    """
    Run ``code`` in a Python with Windows' own fonts: the tests' offscreen
    platform has none, so every font check there says yes.
    """
    import os
    import subprocess

    env = {**os.environ, "QT_QPA_PLATFORM": "windows", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
        text=True, encoding="utf-8", timeout=120, check=True,
    )
    return result.stdout.strip()


def test_the_app_only_shows_characters_its_font_has() -> None:
    from src.utils.platform_info import IS_WINDOWS

    if not IS_WINDOWS:
        pytest.skip("checks Segoe UI, the Windows font")
    places: dict[str, list[str]] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        name = path.relative_to(ROOT).as_posix()
        if name in _WEB_PAGES:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for char in line:
                if ord(char) > 127 and char not in _ALLOWED.get(name, ""):
                    places.setdefault(char, []).append(f"{name}:{number}")
    codes = [ord(char) for char in places]
    lacking = _run_with_real_fonts(_FONT_CHECK.format(codes=codes))
    # Each would make Qt load every fallback font (about 45 MB) when shown.
    missing = [chr(int(code)) for code in lacking.split()]
    assert not missing, {char: places[char] for char in missing}


_FONT_CHECK = """
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QRawFont
app = QApplication([])
font = QRawFont.fromFont(QFont("Segoe UI"))
assert font.familyName() == "Segoe UI"
print(" ".join(str(c) for c in {codes} if not font.supportsCharacter(c)))
"""

_DRAWABLE_CHECK = """
from PySide6.QtWidgets import QApplication
from src.ui.widgets import drawable
app = QApplication([])
for text in ("Phantom Blade Zero " + chr(0x1F608) + " Day 5 | Eren",
             "Caf" + chr(0xE9) + " " + chr(0x2014) + " vu " + chr(0xB7) + " 3"):
    print(ascii(drawable(text)))
"""


def test_titles_from_other_programs_lose_what_the_font_lacks() -> None:
    from src.utils.platform_info import IS_WINDOWS

    if not IS_WINDOWS:
        pytest.skip("checks Segoe UI, the Windows font")
    shown = _run_with_real_fonts(_DRAWABLE_CHECK).splitlines()
    assert shown == [ascii("Phantom Blade Zero Day 5 | Eren"), ascii("Café — vu · 3")]
