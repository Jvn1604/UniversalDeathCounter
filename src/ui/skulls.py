"""
Skull evolution: the death count's badge grows meaner every 10 deaths.

0 is a plain skull; each tier adds something (horns, a nose ring, cheek
blades, a crown, a third eye, burning eyes, flames, an aura). Past 100 the
skull keeps its full form and changes colour at 150, 200, 300, 500 and 1000.

Everything is drawn with QPainter paths in a 100×100 design space: no image
files, any size stays sharp, and each (tier, size, colour) is drawn once and
cached, so the overlay and Home page pay nothing per death.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QTransform,
)


@dataclass(frozen=True)
class Tier:
    deaths: int  # reached at this many deaths
    name: str
    aura: str = ""  # past 100: the colour that marks the tier
    body: str = ""  # the skull's own colour, if not the theme's


TIERS: tuple[Tier, ...] = (
    Tier(0, "Fresh Spawn"),
    Tier(10, "Bruised"),
    Tier(20, "Horned"),
    Tier(30, "Bloodied"),
    Tier(40, "Hellbound"),
    Tier(50, "Demon"),
    Tier(60, "Fiend"),
    Tier(70, "Infernal"),
    Tier(80, "Archdemon"),
    Tier(90, "Undying"),
    Tier(100, "Death Incarnate"),
    Tier(150, "Gilded Reaper", "#ffc247"),
    Tier(200, "Void Walker", "#a970ff"),
    Tier(300, "Frostbound Lich", "#4fd4ff"),
    Tier(500, "Eternal", "#5dff9a"),
    Tier(1000, "God of Death", "#ff3d55", "#ffd36b"),
)
_FULL_FORM = 10  # TIERS[10]: every feature on; later tiers only recolour


def tier_index(deaths: int) -> int:
    """Which tier a death count has reached."""
    index = 0
    for number, tier in enumerate(TIERS):
        if deaths >= tier.deaths:
            index = number
    return index


def next_tier(deaths: int) -> tuple[Tier | None, float]:
    """The next tier (None at the top) and how far along the way to it (0–1)."""
    index = tier_index(deaths)
    if index + 1 >= len(TIERS):
        return None, 1.0
    low, high = TIERS[index].deaths, TIERS[index + 1].deaths
    return TIERS[index + 1], (max(deaths, 0) - low) / (high - low)


def skull_pixmap(
    deaths: int, size: int, color: str = "#ececf1", accent: str = "#ff3d55", ratio: float = 1.0
) -> QPixmap:
    """The badge for a death count, ``size`` logical pixels square."""
    return _pixmap(tier_index(deaths), size, color, accent, round(ratio * 4) / 4)


@lru_cache(maxsize=48)
def _pixmap(tier: int, size: int, color: str, accent: str, ratio: float) -> QPixmap:
    pixels = max(1, round(size * ratio))
    image = QImage(pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(pixels / 100, pixels / 100)
    _draw(painter, tier, QColor(TIERS[tier].body or color), QColor(TIERS[tier].aura or accent))
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


# ---------------------------------------------------------------------------
# Drawing (100 × 100 design space, skull centred on x = 50)
# ---------------------------------------------------------------------------
def _mirrored(path: QPainterPath) -> QPainterPath:
    """The path plus its mirror image across the centre line."""
    flip = QTransform(-1, 0, 0, 1, 100, 0)
    return path.united(flip.map(path))


def _polygon(*points: tuple[float, float]) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    path.closeSubpath()
    return path


def _head() -> QPainterPath:
    head = QPainterPath()
    head.addEllipse(QPointF(50, 46), 26, 25)
    jaw = QPainterPath()
    jaw.addRoundedRect(QRectF(34, 58, 32, 24), 7, 7)
    cheeks = QPainterPath()
    cheeks.addRoundedRect(QRectF(26.5, 46, 47, 18), 9, 9)
    return head.united(jaw).united(cheeks)


def _eyes(angry: bool) -> QPainterPath:
    eye = QPainterPath()
    eye.addEllipse(QPointF(39.5, 53), 8.2, 7.2)
    if angry:  # a slanted brow cuts the top: a scowl
        eye = eye.intersected(_polygon((28, 50), (49, 54.5), (49, 66), (28, 66)))
    return _mirrored(eye)


def _holes(tier: int) -> QPainterPath:
    holes = _eyes(angry=tier >= 1)
    nose = QPainterPath()
    nose.moveTo(50, 59.5)
    nose.cubicTo(52.5, 62, 54, 65, 53, 67.5)
    nose.lineTo(47, 67.5)
    nose.cubicTo(46, 65, 47.5, 62, 50, 59.5)
    holes = holes.united(nose)
    mouth = QPainterPath()
    mouth.addRect(QRectF(37.5, 72.6, 25, 1.7))
    for x in (41.6, 46, 50.4 - 0.4, 54.4, 58.6):
        mouth.addRect(QRectF(x - 0.8, 72.6, 1.6, 9.5))
    holes = holes.united(mouth)
    if tier >= 5:  # third eye
        holes = holes.united(_polygon((50, 30), (53.2, 35.5), (50, 41), (46.8, 35.5)))
    return holes


def _horns(tier: int) -> QPainterPath:
    horn = QPainterPath()
    if tier == 0:
        return horn
    if tier == 1:  # nubs
        horn.moveTo(29.5, 34)
        horn.quadTo(24, 25, 27.5, 16)
        horn.quadTo(31, 24, 37.5, 26.5)
    elif tier in (2, 3):  # proper horns
        horn.moveTo(28.5, 37)
        horn.cubicTo(20, 30, 19, 18, 23, 6)
        horn.cubicTo(26, 17, 30, 23, 38.5, 25.5)
    else:  # great sweeping horns
        horn.moveTo(27.5, 39)
        horn.cubicTo(12, 36, 7, 20, 13, 2)
        horn.cubicTo(16, 15, 23, 23, 38.5, 25)
    horn.closeSubpath()
    return _mirrored(horn)


def _blades(tier: int) -> QPainterPath:
    """Cheek blades (30+) and, from 80, a second pair along the jaw."""
    blades = QPainterPath()
    if tier >= 3:
        blades = blades.united(_polygon((28, 50), (16, 57), (28.5, 61)))
    if tier >= 8:
        blades = blades.united(_polygon((35, 68), (25, 76), (36, 77)))
    return _mirrored(blades)


def _crown(tier: int) -> QPainterPath:
    crown = QPainterPath()
    if tier >= 4:  # one spike
        crown = crown.united(_polygon((46.5, 24), (50, 6), (53.5, 24)))
    if tier >= 7:  # three
        crown = crown.united(_mirrored(_polygon((37, 26.5), (37.5, 11), (43.5, 23.5))))
    if tier >= 10:  # five
        crown = crown.united(_mirrored(_polygon((29.5, 32), (26, 19), (35, 27.5))))
    return crown


def _flames() -> QPainterPath:
    """Tongues of fire licking up behind the skull (70+)."""
    fire = QPainterPath()
    for x, base, height, width in (
        (20, 66, 34, 6), (27, 50, 22, 6), (80, 66, 34, 6), (73, 50, 22, 6),
        (43, 26, 22, 5), (57, 26, 22, 5),
    ):
        tongue = QPainterPath()
        lean = width * (0.35 if x < 50 else -0.35)  # tips lean outward
        tongue.moveTo(x - width, base)
        tongue.quadTo(x - width * 0.7, base - height * 0.6, x - lean, base - height)
        tongue.quadTo(x + width * 0.4, base - height * 0.45, x + width, base)
        tongue.closeSubpath()
        fire = fire.united(tongue)
    return fire


def _draw(painter: QPainter, tier: int, color: QColor, accent: QColor) -> None:
    form = min(tier, _FULL_FORM)
    if form >= 9:  # aura
        glow = QRadialGradient(QPointF(50, 50), 50)
        halo = QColor(accent)
        halo.setAlpha(110 if tier > _FULL_FORM else 80)
        glow.setColorAt(0.35, halo)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(QRectF(0, 0, 100, 100), glow)
    if form >= 6:
        fire = QColor(accent)
        fire.setAlpha(150)
        painter.fillPath(_flames() if form >= 7 else QPainterPath(), fire)

    body = _head().united(_horns(form)).united(_blades(form)).united(_crown(form))
    holes = _holes(form)
    painter.fillPath(body.subtracted(holes), color)

    if form >= 2:  # nose ring
        painter.setPen(QPen(color, 2.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(50, 86.5), 4.6, 4.6)
    if form >= 6:  # burning eyes
        eyes = _eyes(angry=True)
        if form >= 5:
            eyes = eyes.united(_polygon((50, 30), (53.2, 35.5), (50, 41), (46.8, 35.5)))
        painter.fillPath(eyes, accent)
