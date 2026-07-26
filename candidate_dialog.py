"""Окно ручного выбора варианта текста для трека."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from core import Track
from providers import LyricsResult, build_chain, rank_key
from widgets import draw_pill, mono_font, ui_font

PREVIEW_LINES = 12

DIALOG_QSS = """
QDialog { background: #101218; }
QLabel { background: transparent; color: #e8eaf0; }
QLabel#dlgTitle { font-size: 13pt; font-weight: 600; }
QLabel#dlgSub { color: #8b93a7; font-size: 9.5pt; }
QLabel#dlgHint { color: #6d7488; font-size: 9pt; }
QListWidget {
    background: #12141b; border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px; outline: none; padding: 2px 0;
}
QPlainTextEdit {
    background: #12141b; border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px; padding: 10px; color: #aab2c5;
}
QPushButton {
    background: #181b23; color: #dfe2ec; border: 1px solid rgba(255,255,255,0.09);
    border-radius: 10px; padding: 8px 18px; font-weight: 500;
}
QPushButton:hover { background: #222736; }
QPushButton:disabled { color: #545b6c; background: #14161e; }
QPushButton#primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7c5cff, stop:1 #b44dff);
    border: none; border-radius: 11px; padding: 9px 22px; font-weight: 600; color: white;
}
QPushButton#primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8c6eff, stop:1 #c25fff);
}
QPushButton#primary:disabled { background: #2a2745; color: #726f96; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: #2b3244; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


def fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return "—"
    m, s = divmod(int(round(float(seconds))), 60)
    return f"{m}:{s:02d}"


class CandidateWorker(QThread):
    """Опрашивает все источники параллельно — окно ждёт самый медленный, не сумму."""
    done = Signal(object, str)  # список LyricsResult, текст ошибки

    def __init__(self, track: Track, parent=None):
        super().__init__(parent)
        self._track = track

    def run(self):
        providers = build_chain()
        results: list[LyricsResult] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=len(providers)) as pool:
            futures = {pool.submit(p.candidates, self._track.query): p
                       for p in providers}
            for future, provider in futures.items():
                try:
                    results.extend(future.result())
                except Exception as exc:
                    errors.append(f"{provider.name}: {exc}")
        results.sort(key=lambda r: rank_key(r, self._track.duration))
        # Ошибку показываем, только если совсем ничего не нашлось.
        self.done.emit(results, "" if results else "; ".join(errors))


class CandidateDelegate(QStyledItemDelegate):
    """Строка варианта: длительность, расхождение, альбом, пилюля synced/plain."""

    ROW_H = 56

    def __init__(self, records: list[LyricsResult], track_duration: float | None,
                 parent=None):
        super().__init__(parent)
        self.records = records
        self.track_duration = track_duration

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, self.ROW_H)

    def paint(self, p: QPainter, option, index):
        row = index.row()
        if row >= len(self.records):
            return
        rec = self.records[row]
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)

        if option.state & QStyle.State_Selected:
            p.fillRect(r, QColor(124, 92, 255, 38))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, QColor(255, 255, 255, 8))
        if row < len(self.records) - 1:
            p.setPen(QPen(QColor(255, 255, 255, 10), 1))
            p.drawLine(r.left() + 12, r.bottom(), r.right() - 12, r.bottom())

        cy = r.center().y()
        x = r.left() + 14

        dfont = mono_font(13, QFont.DemiBold)
        dfm = QFontMetrics(dfont)
        p.setFont(dfont)
        p.setPen(QColor("#e8eaf0"))
        dur_text = fmt_duration(rec.duration)
        p.drawText(x, cy - 3, dur_text)

        delta = rec.delta(self.track_duration)
        if delta is not None:
            color = "#4ade80" if abs(delta) <= 2 else (
                "#e6b45a" if abs(delta) <= 5 else "#f2777a")
            p.setFont(mono_font(11))
            p.setPen(QColor(color))
            p.drawText(x, cy + 15, f"{delta:+.0f}с" if abs(delta) >= 0.5 else "точно")

        ax = x + max(dfm.horizontalAdvance(dur_text), 52) + 18
        album = rec.album
        if album in ("null", "Unknown Album", ""):
            album = "—"
        afont = ui_font(13)
        afm = QFontMetrics(afont)
        pill_w = 118
        src_w = 74
        max_w = r.right() - pill_w - src_w - 28 - ax
        p.setFont(afont)
        p.setPen(QColor("#e8eaf0"))
        p.drawText(ax, cy - 3, afm.elidedText(album, Qt.ElideRight, max_w))

        sub = f"{rec.artist} — {rec.title}"
        sfont = ui_font(11)
        sfm = QFontMetrics(sfont)
        p.setFont(sfont)
        p.setPen(QColor("#6d7488"))
        p.drawText(ax, cy + 15, sfm.elidedText(sub, Qt.ElideRight, max_w))

        # источник — чтобы было видно, откуда вариант
        src_font = mono_font(10)
        src_fm = QFontMetrics(src_font)
        p.setFont(src_font)
        p.setPen(QColor("#8b93a7"))
        p.drawText(r.right() - pill_w - 22 - src_fm.horizontalAdvance(rec.source),
                   cy + src_fm.capHeight() / 2, rec.source)

        if rec.instrumental and not (rec.synced or rec.plain):
            color, text = "#c39ef2", "Инструментал"
        elif rec.synced:
            color, text = "#4ade80", "С таймкодами"
        else:
            color, text = "#e6b45a", "Без таймкодов"
        draw_pill(p, r.right() - pill_w - 12, cy, color, text)
        p.restore()


