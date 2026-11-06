"""
Overlay designs: whole looks for the death count, drawn in code.

``classic`` is the regular overlay (card, lines of text, skull). The others
are drawn here on a fixed canvas, scaled to fit the overlay window, so they
cost no image files and stay sharp at any size:

* ``seal``: a red seal with 死 ("death"), the word and the count
* ``neon``: a glowing neon-tube sign, script word, neon skull and count
* ``tombstone``: an R.I.P. gravestone with candles, a pumpkin and a ghost
* ``banner``: a gothic title with ornate swirls over the count

Each shows the evolving skull (a new look every 10 deaths, new colours past
100: :mod:`src.ui.skulls`) in its own style.

The same drawing makes the picture the OBS Browser Source page shows.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QTransform,
)

from src.ui.skulls import draw_skull, skull_shape, tier_colors

DESIGNS: tuple[tuple[str, str], ...] = (
    ("classic", "Classic card"),
    ("seal", "Kanji Seal"),
    ("neon", "Neon Sign"),
    ("tombstone", "Tombstone"),
    ("banner", "Death Banner"),
)
# Each design's canvas (width, height); it's scaled to fit, keeping its shape.
_CANVAS = {
    "seal": (320, 100),
    "neon": (380, 200),
    "tombstone": (380, 330),
    "banner": (440, 230),
}
_SANS = ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"]
_SCRIPT = ["Segoe Script", "Brush Script MT", "Snell Roundhand", "URW Chancery L"]
_GOTHIC = ["Old English Text MT", "UnifrakturMaguntia", "Blackadder ITC", "Georgia", "serif"]
_KANJI = ["Yu Mincho", "MS Mincho", "Hiragino Mincho ProN", "Noto Serif CJK JP",
          "Yu Gothic", "Noto Sans CJK JP"]


def is_design(name: str) -> bool:
    return name in _CANVAS


def word_for(word: str) -> str:
    """The word a design shows: "DEATH" (the default) reads "Deaths" there."""
    return "Deaths" if word.strip().upper() == "DEATH" else word.strip()


@lru_cache(maxsize=16)
def _installed(families: tuple[str, ...]) -> str:
    """The first of ``families`` on this PC ("" for the default font)."""
    installed = set(QFontDatabase.families())
    return next((family for family in families if family in installed), "")


def _font(families: list[str], size: float, weight: int = 700, italic: bool = False) -> QFont:
    # One family, not the list: a list makes Qt load every fallback font (~45 MB).
    font = QFont()
    family = _installed(tuple(families))
    if family:
        font.setFamily(family)
    font.setPixelSize(max(1, round(size)))
    font.setWeight(QFont.Weight(weight))
    font.setItalic(italic)
    return font


def _text_path(font: QFont, text: str, center_x: float, baseline: float) -> QPainterPath:
    path = QPainterPath()
    width = QFontMetricsF(font).horizontalAdvance(text)
    path.addText(center_x - width / 2, baseline, font, text)
    return path


def _fit_font(families: list[str], text: str, size: float, max_width: float,
              weight: int = 800, italic: bool = False) -> QFont:
    """``size`` px, smaller if ``text`` would be wider than ``max_width``."""
    font = _font(families, size, weight, italic)
    width = QFontMetricsF(font).horizontalAdvance(text)
    if width > max_width > 0:
        font = _font(families, size * max_width / width, weight, italic)
    return font


def _glow(painter: QPainter, path: QPainterPath, color: QColor, width: float,
          fill: bool = False) -> None:
    """Neon: wide faint strokes under a bright core."""
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for spread, alpha in ((7.0, 22), (4.5, 40), (2.6, 80)):
        glow = QColor(color)
        glow.setAlpha(alpha)
        painter.setPen(QPen(glow, width * spread, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)
    core = QColor(color).lighter(150)
    painter.setPen(QPen(core, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    if fill:
        painter.setBrush(core)
    painter.drawPath(path)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def paint_design(
    painter: QPainter, rect: QRectF, design: str, word: str, number: int, skull: bool = True
) -> None:
    """Draw ``design`` centered in ``rect``, as large as fits (``skull``: with the skull)."""
    width, height = _CANVAS[design]
    scale = min(rect.width() / width, rect.height() / height)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.translate(rect.center().x() - width * scale / 2,
                      rect.center().y() - height * scale / 2)
    painter.scale(scale, scale)
    {"seal": _seal, "neon": _neon, "tombstone": _tombstone, "banner": _banner}[design](
        painter, word_for(word), number, skull
    )
    painter.restore()


def render_png(
    design: str, word: str, number: int, width: int = 760, skull: bool = True
) -> bytes:
    """The design as a transparent PNG (for the OBS Browser Source page)."""
    canvas_w, canvas_h = _CANVAS[design]
    image = QImage(width, round(width * canvas_h / canvas_w), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    paint_design(painter, QRectF(image.rect()), design, word, number, skull)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def _skull_at(deaths: int, rect: QRectF) -> QPainterPath:
    """The evolving skull's shape, scaled into ``rect``."""
    transform = QTransform()
    transform.translate(rect.left(), rect.top())
    transform.scale(rect.width() / 100, rect.height() / 100)
    return transform.map(skull_shape(deaths))


