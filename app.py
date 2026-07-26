"""lrcfetch — загрузчик текстов песен (.lrc) с lrclib.net.

Запуск: python app.py  (или pythonw app.py — без консоли)
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QMainWindow, QMenu, QProgressBar, QPushButton, QListWidgetItem,
    QStackedWidget, QVBoxLayout, QWidget,
)

from candidate_dialog import CandidateDialog
from core import (
    Options, Status, Track, apply_record, collect_audio_files, has_any_text,
    has_synced_text, process_track, read_track,
)
from providers import build_chain
from widgets import (
    ChipLabel, ColumnHeader, DropZone, GradientLabel, PILL_TEXT, STATUS_COLORS,
    SegmentedControl, Toggle, TrackDelegate, TrackList, cover_pixmap, mono_family,
    mono_font, ui_font,
)

APP_NAME = "LRC Fetch"
# Треки обрабатываются параллельно. Больше 8 — уже неуважение к бесплатным
# публичным API, а выигрыш упирается в их же скорость ответа.
MAX_WORKERS = 8

QSS = f"""
* {{ font-family: 'Segoe UI', sans-serif; font-size: 10.5pt; color: #e8eaf0; }}
QMainWindow {{ background: #0c0e13; }}
QWidget#content {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #101218, stop:1 #0b0d12);
}}
QLabel {{ background: transparent; }}
QLabel#appSubtitle {{ color: #8b93a7; font-size: 10pt; }}
QPushButton {{
    background: #181b23; color: #dfe2ec; border: 1px solid rgba(255,255,255,0.09);
    border-radius: 10px; padding: 8px 18px; font-weight: 500;
}}
QPushButton:hover {{ background: #222736; }}
QPushButton:pressed {{ background: #161a24; }}
QPushButton:disabled {{ color: #545b6c; background: #14161e;
    border-color: rgba(255,255,255,0.05); }}
QPushButton#iconbtn {{ padding: 4px 12px; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7c5cff, stop:1 #b44dff);
    border: none; border-radius: 11px; padding: 10px 26px;
    font-weight: 600; color: white;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8c6eff, stop:1 #c25fff);
}}
QPushButton#primary:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6a4de6, stop:1 #9c3fe0);
}}
QPushButton#primary:disabled {{ background: #2a2745; color: #726f96; }}
QPushButton#stop {{ color: #f2777a; }}
QListWidget {{
    background: #12141b;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 14px;
    outline: none;
    padding: 2px 0;
}}
QProgressBar {{
    background: #1b1e28; border: none; border-radius: 3px;
    min-height: 6px; max-height: 6px; color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c5cff, stop:1 #c44dff);
    border-radius: 3px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: #2b3244; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4358; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenu {{ background: #1b1f2a; border: 1px solid #2b3244; border-radius: 10px; padding: 5px; }}
QMenu::item {{ padding: 7px 20px; border-radius: 6px; }}
QMenu::item:selected {{ background: rgba(124, 92, 255, 0.22); }}
QMenu::item:disabled {{ color: #545b6c; }}
QToolTip {{ background: #1b1f2a; color: #e8eaf0; border: 1px solid #2b3244; padding: 5px 8px; }}
"""


def read_cover_bytes(path: Path) -> bytes | None:
    """Достаёт встроенную обложку из тегов (mp3/flac/m4a/ogg/opus)."""
    try:
        from mutagen import File as MFile
        f = MFile(str(path))
        if f is None:
            return None
        tags = getattr(f, "tags", None)
        if tags is not None and hasattr(tags, "getall"):          # ID3
            pics = tags.getall("APIC")
            if pics:
                return bytes(pics[0].data)
        if getattr(f, "pictures", None):                          # FLAC
            return bytes(f.pictures[0].data)
        if tags is not None and "covr" in tags:                   # MP4/M4A
            return bytes(tags["covr"][0])
        if tags is not None and "metadata_block_picture" in tags:  # ogg/opus
            from mutagen.flac import Picture
            return bytes(Picture(base64.b64decode(tags["metadata_block_picture"][0])).data)
    except Exception:
        pass
    return None


def format_eta(seconds: float) -> str:
    """Человеческая оценка оставшегося времени."""
    if seconds < 10:
        return "почти готово"
    if seconds < 60:
        return f"~{int(round(seconds / 5)) * 5} с"
    minutes = seconds / 60
    if minutes < 60:
        return f"~{int(round(minutes))} мин"
    hours, mins = divmod(int(round(minutes)), 60)
    return f"~{hours} ч {mins} мин" if mins else f"~{hours} ч"


def plural_texts(n: int) -> str:
    if n % 100 in (11, 12, 13, 14):
        return "текстов"
    if n % 10 == 1:
        return "текст"
    if n % 10 in (2, 3, 4):
        return "текста"
    return "текстов"


class ScanWorker(QThread):
    track_ready = Signal(object, object)  # Track, cover bytes | None
    finished_scan = Signal(int)

    def __init__(self, paths: list[Path], parent=None):
        super().__init__(parent)
        self._paths = paths

    def run(self):
        files = collect_audio_files(self._paths)
        for f in files:
            self.track_ready.emit(read_track(f), read_cover_bytes(f))
        self.finished_scan.emit(len(files))


class FetchWorker(QThread):
    item_started = Signal(int)
    item_done = Signal(int, object)
    all_done = Signal()

    def __init__(self, targets: list[tuple[int, Track]], options: Options, parent=None):
        # targets — пары (номер строки в списке, трек). Обрабатываются только они,
        # поэтому фильтр «без синхронного» реально сужает набор для скачивания.
        super().__init__(parent)
        self._targets = targets
        self._options = options
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        # Свой набор провайдеров на поток: requests.Session не потокобезопасна.
        local = threading.local()

        def providers():
            if not hasattr(local, "chain"):
                local.chain = build_chain()
            return local.chain

        def worker(row: int, track: Track):
            if self._stop.is_set():
                return
            # статус меняется здесь же, в рабочем потоке: сигнал item_started
            # обрабатывается GUI позже и мог бы затереть финальный статус
            track.status = Status.SEARCHING
            self.item_started.emit(row)
            process_track(track, providers(), self._options)
            self.item_done.emit(row, track)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(worker, row, t) for row, t in self._targets]
            for f in futures:
                f.result()
        self.all_done.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1010, 660)
        self.setMinimumSize(880, 560)
        self.setAcceptDrops(True)

        self.settings = QSettings("lrcfetch", "lrcfetch")
        self.tracks: list[Track] = []
        self.covers: list = []
        self.scan_worker: ScanWorker | None = None
        self.fetch_worker: FetchWorker | None = None
        self.done_count = 0
        self._fetch_total = 0
        self._last_paths: list[Path] = []
        # Фильтр списка: ("mode", 0|1|2) от сегментов или ("status", Status) от чипа.
        self._filter: tuple = ("mode", 0)
        self._chip_widgets: dict = {}

        content = QWidget()
        content.setObjectName("content")
        content.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(content)
        root.setContentsMargins(24, 18, 24, 16)
        root.setSpacing(12)

        # --- шапка ---
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        title_box.addWidget(GradientLabel("LRC FETCH"))
        self.subtitle = QLabel()
        self.subtitle.setObjectName("appSubtitle")
        self.subtitle.setTextFormat(Qt.RichText)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        self.btn_rescan = QPushButton("⟳")
        self.btn_rescan.setObjectName("iconbtn")
        self.btn_rescan.setToolTip("Просканировать те же папки заново")
        self.btn_rescan.setFont(ui_font(17))
        self.btn_rescan.setEnabled(False)
        self.btn_rescan.clicked.connect(self.rescan)
        self.btn_folder = QPushButton("Папка…")
        self.btn_files = QPushButton("Файлы…")
        self.btn_folder.clicked.connect(self.choose_folder)
        self.btn_files.clicked.connect(self.choose_files)
        header.addWidget(self.btn_rescan, 0, Qt.AlignTop)
        header.addWidget(self.btn_folder, 0, Qt.AlignTop)
        header.addWidget(self.btn_files, 0, Qt.AlignTop)
        root.addLayout(header)

        # --- чипы-сводка ---
        self.chips_row = QWidget()
        self.chips_layout = QHBoxLayout(self.chips_row)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(8)
        self.chips_row.hide()
        root.addWidget(self.chips_row)

        # --- стек: drop-зона / список ---
        self.stack = QStackedWidget()
        self.dropzone = DropZone()
        self.dropzone.clicked.connect(self.choose_folder)
        self.stack.addWidget(self.dropzone)

        list_page = QWidget()
        list_lay = QVBoxLayout(list_page)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(2)

        # --- строка фильтра над списком ---
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(2, 0, 2, 4)
        self.count_label = QLabel()
        self.count_label.setFont(ui_font(12))
        self.count_label.setStyleSheet("color: #8b93a7;")
        filter_row.addWidget(self.count_label)
        filter_row.addStretch(1)
        self.filter = SegmentedControl(["Все", "Без синхронного", "Совсем без текста"])
        self.filter.changed.connect(self.on_segment_changed)
        filter_row.addWidget(self.filter)
        list_lay.addLayout(filter_row)

        self.col_header = ColumnHeader()
        list_lay.addWidget(self.col_header)
        self.list = TrackList()
        self.delegate = TrackDelegate(self.tracks, self.covers, self.list)
        self.list.setItemDelegate(self.delegate)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.show_context_menu)
        list_lay.addWidget(self.list, 1)
        self.stack.addWidget(list_page)
        root.addWidget(self.stack, 1)

        # --- прогресс ---
        self.progress_row = QWidget()
        pr = QHBoxLayout(self.progress_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(14)
        self.progress = QProgressBar()
        pr.addWidget(self.progress, 1)
        self.eta_label = QLabel()
        self.eta_label.setFont(ui_font(12))
        self.eta_label.setStyleSheet("color: #6d7488;")
        pr.addWidget(self.eta_label)
        self.progress_label = QLabel()
        self.progress_label.setFont(mono_font(12))
        self.progress_label.setStyleSheet("color: #8b93a7;")
        pr.addWidget(self.progress_label)
        self.progress_row.hide()
        root.addWidget(self.progress_row)

        # --- футер ---
        footer = QHBoxLayout()
        footer.setSpacing(22)
        self.chk_plain = Toggle("Без таймкодов, если нет синхронного")
        self.chk_plain.setChecked(self.settings.value("allow_plain", True, bool))
        self.chk_overwrite = Toggle("Перезаписывать .lrc")
        self.chk_overwrite.setChecked(self.settings.value("overwrite", False, bool))
        footer.addWidget(self.chk_plain)
        footer.addWidget(self.chk_overwrite)
        footer.addStretch(1)
        self.btn_stop = QPushButton("Стоп")
        self.btn_stop.setObjectName("stop")
        self.btn_stop.hide()
        self.btn_stop.clicked.connect(self.stop_fetch)
        self.btn_go = QPushButton("⇣  Скачать тексты")
        self.btn_go.setObjectName("primary")
        self.btn_go.setEnabled(False)
        self.btn_go.clicked.connect(self.start_fetch)
        self._glow = QGraphicsDropShadowEffect(self.btn_go)
        self._glow.setColor(QColor(124, 92, 255, 90))
        self._glow.setBlurRadius(26)
        self._glow.setOffset(0, 8)
        self.btn_go.setGraphicsEffect(self._glow)
        self._glow.setEnabled(False)
        footer.addWidget(self.btn_stop)
        footer.addWidget(self.btn_go)
        root.addLayout(footer)

        self.setCentralWidget(content)

        self.pulse_timer = QTimer(self)
        self.pulse_timer.setInterval(90)
        self.pulse_timer.timeout.connect(self._pulse)

        # Отдельный таймер: при затыке на медленном источнике оценка должна
        # расти, а не застывать на цифре, посчитанной до затыка.
        self.eta_timer = QTimer(self)
        self.eta_timer.setInterval(1000)
        self.eta_timer.timeout.connect(self._update_eta)
        self._fetch_started = 0.0

        self.set_subtitle_idle()

    def _pulse(self):
        self.delegate.phase = (self.delegate.phase + 0.082) % 1.0
        self.list.viewport().update()

    def _update_eta(self):
        """Оценка по фактической средней скорости с начала прогона."""
        total = self._fetch_total
        if not self._fetch_started or self.done_count >= total:
            self.eta_label.setText("")
            return
        elapsed = time.monotonic() - self._fetch_started
        if self.done_count < 1 or elapsed < 2:
            self.eta_label.setText("оцениваю…")
            return
        per_track = elapsed / self.done_count
        text = format_eta(per_track * (total - self.done_count))
        # «почти готово» — самодостаточная фраза, приставка «осталось» её ломает
        self.eta_label.setText(text if text.startswith("почти") else f"осталось {text}")

    # ---------- подзаголовок ----------
    def set_subtitle_idle(self):
        self.subtitle.setText(
            'Синхронные тексты песен · '
            '<span style="color:#8b7cff">lrclib.net</span>')

    def _set_go_enabled(self, enabled: bool):
        self.btn_go.setEnabled(enabled)
        self._glow.setEnabled(enabled)

    # ---------- выбор файлов ----------
    def choose_folder(self):
        start = self.settings.value("last_dir", str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с музыкой", start)
        if folder:
            self.settings.setValue("last_dir", folder)
            self.load_paths([Path(folder)])

    def choose_files(self):
        start = self.settings.value("last_dir", str(Path.home()))
        exts = ("Аудиофайлы (*.mp3 *.flac *.m4a *.mp4 *.aac *.ogg *.opus "
                "*.wma *.wav *.aiff *.ape *.wv *.dsf)")
        files, _ = QFileDialog.getOpenFileNames(self, "Выберите аудиофайлы", start, exts)
        if files:
            self.settings.setValue("last_dir", str(Path(files[0]).parent))
            self.load_paths([Path(f) for f in files])

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.load_paths(paths)

    def load_paths(self, paths: list[Path]):
        if self.fetch_worker and self.fetch_worker.isRunning():
            return
        if self.scan_worker and self.scan_worker.isRunning():
            return
        self._last_paths = list(paths)
        self.tracks.clear()
        self.covers.clear()
        self.list.clear()
        self.chips_row.hide()
        self.progress_row.hide()
        self.count_label.clear()
        self.btn_rescan.setEnabled(False)   # идёт сканирование
        self._set_go_enabled(False)
        self.stack.setCurrentIndex(1)
        self.subtitle.setText("Сканирование…")
        self.scan_worker = ScanWorker(paths)
        self.scan_worker.track_ready.connect(self.add_track)
        self.scan_worker.finished_scan.connect(self.scan_finished)
        self.scan_worker.start()

    def rescan(self):
        """Повторно сканирует те же папки/файлы без перевыбора."""
        if self._last_paths:
            self.load_paths(self._last_paths)

    def add_track(self, track: Track, cover: bytes | None):
        self.tracks.append(track)
        self.covers.append(cover_pixmap(
            cover, f"{track.artist}|{track.title}|{track.path.name}"))
        item = QListWidgetItem()
        item.setToolTip(str(track.path))
        self.list.addItem(item)

    def scan_finished(self, total: int):
        self.btn_rescan.setEnabled(bool(self._last_paths))
        if total == 0:
            self.stack.setCurrentIndex(0)
            self.subtitle.setText("Аудиофайлы не найдены — попробуйте другую папку")
            return
        self.subtitle.setText(f"Найдено файлов: {total} · нажмите «Скачать тексты»")
        self._set_go_enabled(True)
        self._rebuild_chips()
        self.apply_filter()

    # ---------- скачивание ----------
    def start_fetch(self):
        if not self.tracks:
            return
        # Скачиваем только показанные фильтром треки (при «Все» — весь список).
        targets = [(row, track) for row, track in enumerate(self.tracks)
                   if not self.list.item(row).isHidden()]
        if not targets:
            self.subtitle.setText("Фильтр скрыл все треки — скачивать нечего")
            return

        options = Options(allow_plain=self.chk_plain.isChecked(),
                          overwrite=self.chk_overwrite.isChecked())
        self.settings.setValue("allow_plain", options.allow_plain)
        self.settings.setValue("overwrite", options.overwrite)

        for _, track in targets:
            track.status = Status.PENDING
            track.message = ""
        self.list.viewport().update()

        self.done_count = 0
        self._fetch_total = len(targets)
        self._fetch_started = time.monotonic()
        self.progress.setMaximum(self._fetch_total)
        self.progress.setValue(0)
        self.progress_label.setText(f"0 / {self._fetch_total}")
        self.eta_label.setText("оцениваю…")
        self.eta_timer.start()
        self.progress_row.show()
        self.chips_row.hide()
        self.set_busy(True)
        self._update_fetch_subtitle()

        self.fetch_worker = FetchWorker(targets, options)
        self.fetch_worker.item_started.connect(self.on_item_started)
        self.fetch_worker.item_done.connect(self.on_item_done)
        self.fetch_worker.all_done.connect(self.on_all_done)
        self.fetch_worker.start()

    def stop_fetch(self):
        if self.fetch_worker:
            self.fetch_worker.stop()
            self.btn_stop.setEnabled(False)

    def set_busy(self, busy: bool):
        for w in (self.btn_folder, self.btn_files,
                  self.chk_plain, self.chk_overwrite):
            w.setEnabled(not busy)
        self.btn_rescan.setEnabled(not busy and bool(self._last_paths))
        self._set_go_enabled(not busy and bool(self.tracks))
        self.btn_stop.setVisible(busy)
        self.btn_stop.setEnabled(busy)
        self.delegate.busy = busy
        if busy:
            self.pulse_timer.start()
        else:
            self.pulse_timer.stop()
        self.list.viewport().update()

    def _update_fetch_subtitle(self):
        self.subtitle.setText(
            f"Скачивание текстов · {self.done_count} из {self._fetch_total}")

    def on_item_started(self, row: int):
        self.list.viewport().update()

    def on_item_done(self, row: int, track: Track):
        self.done_count += 1
        self.progress.setValue(self.done_count)
        self.progress_label.setText(f"{self.done_count} / {self._fetch_total}")
        self._update_eta()
        self._update_fetch_subtitle()
        item = self.list.item(row)
        if item and track.message:
            item.setToolTip(f"{track.path}\n{track.message}")
        self.list.viewport().update()

    def on_all_done(self):
        self.set_busy(False)
        self.eta_timer.stop()
        self._fetch_started = 0.0
        self.eta_label.setText("")
        self.progress_row.hide()
        self.refresh_summary()
        self.apply_filter()

    # Порядок статусов в чипах-сводке.
    _CHIP_ORDER = (Status.SYNCED, Status.HAS_SYNCED, Status.PLAIN, Status.HAS_PLAIN,
                   Status.NO_LYRICS, Status.ONLY_PLAIN, Status.NOT_FOUND,
                   Status.INSTRUMENTAL, Status.ERROR, Status.PENDING)

    def _rebuild_chips(self):
        counts: dict[Status, int] = {}
        for t in self.tracks:
            counts[t.status] = counts.get(t.status, 0) + 1
        while self.chips_layout.count():
            w = self.chips_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._chip_widgets = {}
        for status in self._CHIP_ORDER:
            if counts.get(status):
                chip = ChipLabel(STATUS_COLORS[status], PILL_TEXT[status],
                                 counts[status], payload=status)
                chip.clicked.connect(self.on_chip_clicked)
                self.chips_layout.addWidget(chip)
                self._chip_widgets[status] = chip
        self.chips_layout.addStretch(1)
        self.chips_row.show()
        # Фильтр по статусу, которого больше нет, сбрасываем на «Все».
        if self._filter[0] == "status" and self._filter[1] not in self._chip_widgets:
            self._filter = ("mode", 0)
            self.filter.set_index(0)
        self._update_chip_selection()

    def _update_chip_selection(self):
        active = self._filter[1] if self._filter[0] == "status" else None
        for status, chip in self._chip_widgets.items():
            chip.set_selected(status == active)

    def on_segment_changed(self, index: int):
        self._filter = ("mode", index)
        self.apply_filter()

    def on_chip_clicked(self, status):
        """Клик по чипу фильтрует по этому статусу; повторный клик — снова «Все»."""
        if self._filter == ("status", status):
            self._filter = ("mode", 0)
            self.filter.set_index(0)
        else:
            self._filter = ("status", status)
            self.filter.set_index(-1)   # ни один сегмент не активен
        self.apply_filter()

    def _is_visible(self, track: Track) -> bool:
        kind, val = self._filter
        if kind == "status":
            return track.status == val
        if val == 1:
            return not has_synced_text(track.status)
        if val == 2:
            return not has_any_text(track.status)
        return True

    def refresh_summary(self):
        """Пересобирает чипы и подзаголовок по текущим статусам треков."""
        self._rebuild_chips()
        saved = sum(1 for t in self.tracks if t.status in (Status.SYNCED, Status.PLAIN))
        self.subtitle.setText(
            f"Готово · сохранено {saved} {plural_texts(saved)} из {len(self.tracks)}")

    def apply_filter(self):
        """Прячет строки по текущему фильтру и обновляет счётчик «показано»."""
        shown = 0
        for row, track in enumerate(self.tracks):
            visible = self._is_visible(track)
            item = self.list.item(row)
            if item:
                item.setHidden(not visible)
            shown += visible
        self._update_chip_selection()
        total = len(self.tracks)
        self.count_label.setText(
            f"Показано: {shown}" if shown == total else f"Показано: {shown} из {total}")

    # ---------- контекстное меню ----------
    def show_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        row = self.list.row(item)
        if row < 0 or row >= len(self.tracks):
            return
        menu = self.build_context_menu(row)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def build_context_menu(self, row: int) -> QMenu:
        """Собирает меню строки. Отдельно от показа — чтобы поддавалось тестам."""
        track = self.tracks[row]
        busy = bool(self.fetch_worker and self.fetch_worker.isRunning())
        menu = QMenu(self)

        act_choose = QAction("Выбрать вариант…", self)
        act_choose.setEnabled(not busy and bool(track.title))
        act_choose.triggered.connect(lambda: self.choose_variant(row))
        menu.addAction(act_choose)
        menu.addSeparator()

        act_open_lrc = QAction("Открыть .lrc", self)
        act_open_lrc.setEnabled(track.lrc_path.exists())
        act_open_lrc.triggered.connect(lambda: os.startfile(track.lrc_path))
        act_show = QAction("Показать в проводнике", self)
        act_show.triggered.connect(
            lambda: subprocess.Popen(["explorer", "/select,", str(track.path)]))
        menu.addAction(act_open_lrc)
        menu.addAction(act_show)
        return menu

    def choose_variant(self, row: int):
        """Ручной выбор варианта: применяется поверх любого текущего статуса."""
        track = self.tracks[row]
        dialog = CandidateDialog(track, self)
        if dialog.exec() == CandidateDialog.Accepted and dialog.chosen:
            options = Options(allow_plain=self.chk_plain.isChecked(),
                              overwrite=self.chk_overwrite.isChecked())
            try:
                apply_record(track, dialog.chosen, options)
            except OSError as exc:
                track.status = Status.ERROR
                track.message = str(exc)
            item = self.list.item(row)
            if item:
                item.setToolTip(f"{track.path}\n{track.message}"
                                if track.message else str(track.path))
            self.list.viewport().update()
            self.refresh_summary()
            self.apply_filter()

    def closeEvent(self, event):
        if self.fetch_worker and self.fetch_worker.isRunning():
            self.fetch_worker.stop()
            self.fetch_worker.wait(3000)
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.wait(3000)
        super().closeEvent(event)


def _enable_dark_titlebar(win) -> None:
    """Тёмный заголовок окна на Windows (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = int(win.winId())
        value = ctypes.c_int(1)
        # атрибут 20 (Windows 10 2004+); на более старых сборках — 19
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd), ctypes.c_int(attr),
                    ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


def main():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("lrcfetch.app")
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    app.setApplicationName(APP_NAME)
    ico = Path(__file__).with_name("lrcfetch.ico")
    if ico.exists():
        app.setWindowIcon(QIcon(str(ico)))
    win = MainWindow()
    win.show()
    _enable_dark_titlebar(win)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
