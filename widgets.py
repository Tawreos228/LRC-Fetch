"""Кастомные виджеты LRC Fetch: пилюли, тумблеры, drop-зона, делегат списка."""

from __future__ import annotations

import math
import zlib
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QLinearGradient,
    QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QListWidget, QStyle, QStyledItemDelegate,
    QVBoxLayout, QWidget,
)

from core import Status

ACCENT = "#7c5cff"
TEXT = "#e8eaf0"
TEXT_DIM = "#8b93a7"
TEXT_MUTE = "#6d7488"
TEXT_FAINT = "#5d6475"

STATUS_COLORS = {
    Status.PENDING: "#8b93a7",
    Status.SEARCHING: "#6ea8fe",
    Status.SYNCED: "#4ade80",
    Status.PLAIN: "#b8d96a",
    Status.HAS_SYNCED: "#4ade80",
    Status.HAS_PLAIN: "#e6b45a",
    Status.NO_LYRICS: "#8b93a7",
    Status.ONLY_PLAIN: "#e6b45a",
    Status.NOT_FOUND: "#f2777a",
    Status.INSTRUMENTAL: "#c39ef2",
    Status.ERROR: "#f2777a",
}

PILL_TEXT = {
    Status.PENDING: "В очереди",
    Status.SEARCHING: "Поиск…",
    Status.SYNCED: "Скачан · синхронный",
    Status.PLAIN: "Скачан · без таймкодов",
    Status.HAS_SYNCED: "Есть синхронный",
    Status.HAS_PLAIN: "Есть без таймкодов",
    Status.NO_LYRICS: "Нет текста",
    Status.ONLY_PLAIN: "Только без таймкодов",
    Status.NOT_FOUND: "Не найден",
    Status.INSTRUMENTAL: "Инструментал",
    Status.ERROR: "Ошибка",
}

ROW_H = 52
COVER_SIZE = 36
COVER_RADIUS = 9
STATUS_COL_W = 220
DUR_GAP = 18
LIST_PAD_X = 14

_mono_family: str | None = None


def mono_family() -> str:
    global _mono_family
    if _mono_family is None:
        families = QFontDatabase.families()
        _mono_family = "JetBrains Mono" if "JetBrains Mono" in families else "Consolas"
    return _mono_family


def ui_font(px: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def mono_font(px: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont(mono_family())
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def rounded_pixmap(pm: QPixmap, size: int, radius: int) -> QPixmap:
    pm = pm.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    # внутренняя обводка
    p.setClipping(False)
    p.setPen(QPen(QColor(255, 255, 255, 30), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), radius, radius)
    p.end()
    return out


def cover_pixmap(data: bytes | None, seed: str) -> QPixmap:
    """Обложка 36×36; при отсутствии — градиент-заглушка по хешу артиста/названия."""
    pm = QPixmap()
    if data and pm.loadFromData(data) and not pm.isNull():
        return rounded_pixmap(pm, COVER_SIZE, COVER_RADIUS)
    hue = zlib.crc32(seed.encode("utf-8")) % 360
    base = QPixmap(COVER_SIZE, COVER_SIZE)
    base.fill(Qt.transparent)
    p = QPainter(base)
    g = QLinearGradient(0, 0, COVER_SIZE, COVER_SIZE)
    g.setColorAt(0, QColor.fromHslF(hue / 360, 0.60, 0.46))
    g.setColorAt(1, QColor.fromHslF(((hue + 70) % 360) / 360, 0.70, 0.20))
    p.fillRect(0, 0, COVER_SIZE, COVER_SIZE, g)
    p.end()
    return rounded_pixmap(base, COVER_SIZE, COVER_RADIUS)


def pill_metrics(text: str) -> int:
    fm = QFontMetrics(ui_font(12, QFont.Medium))
    return 11 * 2 + 6 + 7 + fm.horizontalAdvance(text)


def draw_pill(p: QPainter, x: float, y_center: float, color: str, text: str,
              dot_alpha: float = 1.0, count: str = "", selected: bool = False) -> float:
    """Капсула статуса: точка + текст (+ mono-счётчик). Возвращает ширину."""
    c = QColor(color)
    font = ui_font(12, QFont.Medium)
    fm = QFontMetrics(font)
    cfont = mono_font(11, QFont.DemiBold)
    cfm = QFontMetrics(cfont)
    h, dot, gap, padx = 24, 6, 7, 11
    w = padx * 2 + dot + gap + fm.horizontalAdvance(text)
    if count:
        w += 8 + cfm.horizontalAdvance(count)
    rect = QRectF(x, y_center - h / 2, w, h)

    bg = QColor(c); bg.setAlpha(0x40 if selected else 0x1C)
    border = QColor(c); border.setAlpha(0xFF if selected else 0x3A)
    p.setPen(QPen(border, 1.4 if selected else 1))
    p.setBrush(bg)
    p.drawRoundedRect(rect, h / 2, h / 2)

    dc = QColor(c); dc.setAlphaF(max(0.0, min(1.0, dot_alpha)))
    p.setPen(Qt.NoPen)
    p.setBrush(dc)
    p.drawEllipse(QPointF(rect.x() + padx + dot / 2, y_center), dot / 2, dot / 2)

    p.setPen(QPen(c))
    p.setFont(font)
    tx = rect.x() + padx + dot + gap
    p.drawText(QPointF(tx, y_center + fm.capHeight() / 2), text)
    if count:
        p.setFont(cfont)
        p.drawText(QPointF(tx + fm.horizontalAdvance(text) + 8,
                           y_center + cfm.capHeight() / 2), count)
    return w


class ChipLabel(QWidget):
    """Кликабельный чип-фильтр: пилюля статуса + счётчик. Сигнал clicked(payload)."""

    clicked = Signal(object)

    def __init__(self, color: str, text: str, count: int, payload=None, parent=None):
        super().__init__(parent)
        self._color, self._text, self._count = color, text, str(count)
        self.payload = payload
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)
        fm = QFontMetrics(ui_font(12, QFont.Medium))
        cfm = QFontMetrics(mono_font(11, QFont.DemiBold))
        w = 22 + 6 + 7 + fm.horizontalAdvance(text) + 8 + cfm.horizontalAdvance(self._count)
        self.setFixedSize(int(w) + 1, 24)

    def set_selected(self, value: bool):
        if value != self._selected:
            self._selected = value
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.payload)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        draw_pill(p, 0, self.height() / 2, self._color, self._text,
                  count=self._count, selected=self._selected)
        p.end()


