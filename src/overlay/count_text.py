"""
How the overlay writes its count, e.g. "DEATH - 12", "12 DEATHS" or "TRIES: 12".

Shared by the overlay window and the stream page (OBS Browser Source), so both
look the same: the word, the separator between word and number, which comes
first, and the word's own colour and size next to the number's.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from src.utils.constants import (
    ACCENT_COLOR,
    SETTING_OVERLAY_COUNT_LABEL,
    SETTING_OVERLAY_LETTER_SPACING,
    SETTING_OVERLAY_NUMBER_BOLD,
    SETTING_OVERLAY_SEPARATOR,
    SETTING_OVERLAY_TEXT_COLOR,
    SETTING_OVERLAY_WORD_AFTER,
    SETTING_OVERLAY_WORD_COLOR,
    SETTING_OVERLAY_WORD_SIZE,
)

# Separators offered in Settings: (stored value, label). Any other text works too.
SEPARATORS: tuple[tuple[str, str], ...] = (
    ("-", "Dash  ( DEATH - 12 )"),
    (":", "Colon  ( DEATH: 12 )"),
    ("×", "Times  ( DEATH × 12 )"),
    ("·", "Dot  ( DEATH · 12 )"),
    ("|", "Bar  ( DEATH | 12 )"),
    ("", "None  ( DEATH 12 )"),
)


def _int(settings: dict[str, str], key: str, default: int, low: int, high: int) -> int:
    try:
        return min(max(int(settings.get(key, default)), low), high)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class CountStyle:
    word: str = "DEATH"
    separator: str = "-"
    word_after: bool = False  # "12 DEATHS" instead of "DEATHS - 12"
    word_color: str = ""  # "" = the number's colour
    number_color: str = ACCENT_COLOR
    word_size: int = 100  # % of the number's size
    bold: bool = True
    letter_spacing: int = 0  # px

    @classmethod
    def from_settings(cls, settings: dict[str, str]) -> CountStyle:
        return cls(
            word=settings.get(SETTING_OVERLAY_COUNT_LABEL, "DEATH").strip(),
            separator=settings.get(SETTING_OVERLAY_SEPARATOR, "-").strip(),
            word_after=settings.get(SETTING_OVERLAY_WORD_AFTER, "false") == "true",
            word_color=settings.get(SETTING_OVERLAY_WORD_COLOR, ""),
            number_color=settings.get(SETTING_OVERLAY_TEXT_COLOR, ACCENT_COLOR) or ACCENT_COLOR,
            word_size=_int(settings, SETTING_OVERLAY_WORD_SIZE, 100, 30, 200),
            bold=settings.get(SETTING_OVERLAY_NUMBER_BOLD, "true") == "true",
            letter_spacing=_int(settings, SETTING_OVERLAY_LETTER_SPACING, 0, -4, 20),
        )

    def _parts(self, number: int) -> list[tuple[str, str]]:
        """(kind, text) in reading order: "word", "sep" and "number"."""
        if not self.word:
            return [("number", str(number))]
        if self.word_after:
            parts = [("number", str(number))]
            if self.separator:
                parts.append(("sep", f" {self.separator} "))
            else:
                parts.append(("sep", " "))
            return [*parts, ("word", self.word)]
        separator = (
            f"{self.separator} " if self.separator == ":"
            else f" {self.separator} " if self.separator
            else " "
        )
        return [("word", self.word), ("sep", separator), ("number", str(number))]

    def needs_html(self) -> bool:
        """Only a different word colour or size needs rich text (slower to set up)."""
        return bool(self.word_color) and self.word_color != self.number_color or (
            self.word_size != 100 and bool(self.word)
        )

    def plain(self, number: int) -> str:
        """As plain text, e.g. ``DEATH - 12``."""
        return "".join(text for _kind, text in self._parts(number))

    def html(self, number: int, size_px: int) -> str:
        """As HTML spans with each part's colour and size (Qt labels and the stream page)."""
        word_color = self.word_color or self.number_color
        word_px = max(6, round(size_px * self.word_size / 100))
        styles = {
            "word": f"color:{word_color};font-size:{word_px}px",
            "sep": f"color:{word_color};font-size:{word_px}px",
            "number": f"color:{self.number_color};font-size:{size_px}px",
        }
        return "".join(
            f'<span class="{kind}" style="{styles[kind]}">'
            f"{escape(text).replace(' ', '&nbsp;')}</span>"
            for kind, text in self._parts(number)
        )
