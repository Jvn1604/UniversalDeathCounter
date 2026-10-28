"""
Render the UI icons (Lucide, ISC licence: packaging/icon_src/LICENSE) to PNG.

The app recolors these white PNGs at runtime (src/ui/icons.py), so the build
doesn't need Qt's SVG module. Run after adding an SVG to packaging/icon_src:

    python packaging/make_ui_icons.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packaging" / "icon_src"
TARGET = ROOT / "assets" / "icons" / "ui"
SIZE = 64  # crisp up to 32 px at 200 % scaling
# Small arrows the stylesheets use directly (QSS can't recolor images).
QSS_ARROWS = {
    "chevron-down": ("#8a8f9c", "#6b6f7b"),
    "chevron-up": ("#8a8f9c", "#6b6f7b"),
}


def render(svg: str, color: str, size: int) -> QImage:
    data = svg.replace("currentColor", color).replace('stroke-width="2"', 'stroke-width="2.1"')
    renderer = QSvgRenderer(QByteArray(data.encode()))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def main() -> int:
    QGuiApplication(sys.argv)
    TARGET.mkdir(parents=True, exist_ok=True)
    count = 0
    for svg_path in sorted(SOURCE.glob("*.svg")):
        svg = svg_path.read_text(encoding="utf-8")
        render(svg, "#ffffff", SIZE).save(str(TARGET / f"{svg_path.stem}.png"))
        count += 1
        if svg_path.stem in QSS_ARROWS:
            dark, light = QSS_ARROWS[svg_path.stem]
            render(svg, dark, 24).save(str(TARGET / f"{svg_path.stem}-dark.png"))
            render(svg, light, 24).save(str(TARGET / f"{svg_path.stem}-light.png"))
    print(f"Rendered {count} icons to {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
