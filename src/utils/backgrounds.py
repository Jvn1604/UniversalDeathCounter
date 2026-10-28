"""
Background images for the main window and the overlay.

A picked image is copied (downscaled if huge) into ``BACKGROUNDS_DIR`` so
the setting keeps working if the original is moved, and so a 40-megapixel
photo doesn't sit in memory at full size.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QImage, QPixmap

from src.utils.constants import BACKGROUNDS_DIR
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Larger images are scaled down to this on import (plenty for a 4K screen).
MAX_IMAGE_SIDE: int = 2560
IMAGE_FILTER: str = "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif)"


def import_background(source: Path, dest_dir: Path = BACKGROUNDS_DIR) -> Path:
    """
    Copy an image into the app's backgrounds folder and return the copy's path.

    The copy is named after the image's content, so picking the same picture
    again reuses it. Photos are stored as JPEG, images with transparency as PNG.

    Raises:
        ValueError: If ``source`` isn't a readable image.
        OSError: If the copy can't be written.
    """
    image = QImage(str(source))
    if image.isNull():
        raise ValueError(f"{source.name} isn't an image this app can read.")
    if max(image.width(), image.height()) > MAX_IMAGE_SIDE:
        image = image.scaled(
            MAX_IMAGE_SIDE,
            MAX_IMAGE_SIDE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    digest = hashlib.sha1(source.read_bytes()).hexdigest()[:12]
    transparent = has_transparency(image)
    if not transparent:
        image = image.convertToFormat(QImage.Format.Format_RGB32)  # JPEG has no alpha
    suffix = ".png" if transparent else ".jpg"
    dest_dir.mkdir(parents=True, exist_ok=True)
    destination = dest_dir / f"bg-{digest}{suffix}"
    if not destination.exists() and not image.save(str(destination), quality=90):
        raise OSError(f"Couldn't save the image to {destination}.")
    logger.info("Imported background %s -> %s", source, destination)
    return destination


def has_transparency(image: QImage) -> bool:
    """
    Whether any pixel is see-through.

    Screenshots are often saved with an alpha channel that is fully opaque;
    those are stored as JPEG (~1 MB) instead of PNG (often 10+ MB).
    """
    if not image.hasAlphaChannel():
        return False
    argb = image.convertToFormat(QImage.Format.Format_ARGB32)
    rows = np.frombuffer(argb.constBits(), dtype=np.uint8, count=argb.sizeInBytes())
    pixels = rows.reshape(argb.height(), argb.bytesPerLine())[:, : argb.width() * 4]
    return bool((pixels[:, 3::4] < 255).any())  # bytes are B, G, R, A


def load_background(path: str) -> QPixmap | None:
    """The saved background at ``path``, or None if unset or missing."""
    if not path:
        return None
    pixmap = QPixmap(path)
    if pixmap.isNull():
        logger.warning("Background image not found or unreadable: %s", path)
        return None
    return pixmap


def cover(pixmap: QPixmap, size: QSize) -> QPixmap:
    """Scale ``pixmap`` to fill ``size`` completely, cropping the overflow evenly."""
    if size.isEmpty():
        return pixmap
    scaled = pixmap.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = (scaled.width() - size.width()) // 2
    y = (scaled.height() - size.height()) // 2
    return scaled.copy(QRect(x, y, size.width(), size.height()))