# ---------------------------------------------------------------- Kanji Seal
def _seal(painter: QPainter, word: str, deaths: int, skull: bool) -> None:
    number = str(deaths)
    strip = QLinearGradient(0, 0, 320, 0)
    strip.setColorAt(0, QColor(10, 10, 12, 215))
    strip.setColorAt(0.75, QColor(10, 10, 12, 170))
    strip.setColorAt(1, QColor(10, 10, 12, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(strip)
    painter.drawRect(QRectF(0, 6, 320, 88))
    # The seal: a red square with a thin inner frame, 死 in white.
    seal = QRectF(14, 13, 74, 74)
    painter.setBrush(QColor("#c4161c"))
    painter.drawRect(seal)
    painter.setPen(QPen(QColor(255, 235, 230, 170), 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(seal.adjusted(5, 5, -5, -5))
    kanji = _font(_KANJI, 50, 700)
    painter.setPen(QColor("#fbf3ee"))
    if _installed(tuple(_KANJI)):
        painter.setFont(kanji)
        painter.drawText(seal, Qt.AlignmentFlag.AlignCenter, "死")
    else:  # no Japanese font here: a cross instead
        painter.setFont(_font(_SANS, 44, 800))
        painter.drawText(seal, Qt.AlignmentFlag.AlignCenter, "†")
    if word:
        label = _font(_SANS, 15, 800)
        label.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4.5)
        painter.setFont(label)
        painter.setPen(QColor("#d9d4cf"))
        painter.drawText(QPointF(104, 36), word.upper())
    painter.setFont(_fit_font(_SANS, number, 52, 128))
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QPointF(102, 86), number)
    if skull:  # the evolving skull on the right, white with the seal's red
        draw_skull(painter, deaths, QRectF(240, 17, 66, 66), "#f4efea", "#e0262e")


# ---------------------------------------------------------------- Neon Sign
def _neon(painter: QPainter, word: str, deaths: int, skull: bool) -> None:
    number = str(deaths)
    panel = QRectF(8, 26, 364, 168)
    painter.setPen(QPen(QColor(255, 255, 255, 30), 1.5))
    painter.setBrush(QColor(28, 14, 38, 225))
    painter.drawRoundedRect(panel, 24, 24)
    pink = QColor("#ff4fd8")
    tube = QPainterPath()
    tube.addRoundedRect(QRectF(26, 50, 328, 124), 14, 14)
    _glow(painter, tube, pink, 2.4)
    if word:
        script = _fit_font(_SCRIPT, word, 46, 230, 400)
        text = _text_path(script, word, 190, 64)
        gap = text.boundingRect().adjusted(-16, -4, 16, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(28, 14, 38, 255))
        painter.drawRect(QRectF(gap.left(), 42, gap.width(), 16))  # a gap in the tube
        for x in (gap.left(), gap.right()):  # the tube's mounts
            painter.setBrush(QColor("#0d0710"))
            painter.drawEllipse(QPointF(x, 50), 4.2, 4.2)
        _glow(painter, text, QColor("#ff9ff0"), 1.0, fill=True)
    cyan = QColor("#4ee6ff")
    if skull:  # the evolving skull as neon tubes: cyan, or its tier's colour past 100
        _body, tier = tier_colors(deaths, "#4ee6ff", "#4ee6ff")
        _glow(painter, _skull_at(deaths, QRectF(62, 72, 92, 92)), tier, 1.8)
        digits = _fit_font(_SANS, number, 78, 190, 600)
        _glow(painter, _text_path(digits, number, 250, 150), cyan, 1.2, fill=True)
    else:  # the number alone, in the middle
        digits = _fit_font(_SANS, number, 84, 290, 600)
        _glow(painter, _text_path(digits, number, 190, 150), cyan, 1.2, fill=True)


# ---------------------------------------------------------------- Tombstone
def _candle(painter: QPainter, x: float, base: float) -> None:
    glow = QRadialGradient(QPointF(x, base - 66), 46)
    glow.setColorAt(0, QColor(255, 196, 92, 110))
    glow.setColorAt(1, QColor(255, 160, 60, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(QPointF(x, base - 66), 46, 46)
    painter.setBrush(QColor("#f6ead8"))
    painter.setPen(QPen(QColor("#d8c4a8"), 1.5))
    painter.drawRoundedRect(QRectF(x - 11, base - 54, 22, 54), 4, 4)
    flame = QPainterPath()
    flame.moveTo(x, base - 84)
    flame.cubicTo(x + 9, base - 70, x + 8, base - 58, x, base - 57)
    flame.cubicTo(x - 8, base - 58, x - 9, base - 70, x, base - 84)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffc94d"))
    painter.drawPath(flame)
    painter.setBrush(QColor("#fff3c4"))
    painter.drawEllipse(QPointF(x, base - 63), 3, 5)


def _pumpkin(painter: QPainter, x: float, y: float) -> None:
    painter.setPen(QPen(QColor("#b44d12"), 1.5))
    for dx, w in ((-22, 34), (22, 34), (0, 40)):
        painter.setBrush(QColor("#f08a24") if dx == 0 else QColor("#e07a1a"))
        painter.drawEllipse(QRectF(x + dx - w / 2, y, w, 52))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#4f7a2a"))
    painter.drawRoundedRect(QRectF(x - 3, y - 9, 7, 12), 2, 2)
    painter.setBrush(QColor("#3b1a07"))
    for eye in (-12, 12):
        triangle = QPainterPath()
        triangle.moveTo(x + eye - 6, y + 25)
        triangle.lineTo(x + eye + 6, y + 25)
        triangle.lineTo(x + eye, y + 15)
        triangle.closeSubpath()
        painter.drawPath(triangle)
    mouth = QPainterPath()
    mouth.moveTo(x - 15, y + 32)
    mouth.quadTo(x, y + 46, x + 15, y + 32)
    mouth.quadTo(x, y + 39, x - 15, y + 32)
    painter.drawPath(mouth)


def _ghost(painter: QPainter, x: float, y: float) -> None:
    body = QPainterPath()
    body.moveTo(x, y + 60)
    body.lineTo(x, y + 26)
    body.cubicTo(x, y - 6, x + 52, y - 6, x + 52, y + 26)
    body.lineTo(x + 52, y + 60)
    for step in range(4):  # a wavy hem
        right = x + 52 - step * 13
        body.quadTo(right - 6.5, y + 52 + (8 if step % 2 == 0 else -2), right - 13, y + 60)
    painter.setPen(QPen(QColor("#a9c9c4"), 1.5))
    painter.setBrush(QColor("#eefcf8"))
    painter.drawPath(body)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2a2340"))
    painter.drawEllipse(QPointF(x + 18, y + 27), 3.4, 4.2)
    painter.drawEllipse(QPointF(x + 34, y + 27), 3.4, 4.2)
    painter.setBrush(QColor(255, 150, 170, 150))
    painter.drawEllipse(QPointF(x + 12, y + 36), 4, 2.6)
    painter.drawEllipse(QPointF(x + 40, y + 36), 4, 2.6)


def _tombstone(painter: QPainter, word: str, deaths: int, skull: bool) -> None:
    number = str(deaths)
    _candle(painter, 48, 292)
    _candle(painter, 332, 292)
    stone = QPainterPath()
    stone.moveTo(98, 284)
    stone.lineTo(98, 120)
    stone.cubicTo(98, 36, 282, 36, 282, 120)
    stone.lineTo(282, 284)
    stone.closeSubpath()
    fill = QLinearGradient(0, 40, 0, 284)
    fill.setColorAt(0, QColor("#8a7fae"))
    fill.setColorAt(1, QColor("#5d527f"))
    painter.setPen(QPen(QColor("#f4ebe1"), 7, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(fill)
    painter.drawPath(stone)
    shine = QPainterPath()  # light along the arch
    shine.moveTo(114, 112)
    shine.cubicTo(118, 70, 150, 58, 172, 56)
    painter.setPen(QPen(QColor(255, 255, 255, 90), 6, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(shine)
    painter.setPen(QPen(QColor("#f4ebe1"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(70, 290), QPointF(310, 290))  # the ground
    ink = QColor("#2b2440")
    # The evolving skull, carved into the top of the stone: a light edge below
    # the dark cut, like a chiselled groove.
    if skull:
        carving = _skull_at(deaths, QRectF(171, 55, 38, 38))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 248, 240, 110))
        painter.drawPath(carving.translated(0.9, 1.2))
        _body, tier = tier_colors(deaths, "#3a3157", "#3a3157")
        painter.setBrush(tier)  # the stone's dark ink, or its tier's colour past 100
        painter.drawPath(carving)
    painter.setPen(ink)
    rip = _font(_SANS, 15, 800)
    rip.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4)
    painter.setFont(rip)
    painter.drawText(QRectF(98, 92, 184, 22), Qt.AlignmentFlag.AlignCenter, "R.I.P.")
    if word:
        painter.setFont(_fit_font(_SANS, word, 21, 160, 700))
        painter.drawText(QRectF(98, 118, 184, 30), Qt.AlignmentFlag.AlignCenter, word)
    painter.setFont(_fit_font(_SANS, number, 60, 140, 900))
    painter.drawText(QRectF(98, 150, 184, 80), Qt.AlignmentFlag.AlignCenter, number)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    crack = QPainterPath()
    crack.moveTo(270, 222)
    crack.lineTo(262, 238)
    crack.lineTo(271, 250)
    crack.lineTo(264, 268)
    painter.setPen(QPen(QColor(43, 36, 64, 160), 2.4, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPath(crack)
    _pumpkin(painter, 112, 248)
    _ghost(painter, 306, 8)


# ---------------------------------------------------------------- Death Banner
def _scroll(x0: float, direction: int) -> QPainterPath:
    """One ornate swirl, growing out from the middle (``direction`` -1 = left)."""
    d = direction
    path = QPainterPath()
    path.moveTo(x0, 64)
    path.cubicTo(x0 + d * 40, 30, x0 + d * 90, 84, x0 + d * 140, 52)
    path.cubicTo(x0 + d * 162, 38, x0 + d * 184, 52, x0 + d * 176, 66)
    path.cubicTo(x0 + d * 170, 76, x0 + d * 158, 70, x0 + d * 162, 62)
    path.moveTo(x0 + d * 30, 56)
    path.cubicTo(x0 + d * 50, 74, x0 + d * 78, 70, x0 + d * 92, 60)
    path.addEllipse(QPointF(x0 + d * 104, 76), 4, 4)
    path.addEllipse(QPointF(x0 + d * 64, 44), 3, 3)
    return path


def _banner(painter: QPainter, word: str, deaths: int, skull: bool) -> None:
    number = str(deaths)
    white = QColor("#f7f2f2")
    pen = QPen(white, 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    shadow = QColor(0, 0, 0, 120)
    for path in (_scroll(196, -1), _scroll(244, 1)):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(shadow, 6))
        painter.drawPath(path)
        painter.setPen(pen)
        painter.drawPath(path)
    # The emblem: the evolving skull, with the title's red and blue edges
    # (without the skull, a small diamond joins the swirls).
    if skull:
        emblem = _skull_at(deaths, QRectF(186, 14, 68, 68))
    else:
        emblem = QPainterPath()
        emblem.moveTo(220, 50)
        emblem.lineTo(232, 64)
        emblem.lineTo(220, 78)
        emblem.lineTo(208, 64)
        emblem.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    for dx, color in ((-2.5, QColor(230, 30, 60, 210)), (2.5, QColor(40, 120, 255, 200))):
        painter.setBrush(color)
        painter.drawPath(emblem.translated(dx, 0))
    body, _tier = tier_colors(deaths, "#f7f2f2", "#f7f2f2")
    painter.setPen(QPen(QColor(0, 0, 0, 110), 2))
    painter.setBrush(body)
    painter.drawPath(emblem)

    def chroma(path: QPainterPath) -> None:
        """Red and blue edges, slightly apart, under white: a glitchy title."""
        painter.setPen(Qt.PenStyle.NoPen)
        for dx, color in ((-3.5, QColor(230, 30, 60, 210)), (3.5, QColor(40, 120, 255, 200))):
            painter.setBrush(color)
            painter.drawPath(path.translated(dx, 0))
        painter.setPen(QPen(QColor(0, 0, 0, 90), 2))
        painter.setBrush(white)
        painter.drawPath(path)

    if word:
        title = _fit_font(_GOTHIC, word, 64, 400, 700, italic=True)
        chroma(_text_path(title, word, 220, 142))
    digits = _fit_font(_GOTHIC, number, 76, 320, 800)
    chroma(_text_path(digits, number, 220, 222))

