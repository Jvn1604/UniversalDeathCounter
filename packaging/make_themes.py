"""
Build the downloadable Glass and Clay themes (``themes/*.qss``).

Glass starts from Phantom Dark and Clay from Daylight: each gets its own
palette, then its own layer of rules on top (later rules win). Building them
from the built-in themes means every screen the built-in themes style is
styled in Glass and Clay too. The colored glow behind the panels is painted
by the main window (``ThemeInfo.backdrop``); the panels here are
see-through so it shows. Run after changing ``src/themes/dark.qss`` or
``light.qss``:

    python packaging/make_themes.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GLASS_PALETTE = {
    "rgba(255, 61, 85,": "rgba(200, 241, 105,",  # accent tints: crimson -> lime
    "#ff3d55": "#c8f169",
    "#0b0c10": "#0d0f12",  # window (see-through over the glow)
    "#0c0d12": "rgba(10, 12, 15, 0.50)",
    "#0f1016": "rgba(14, 16, 20, 0.50)",  # sidebar and top bar
    "#16171e": "rgba(26, 29, 34, 0.55)",  # cards
    "#1e2028": "rgba(255, 255, 255, 0.07)",  # controls
    "#22242d": "rgba(255, 255, 255, 0.10)",
    "#1a1c24": "rgba(255, 255, 255, 0.06)",
    "#2c2f3a": "rgba(255, 255, 255, 0.12)",  # borders
    "#262833": "rgba(255, 255, 255, 0.10)",
    "#1c1e26": "rgba(255, 255, 255, 0.08)",
    "#3c404d": "rgba(255, 255, 255, 0.22)",
    "#ececf1": "#f2f4f3",
    "#8a8f9c": "#a6adab",
    "#b3b6c2": "#c3c9c7",
    "#4f5361": "#7d8582",
}

GLASS_LAYER = """
/* ================================================================ Glass layer
 * Frosted dark panels over a lime and teal glow. Pop-ups stay solid so
 * they read over anything.
 */

QMainWindow, QDialog {
    background-color: #0d0f12;
}

QFrame#TopBar {
    background-color: rgba(12, 14, 17, 0.45);
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

QFrame#Sidebar {
    background-color: rgba(12, 14, 17, 0.40);
    border-right: 1px solid rgba(255, 255, 255, 0.08);
}

QFrame#Card, QFrame#StatTile {
    background-color: rgba(28, 31, 36, 0.46);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-top: 1px solid rgba(255, 255, 255, 0.20);
    border-radius: 20px;
}

QFrame#HeroCard {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(200, 241, 105, 0.16), stop: 0.55 rgba(26, 29, 34, 0.50),
        stop: 1 rgba(45, 212, 191, 0.14));
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-top: 1px solid rgba(255, 255, 255, 0.26);
    border-radius: 24px;
}

QPushButton {
    border-radius: 12px;
}

QPushButton#NavButton {
    border-radius: 14px;
}

QPushButton#NavButton:checked {
    color: #ffffff;
    background-color: rgba(200, 241, 105, 0.15);
    border: 1px solid rgba(200, 241, 105, 0.45);
}

QPushButton#AccentButton {
    color: #10140c;
    background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #def99a, stop: 1 #b2e34a);
    border: 1px solid rgba(255, 255, 255, 0.40);
    border-radius: 14px;
}

QPushButton#AccentButton:hover {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #e8fcb3, stop: 1 #c2ec62);
}

QPushButton#AccentButton QLabel {
    color: #10140c;
}

QPushButton#AccentButton QLabel#KeyCap {
    color: #10140c;
    background-color: rgba(0, 0, 0, 0.08);
    border: 1px solid rgba(0, 0, 0, 0.22);
    border-bottom: 2px solid rgba(0, 0, 0, 0.28);
}

QComboBox QAbstractItemView {
    selection-color: #10140c;
}

QListWidget::item:selected, QTableWidget::item:selected {
    color: #10140c;
}

QLabel#NavState[on="true"], QCheckBox::indicator:checked {
    color: #10140c;
}

QMenu, QComboBox QAbstractItemView, QComboBox QFrame, QToolTip {
    background-color: #16191d;
}