class GradientLabel(QWidget):
    """Вордмарк с градиентной заливкой текста."""

    def __init__(self, text: str, px: int = 27, parent=None):
        super().__init__(parent)
        self._text = text
        self._font = QFont("Segoe UI Variable Display", weight=QFont.ExtraBold)
        if "Segoe UI Variable Display" not in QFontDatabase.families():
            self._font = QFont("Segoe UI", weight=QFont.Black)
        self._font.setPixelSize(px)
        self._font.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        fm = QFontMetrics(self._font)
        self.setFixedSize(fm.horizontalAdvance(text) + 4, fm.height())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing)
        fm = QFontMetrics(self._font)
        grad = QLinearGradient(0, 0, self.width(), self.height() * 0.35)
        grad.setColorAt(0.30, QColor("#eceef4"))
        grad.setColorAt(0.70, QColor("#a88bff"))
        grad.setColorAt(1.00, QColor("#e07bff"))
        p.setFont(self._font)
        p.setPen(QPen(grad, 0))
        p.drawText(0, fm.ascent(), self._text)
        p.end()


class Toggle(QCheckBox):
    """Переключатель-тумблер (трек 34×19, анимированный кноб)."""

    TRACK_W, TRACK_H, KNOB = 34, 19, 14

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if self.isChecked() else 0.0
        self._anim = QVariantAnimation(self, duration=130)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)

    def _on_anim(self, v):
        self._pos = float(v)
        self.update()

    def _animate(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._pos = 1.0 if checked else 0.0
        self.update()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(ui_font(13))
        return QSize(self.TRACK_W + 10 + fm.horizontalAdvance(self.text()) + 2,
                     max(self.TRACK_H + 4, fm.height() + 4))

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - self.TRACK_H) / 2
        on = QColor(ACCENT)
        off = QColor("#262b38")
        track = QColor(off)
        if self._pos > 0:
            track = QColor(
                int(off.red() + (on.red() - off.red()) * self._pos),
                int(off.green() + (on.green() - off.green()) * self._pos),
                int(off.blue() + (on.blue() - off.blue()) * self._pos),
            )
        if not self.isEnabled():
            track.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, y, self.TRACK_W, self.TRACK_H),
                          self.TRACK_H / 2, self.TRACK_H / 2)
        knob_x = 2.5 + (self.TRACK_W - self.KNOB - 5) * self._pos
        knob = QColor("white") if self._pos > 0.5 else QColor(TEXT_FAINT)
        if not self.isEnabled():
            knob.setAlpha(140)
        p.setBrush(knob)
        p.drawEllipse(QRectF(knob_x, y + (self.TRACK_H - self.KNOB) / 2,
                             self.KNOB, self.KNOB))
        color = QColor("#aab2c5" if self.isEnabled() else "#545b6c")
        p.setPen(color)
        p.setFont(ui_font(13))
        fm = QFontMetrics(ui_font(13))
        p.drawText(QPointF(self.TRACK_W + 10,
                           self.height() / 2 + fm.capHeight() / 2), self.text())
        p.end()


