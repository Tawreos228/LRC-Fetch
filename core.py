"""Ядро lrcfetch: сканирование, чтение тегов, обработка трека и запись .lrc."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import mutagen

from providers import LyricsResult, Provider, Query

AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".opus",
              ".wma", ".wav", ".aiff", ".aif", ".ape", ".wv", ".dsf"}

# "01. Artist - Title", "03 - Artist - Title", "1_Artist - Title"
_TRACKNUM_RE = re.compile(r"^\s*\d{1,3}\s*[.\-_)\s]\s*")


class Status(Enum):
    PENDING = "В очереди"
    SEARCHING = "Поиск…"
    SYNCED = "Скачан (синхронный)"
    PLAIN = "Скачан (без таймкодов)"
    HAS_SYNCED = "Есть синхронный"          # .lrc с таймкодами уже на диске
    HAS_PLAIN = "Есть без таймкодов"        # .lrc без таймкодов уже на диске
    NO_LYRICS = "Нет текста"                # .lrc отсутствует
    ONLY_PLAIN = "Есть только без таймкодов"
    NOT_FOUND = "Не найден"
    INSTRUMENTAL = "Инструментал"
    ERROR = "Ошибка"


# Категории для фильтра. Статус трека всегда попадает ровно в один из уровней.
SYNCED_STATUSES = frozenset({Status.HAS_SYNCED, Status.SYNCED})
TEXT_STATUSES = SYNCED_STATUSES | {Status.HAS_PLAIN, Status.PLAIN}

# Строка-таймкод вида [00:12.34] / [1:02:03]. Именно наличие такой строки, а не
# первого «[», отличает синхронный текст от plain-файла с метатегами [ti:]/[ar:].
_TIMECODE_RE = re.compile(r"\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]")


def has_synced_text(status: Status) -> bool:
    return status in SYNCED_STATUSES


def has_any_text(status: Status) -> bool:
    return status in TEXT_STATUSES


def is_synced_lyrics(text: str) -> bool:
    """True, если в тексте есть хотя бы одна строка с таймкодом."""
    return bool(_TIMECODE_RE.search(text))


def scan_lrc_status(lrc_path: Path) -> Status:
    """Определяет состояние текста по уже лежащему рядом .lrc."""
    if not lrc_path.exists():
        return Status.NO_LYRICS
    try:
        text = lrc_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Status.NO_LYRICS
    if not text.strip():
        return Status.NO_LYRICS
    return Status.HAS_SYNCED if is_synced_lyrics(text) else Status.HAS_PLAIN


@dataclass
class Track:
    path: Path
    artist: str = ""
    title: str = ""
    album: str = ""
    duration: float | None = None
    status: Status = Status.PENDING
    message: str = ""
    source: str = ""   # провайдер, давший текст

    @property
    def lrc_path(self) -> Path:
        return self.path.with_suffix(".lrc")

    @property
    def query(self) -> Query:
        return Query(self.artist, self.title, self.album, self.duration)


@dataclass
class Options:
    allow_plain: bool = True   # сохранять plain-текст, если нет синхронного
    overwrite: bool = False    # перезаписывать существующие .lrc


def collect_audio_files(paths: list[Path]) -> list[Path]:
    """Файлы и папки (рекурсивно) -> отсортированный список аудиофайлов без дублей."""
    found: set[Path] = set()
    for p in paths:
        if p.is_dir():
            for child in p.rglob("*"):
                if child.is_file() and child.suffix.lower() in AUDIO_EXTS:
                    found.add(child)
        elif p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            found.add(p)
    return sorted(found, key=lambda x: str(x).lower())


def parse_filename(stem: str) -> tuple[str, str]:
    """Имя файла -> (артист, название). Формат 'Артист - Название' с номером трека."""
    cleaned = _TRACKNUM_RE.sub("", stem).strip()
    if " - " in cleaned:
        artist, title = cleaned.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", cleaned


def read_track(path: Path) -> Track:
    """Читает теги и длительность; при пустых тегах берёт данные из имени файла."""
    track = Track(path=path)
    try:
        audio = mutagen.File(path, easy=True)
    except Exception:
        audio = None
    if audio is not None:
        tags = audio.tags or {}

        def first(key: str) -> str:
            values = tags.get(key) or []
            return str(values[0]).strip() if values else ""

        track.artist = first("artist")
        track.title = first("title")
        track.album = first("album")
        if audio.info is not None and getattr(audio.info, "length", 0):
            track.duration = float(audio.info.length)
    if not track.title:
        fn_artist, fn_title = parse_filename(path.stem)
        track.title = fn_title
        if not track.artist:
            track.artist = fn_artist
    # Сразу показываем, есть ли уже текст и какой именно.
    track.status = scan_lrc_status(track.lrc_path)
    return track


def process_track(track: Track, providers: list[Provider], options: Options) -> Track:
    """Опрашивает провайдеров по порядку и пишет .lrc. Обновляет статус трека.

    Без флага overwrite синхронный .lrc не трогаем вообще (даже сеть не дёргаем),
    а plain-файл разрешаем «догнать» до синхронного, если он найдётся онлайн.
    """
    existing = scan_lrc_status(track.lrc_path) if track.lrc_path.exists() else Status.NO_LYRICS
    if not options.overwrite:
        if existing == Status.HAS_SYNCED:
            track.status = Status.HAS_SYNCED
            return track
        # existing == HAS_PLAIN: ищем, но запишем только если найдётся синхронный.
    upgrade_only = (not options.overwrite) and existing == Status.HAS_PLAIN

    best: LyricsResult | None = None   # лучшее из непригодного: plain/инструментал
    errors: list[str] = []
    for provider in providers:
        try:
            result = provider.find(track.query)
        except Exception as exc:
            errors.append(f"{provider.name}: {exc}")
            continue
        if result is None:
            continue
        if result.synced:
            best = result
            break
        if best is None or (result.plain and not best.plain):
            best = result

    # Нашёлся синхронный — пишем всегда (в т.ч. апгрейд plain-файла).
    if best is not None and best.synced:
        track.source = best.source
        _write_lrc(track.lrc_path, best.synced)
        track.status = Status.SYNCED
        return track

    # Синхронного нет. Для plain-файла без overwrite сохраняем то, что уже есть.
    if upgrade_only:
        track.status = Status.HAS_PLAIN
        return track

    if best is None:
        # Ошибку показываем, только если ни один источник ничего не дал.
        track.status = Status.ERROR if errors else Status.NOT_FOUND
        track.message = "\n".join(errors)
        return track

    track.source = best.source
    if best.instrumental:
        track.status = Status.INSTRUMENTAL
    elif best.plain and options.allow_plain:
        _write_lrc(track.lrc_path, best.plain)
        track.status = Status.PLAIN
    elif best.plain:
        track.status = Status.ONLY_PLAIN
    else:
        track.status = Status.NOT_FOUND
    return track


def apply_record(track: Track, result: LyricsResult, options: Options) -> Track:
    """Записывает выбранный вручную вариант, игнорируя existing/overwrite."""
    track.message = ""
    track.source = result.source
    if result.instrumental and not (result.synced or result.plain):
        track.status = Status.INSTRUMENTAL
        return track

    if result.synced:
        _write_lrc(track.lrc_path, result.synced)
        track.status = Status.SYNCED
    elif result.plain:
        # Ручной выбор — прямое указание пользователя, настройка allow_plain
        # здесь не действует: он видел, что у варианта нет таймкодов.
        _write_lrc(track.lrc_path, result.plain)
        track.status = Status.PLAIN
    else:
        track.status = Status.NOT_FOUND
    return track


def _write_lrc(path: Path, text: str) -> None:
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