QMessageBox, QInputDialog, QProgressDialog, QColorDialog, QFileDialog {
    background-color: #111317;
}
"""

CLAY_PALETTE = {
    "rgba(227, 38, 63,": "rgba(108, 92, 231,",  # accent tints: red -> clay purple
    "#e3263f": "#6c5ce7",
    "rgba(17, 18, 22,": "rgba(46, 34, 120,",  # soft purple shadows instead of grey
    "#f3f4f8": "#efecfa",  # window (see-through over the pastel blobs)
    "#fafbfd": "#f8f6ff",
    "#fafbfc": "#f8f6ff",
    "#eef0f4": "#f3f0fd",
    "#eceef3": "#efebfb",
    "#e4e6ec": "#e9e4f8",
    "#e2e4ea": "#e6e0f8",
    "#d9dce4": "#ddd5f5",
    "#c3c7d1": "#c9bff0",
    "#1b1c21": "#1e2145",
    "#111216": "#15173a",
    "#626674": "#6b6890",
    "#7a7e8a": "#7d7a9e",
    "#555966": "#5c5980",
    "#4a4e5a": "#4e4b73",
    "#fff5f6": "#f6f3ff",
    "#ffdfe4": "#e7e1ff",
}

CLAY_LAYER = """
/* ================================================================ Clay layer
 * Soft, puffy white shapes on lavender with pastel blobs behind: a light
 * top edge and a deeper bottom edge make every card and button look
 * pressable, without shadow effects (they'd cost performance).
 */

QMainWindow, QDialog {
    background-color: #efecfa;
}

QFrame#TopBar {
    background-color: rgba(255, 255, 255, 0.55);
    border-bottom: 1px solid rgba(255, 255, 255, 0.85);
}

QFrame#Sidebar {
    background-color: rgba(255, 255, 255, 0.50);
    border-right: 1px solid rgba(255, 255, 255, 0.85);
}

QFrame#Card, QFrame#StatTile {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #ffffff, stop: 1 #f7f5ff);
    border: 1px solid #ffffff;
    border-bottom: 4px solid rgba(108, 92, 231, 0.14);
    border-radius: 22px;
}

QFrame#HeroCard {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #ffffff, stop: 0.6 #f6f3ff, stop: 1 #ebe5ff);
    border: 1px solid #ffffff;
    border-bottom: 5px solid rgba(108, 92, 231, 0.16);
    border-radius: 26px;
}

QPushButton {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #ffffff, stop: 1 #f2eefd);
    border: 1px solid #ffffff;
    border-bottom: 3px solid rgba(108, 92, 231, 0.18);
    border-radius: 14px;
}

QPushButton:pressed {
    border-bottom: 1px solid rgba(108, 92, 231, 0.18);
}

QPushButton#NavButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 14px;
}

QPushButton#NavButton:hover {
    background-color: rgba(255, 255, 255, 0.60);
}

QPushButton#NavButton:checked {
    color: #1e2145;
    background-color: #ffffff;
    border: 1px solid #ffffff;
    border-bottom: 3px solid rgba(108, 92, 231, 0.20);
}

QPushButton#AccentButton {
    color: #ffffff;
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #8a7cf3, stop: 1 #6150e2);
    border: 1px solid rgba(255, 255, 255, 0.45);
    border-bottom: 4px solid #4a3bc2;
    border-radius: 16px;
}

QPushButton#AccentButton:hover {
    background-color: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #978af6, stop: 1 #6c5ce7);
}

QPushButton#AccentButton:pressed {
    border-bottom: 1px solid #4a3bc2;
}

QPushButton#GhostButton, QPushButton#TopIconButton, QPushButton#CounterCaption {
    background-color: transparent;
    border: 1px solid transparent;
}

QPushButton#DangerButton {
    color: #d93a4a;
    border-bottom: 3px solid rgba(217, 58, 74, 0.25);
}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QKeySequenceEdit {
    background-color: #ffffff;
    border: 1px solid #e6e0f8;
    border-bottom: 2px solid #ddd5f5;
    border-radius: 12px;
}

QCheckBox::indicator {
    border-radius: 7px;
}

QMenu, QComboBox QAbstractItemView, QComboBox QFrame, QToolTip {
    background-color: #ffffff;
}

QMessageBox, QInputDialog, QProgressDialog, QColorDialog, QFileDialog {
    background-color: #f6f4fd;
}
"""

HEADERS = {
    "glass": "/*\n * Glass: frosted dark panels over a lime and teal glow.\n"
    " * Built by packaging/make_themes.py from Phantom Dark:\n"
    " * edit that script, not this file.\n */\n",
    "clay": "/*\n * Clay: soft, puffy white shapes on lavender with pastel blobs.\n"
    " * Built by packaging/make_themes.py from Daylight:\n"
    " * edit that script, not this file.\n */\n",
}


def build(source: str, palette: dict[str, str], layer: str, header: str) -> str:
    text = (ROOT / "src" / "themes" / f"{source}.qss").read_text(encoding="utf-8")
    text = text[text.index("*/") + 2 :].lstrip("\n")  # drop the source theme's header
    for old, new in palette.items():
        text = text.replace(old, new)
    return header + "\n" + text.rstrip() + "\n" + layer


def main() -> int:
    for name, source, palette, layer in (
        ("glass", "dark", GLASS_PALETTE, GLASS_LAYER),
        ("clay", "light", CLAY_PALETTE, CLAY_LAYER),
    ):
        target = ROOT / "themes" / f"{name}.qss"
        target.write_text(build(source, palette, layer, HEADERS[name]), encoding="utf-8")
        print(f"Wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
