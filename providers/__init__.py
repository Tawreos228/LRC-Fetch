"""Реестр провайдеров. Добавить источник — положить сюда модуль и строку ниже.

Опрос идёт по порядку: следующий провайдер трогаем, только если предыдущий не дал
синхронный текст. Так на лишние сервисы не уходит трафик, а по времени это почти
бесплатно — основной источник срабатывает в большинстве случаев.
"""

from __future__ import annotations

from .base import LyricsResult, Provider, Query, matches, rank_key, similarity
from .lrclib import LrclibProvider
from .netease import NeteaseProvider

__all__ = [
    "LyricsResult", "Provider", "Query", "build_chain", "matches",
    "provider_names", "rank_key", "similarity",
]

# Порядок важен: lrclib первый — он единственный публичный API, спроектированный
# под такое использование, и не отдаёт мусор на неизвестный запрос.
_REGISTRY: list[type[Provider]] = [
    LrclibProvider,
    NeteaseProvider,
]


def provider_names() -> list[str]:
    return [cls.name for cls in _REGISTRY]


def build_chain(enabled: list[str] | None = None) -> list[Provider]:
    """Создаёт провайдеры в порядке опроса. `enabled` — имена (None = все)."""
    return [cls() for cls in _REGISTRY if enabled is None or cls.name in enabled]