class CandidateDialog(QDialog):
    """Показывает варианты текста и позволяет применить выбранный."""

    def __init__(self, track: Track, parent=None):
        super().__init__(parent)
        self.track = track
        self.records: list[dict] = []
        self.chosen: dict | None = None

        self.setWindowTitle("Выбор варианта текста")
        self.setStyleSheet(DIALOG_QSS)
        self.resize(720, 560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        title = QLabel(track.title or track.path.stem)
        title.setObjectName("dlgTitle")
        lay.addWidget(title)
        sub = QLabel(f"{track.artist or '—'} · {track.path.name} · "
                     f"{fmt_duration(track.duration)}")
        sub.setObjectName("dlgSub")
        lay.addWidget(sub)

        self.status = QLabel("Загрузка вариантов…")
        self.status.setObjectName("dlgHint")
        lay.addWidget(self.status)

        self.list = QListWidget()
        self.list.setMouseTracking(True)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.currentRowChanged.connect(self.on_row_changed)
        self.list.itemDoubleClicked.connect(lambda _: self.accept_choice())
        lay.addWidget(self.list, 3)

        preview_label = QLabel("Начало текста — сверьте со своей версией:")
        preview_label.setObjectName("dlgHint")
        lay.addWidget(preview_label)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(mono_font(12))
        lay.addWidget(self.preview, 2)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply = QPushButton("Применить")
        self.btn_apply.setObjectName("primary")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.accept_choice)
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_apply)
        lay.addLayout(buttons)

        self.worker = CandidateWorker(track, self)
        self.worker.done.connect(self.on_loaded)
        self.worker.start()

    def on_loaded(self, records: list[LyricsResult], error: str):
        self.records = records
        if error:
            self.status.setText(f"Не удалось загрузить варианты: {error}")
            return
        if not records:
            self.status.setText("Вариантов не нашлось — попробуйте поправить теги трека.")
            return
        synced = sum(1 for r in records if r.synced)
        by_source: dict[str, int] = {}
        for r in records:
            by_source[r.source] = by_source.get(r.source, 0) + 1
        sources = ", ".join(f"{name} {count}" for name, count in by_source.items())
        self.status.setText(
            f"Найдено вариантов: {len(records)} ({sources}) · с таймкодами: {synced}. "
            "Двойной клик применяет выбранный.")
        self.list.setItemDelegate(CandidateDelegate(records, self.track.duration, self.list))
        for _ in records:
            self.list.addItem(QListWidgetItem())
        self.list.setCurrentRow(0)

    def on_row_changed(self, row: int):
        if row < 0 or row >= len(self.records):
            self.btn_apply.setEnabled(False)
            self.preview.setPlainText("")
            return
        rec = self.records[row]
        self.btn_apply.setEnabled(True)
        if rec.instrumental and not (rec.synced or rec.plain):
            self.preview.setPlainText("Трек отмечен как инструментальный — текста нет.")
            return
        text = (rec.synced or rec.plain).strip()
        lines = text.splitlines()[:PREVIEW_LINES]
        if len(text.splitlines()) > PREVIEW_LINES:
            lines.append("…")
        self.preview.setPlainText("\n".join(lines))

    def accept_choice(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.records):
            self.chosen = self.records[row]
            self.accept()

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.worker.wait(3000)
        super().closeEvent(event)