class IconCircle(QWidget):
    """Круг 88px с нотой для пустого состояния."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(88, 88)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, 88, 88)
        g.setColorAt(0, QColor(124, 92, 255, 64))
        g.setColorAt(1, QColor(196, 77, 255, 31))
        p.setBrush(g)
        p.setPen(QPen(QColor(140, 110, 255, 102), 1))
        p.drawEllipse(QRectF(0.5, 0.5, 87, 87))
        p.setPen(QColor("#cdb9ff"))
        f = QFont("Segoe UI Symbol")
        f.setPixelSize(34)
        p.setFont(f)
        p.drawText(QRectF(0, -2, 88, 88), Qt.AlignCenter, "♪")
        p.end()


class DropZone(QWidget):
    """Пустое состояние: dashed-рамка, свечение, приглашение перетащить музыку."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(0)
        lay.addStretch(3)
        lay.addWidget(IconCircle(), 0, Qt.AlignHCenter)
        lay.addSpacing(22)

        title = QLabel("Перетащите музыку сюда")
        title.setFont(ui_font(21, QFont.DemiBold))
        title.setStyleSheet(f"color: #eceef4; background: transparent;")
        title.setAlignment(Qt.AlignHCenter)
        lay.addWidget(title)
        lay.addSpacing(10)

        sub = QLabel(
            'Папки сканируются рекурсивно. Текст сохраняется<br>'
            f'рядом с треком в файл <span style="font-family:\'{mono_family()}\';'
            f'color:#a88bff">.lrc</span>')
        sub.setTextFormat(Qt.RichText)
        sub.setFont(ui_font(13))
        sub.setStyleSheet(f"color: {TEXT_DIM}; background: transparent;")
        sub.setAlignment(Qt.AlignHCenter)
        lay.addWidget(sub)
        lay.addSpacing(20)

        chips = QHBoxLayout()
        chips.setSpacing(7)
        chips.addStretch(1)
        for name in ("mp3", "flac", "m4a", "ogg", "opus", "+8"):
            chip = QLabel(name)
            chip.setFont(mono_font(11))
            chip.setStyleSheet(
                "color: #6d7488; background: transparent;"
                "border: 1px solid rgba(255,255,255,0.08);"
                "border-radius: 6px; padding: 3px 9px;")
            chips.addWidget(chip)
        chips.addStretch(1)
        lay.addLayout(chips)
        lay.addStretch(4)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        glow = QRadialGradient(QPointF(self.width() / 2, 0), self.width() * 0.55)
        glow.setColorAt(0, QColor(124, 92, 255, 23))
        glow.setColorAt(1, QColor(124, 92, 255, 0))
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        p.fillPath(path, glow)
        pen = QPen(QColor(140, 110, 255, 89), 1.5, Qt.DashLine)
        pen.setDashPattern([5, 4])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, 16, 16)
        p.end()


class SegmentedControl(QWidget):
    """Переключатель-сегменты (Все / Без синхронного / …). Сигнал changed(index)."""

    changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self._labels = labels
        self._index = 0
        self.setCursor(Qt.PointingHandCursor)
        self._font = ui_font(12, QFont.Medium)
        fm = QFontMetrics(self._font)
        self._seg_w = [fm.horizontalAdvance(t) + 26 for t in labels]
        self.setFixedSize(sum(self._seg_w) + 6, 30)

    def current_index(self) -> int:
        return self._index

    def set_index(self, index: int):
        """Программно выбрать сегмент (или -1 — снять выделение), без сигнала."""
        if index != self._index:
            self._index = index
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        x = 3
        for i, w in enumerate(self._seg_w):
            if x <= event.position().x() < x + w:
                if i != self._index:
                    self._index = i
                    self.update()
                self.changed.emit(i)   # клик пользователя всегда шлёт сигнал
                break
            x += w

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(QColor("#14161e"))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 9, 9)
        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        x = 3
        for i, (label, w) in enumerate(zip(self._labels, self._seg_w)):
            rect = QRectF(x, 3, w, self.height() - 6)
            if i == self._index:
                grad = QLinearGradient(rect.left(), 0, rect.right(), 0)
                grad.setColorAt(0, QColor("#7c5cff"))
                grad.setColorAt(1, QColor("#b44dff"))
                p.setPen(Qt.NoPen)
                p.setBrush(grad)
                p.drawRoundedRect(rect, 7, 7)
                p.setPen(QColor("white"))
            else:
                p.setPen(QColor(TEXT_DIM))
            p.drawText(rect, Qt.AlignCenter, label)
            x += w
        p.end()


