"""Общий контракт провайдеров текстов и проверка совпадения."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

# Допустимое расхождение длительности, сек.
DURATION_TOLERANCE = 5.0

# Порог схожести, когда длительность известна и совпала.
TITLE_MIN = 0.72
ARTIST_MIN = 0.55
# Порог, когда длительности нет — полагаться остаётся только на названия.
TITLE_MIN_NO_DURATION = 0.90
ARTIST_MIN_NO_DURATION = 0.80

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Query:
    artist: str
    title: str
    album: str = ""
    duration: float | None = None


@dataclass
class LyricsResult:
    """Найденный текст. `source` — отображаемое имя провайдера."""
    source: str
    title: str
    artist: str
    album: str = ""
    duration: float | None = None
    synced: str = ""
    plain: str = ""
    instrumental: bool = False
    remote_id: str = ""

    @property
    def has_text(self) -> bool:
        return bool(self.synced or self.plain or self.instrumental)

    def delta(self, duration: float | None) -> float | None:
        if duration is None or self.duration is None:
            return None
        return float(self.duration) - duration


class Provider:
    """Источник текстов. Порядок в реестре = порядок опроса."""

    name = "provider"

    def find(self, query: Query) -> LyricsResult | None:
        """Лучший вариант или None."""
        raise NotImplementedError

    def candidates(self, query: Query) -> list[LyricsResult]:
        """Все варианты для ручного выбора."""
        raise NotImplementedError


def normalize_for_match(text: str) -> str:
    return _SPACE_RE.sub(" ", _PUNCT_RE.sub(" ", text.casefold())).strip()


def similarity(a: str, b: str) -> float:
    na, nb = normalize_for_match(a), normalize_for_match(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.95
    return SequenceMatcher(None, na, nb).ratio()


def duration_ok(result_duration: float | None, wanted: float | None) -> bool:
    if wanted is None or result_duration is None:
        return True
    return abs(float(result_duration) - wanted) <= DURATION_TOLERANCE


def matches(result: LyricsResult, query: Query) -> bool:
    """Строгая проверка «это точно тот трек».

    Нужна для источников, которые на любой запрос возвращают хоть что-нибудь:
    без неё в .lrc молча уедет текст постороннего трека.
    """
    if not duration_ok(result.duration, query.duration):
        return False
    exact_duration = query.duration is not None and result.duration is not None
    title_min = TITLE_MIN if exact_duration else TITLE_MIN_NO_DURATION
    artist_min = ARTIST_MIN if exact_duration else ARTIST_MIN_NO_DURATION

    if similarity(result.title, query.title) < title_min:
        return False
    if query.artist:
        # У сборных треков артисты перечислены иначе — сверяем и по частям.
        best = similarity(result.artist, query.artist)
        for part in re.split(r"[,;/&]|\bfeat\.?\b|\bft\.?\b", result.artist):
            part = part.strip()
            if part:
                best = max(best, similarity(part, query.artist))
        if best < artist_min:
            return False
    return True


def rank_key(result: LyricsResult, duration: float | None):
    """Сортировка вариантов: сначала synced, затем по близости длительности."""
    delta = result.delta(duration)
    return (not result.synced, abs(delta) if delta is not None else float("inf"))
