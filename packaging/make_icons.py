"""
Regenerate the app icon set from assets/icons/logo_source.jpg.

Run from the project root after changing the logo:
    python packaging/make_icons.py

Outputs (all in assets/icons/):
* app_icon_<N>.png for N in 16..1024, app_icon.png (512) and a
  multi-size app_icon.ico for the .exe, installer, window and tray.
* Large sizes use the full logo; the tile's black corners become
  transparent. Sizes <= 48 px use a tighter crop of just the skull, since
  the "PHANTOM" text is unreadable that small (taskbar, tray, title bar).
* readme_banner.png: logo + app name for the README header.

Uses only PySide6 (already a dependency), no image libraries.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath

ICONS = Path(__file__).resolve().parents[1] / "assets" / "icons"
SOURCE = ICONS / "logo_source.jpg"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
SMALL_MAX = 48

# Regions of the 1024x1024 source (measured on the logo).
TILE = QRect(6, 6, 1012, 1012)  # the rounded tile, inside the black corners
TILE_RADIUS = 0.215  # corner radius as a fraction of the tile size
SKULL = QRect(200, 140, 625, 625)  # just the skull, above the "PHANTOM" text


def _rounded(image: QImage, radius_fraction: float) -> QImage:
    """Copy ``image`` with transparent corners outside a rounded square."""
    out = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    radius = image.width() * radius_fraction
    path.addRoundedRect(QRectF(out.rect()), radius, radius)
    painter.setClipPath(path)
    painter.drawImage(0, 0, image)
    painter.end()
    return out


def _scaled(image: QImage, size: int) -> QImage:
    return image.scaled(
        size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def _write_ico(path: Path, images: list[QImage]) -> None:
    """Multi-size .ico with PNG-compressed entries (supported since Vista)."""
    blobs = [_png_bytes(img) for img in images]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for img, blob in zip(images, blobs, strict=True):
        side = img.width() if img.width() < 256 else 0  # 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def _banner(full: QImage) -> QImage:
    """1280x320 README banner: logo on the left, name on the right."""
    banner = QImage(1280, 320, QImage.Format.Format_ARGB32_Premultiplied)
    banner.fill(QColor("#0b0b0e"))
    painter = QPainter(banner)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(QRect(40, 20, 280, 280), _scaled(full, 280))
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI", 54, QFont.Weight.Bold))
    painter.drawText(QRect(360, 70, 900, 90), Qt.AlignmentFlag.AlignLeft, "DePhantom")
    painter.setPen(QColor("#b56cff"))
    painter.setFont(QFont("Segoe UI", 28, QFont.Weight.DemiBold))
    painter.drawText(
        QRect(364, 170, 900, 60), Qt.AlignmentFlag.AlignLeft, "Universal Death Counter (DUDC)"
    )
    painter.end()
    return banner


def main() -> int:
    _app = QGuiApplication(sys.argv)  # needed for fonts in the banner
    source = QImage(str(SOURCE))
    if source.isNull():
        print(f"Cannot read {SOURCE}")
        return 1
    full = _rounded(source.copy(TILE), TILE_RADIUS)
    small = _rounded(source.copy(SKULL), 0.18)

    icons: dict[int, QImage] = {}
    for size in SIZES:
        icons[size] = _scaled(small if size <= SMALL_MAX else full, size)
        icons[size].save(str(ICONS / f"app_icon_{size}.png"))
    icons[512].save(str(ICONS / "app_icon.png"))
    _write_ico(ICONS / "app_icon.ico", [icons[s] for s in (16, 24, 32, 48, 64, 128, 256)])
    _banner(full).save(str(ICONS / "readme_banner.png"))
    print("Icons written to", ICONS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