class ColumnHeader(QWidget):
    """Заголовки колонок ТРЕК / ДЛИТ. / СТАТУС над списком."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)

    def paintEvent(self, _):
        p = QPainter(self)
        f = ui_font(11, QFont.DemiBold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.1)
        p.setFont(f)
        p.setPen(QColor(TEXT_FAINT))
        fm = QFontMetrics(f)
        base = self.height() / 2 + fm.capHeight() / 2
        status_x = self.width() - STATUS_COL_W
        p.drawText(QPointF(LIST_PAD_X, base), "ТРЕК")
        dur = "ДЛИТ."
        p.drawText(QPointF(status_x - DUR_GAP - fm.horizontalAdvance(dur), base), dur)
        p.drawText(QPointF(status_x, base), "СТАТУС")
        p.end()


class TrackDelegate(QStyledItemDelegate):
    """Рисует строку трека: обложка, название, артист · файл, длительность, пилюля."""

    def __init__(self, tracks: list, covers: list, parent=None):
        super().__init__(parent)
        self.tracks = tracks
        self.covers = covers
        self.busy = False
        self.phase = 0.0  # для пульса точки «Поиск…»

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, ROW_H)

    def paint(self, p: QPainter, option, index):
        row = index.row()
        if row >= len(self.tracks):
            return
        track = self.tracks[row]
        cover = self.covers[row] if row < len(self.covers) else None
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)

        if option.state & QStyle.State_Selected:
            p.fillRect(r, QColor(124, 92, 255, 32))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, QColor(255, 255, 255, 7))

        if row < len(self.tracks) - 1:
            p.setPen(QPen(QColor(255, 255, 255, 10), 1))
            p.drawLine(r.left() + LIST_PAD_X, r.bottom(), r.right() - LIST_PAD_X, r.bottom())

        if self.busy and track.status == Status.PENDING:
            p.setOpacity(0.45)

        cy = r.center().y() + 1
        x = r.left() + LIST_PAD_X
        if cover is not None:
            p.drawPixmap(x, cy - COVER_SIZE // 2, cover)
        tx = x + COVER_SIZE + 12

        status_x = r.right() - STATUS_COL_W

        title = track.title or track.path.stem
        tfont = ui_font(14, QFont.Medium)
        tfm = QFontMetrics(tfont)
        max_w = status_x - DUR_GAP - 64 - tx
        p.setFont(tfont)
        p.setPen(QColor(TEXT))
        p.drawText(QPointF(tx, cy - 3), tfm.elidedText(title, Qt.ElideRight, max_w))

        sfont = ui_font(12)
        sfm = QFontMetrics(sfont)
        mfont = mono_font(11)
        mfm = QFontMetrics(mfont)
        p.setPen(QColor(TEXT_MUTE))
        sx = tx
        if track.artist:
            artist = sfm.elidedText(track.artist, Qt.ElideRight, max_w // 2)
            p.setFont(sfont)
            p.drawText(QPointF(sx, cy + 15), artist + " · ")
            sx += sfm.horizontalAdvance(artist + " · ")
        p.setFont(mfont)
        fname = mfm.elidedText(track.path.name, Qt.ElideRight, max_w - (sx - tx))
        p.drawText(QPointF(sx, cy + 15), fname)

        if track.duration:
            m, s = divmod(int(track.duration), 60)
            dtext = f"{m}:{s:02d}"
            dfont = mono_font(12)
            dfm = QFontMetrics(dfont)
            p.setFont(dfont)
            p.setPen(QColor(TEXT_DIM))
            p.drawText(QPointF(status_x - DUR_GAP - dfm.horizontalAdvance(dtext),
                               cy + dfm.capHeight() / 2), dtext)

        dot_alpha = 1.0
        if track.status == Status.SEARCHING:
            dot_alpha = 0.2 + 0.8 * abs(math.sin(math.pi * self.phase))
        draw_pill(p, status_x, cy, STATUS_COLORS[track.status],
                  PILL_TEXT[track.status], dot_alpha)
        p.restore()


class TrackList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setFocusPolicy(Qt.NoFocus)
