"""Нормализация артиста и названия перед поиском текста.

Ключевое различие: мусор оформления («Official Video», «Remastered 2011»)
вычищается, а маркеры версии записи («Live», «Acoustic», «Remix») остаются —
у такой версии свой текст и свой тайминг, и подменять её обычной нельзя.
"""

from __future__ import annotations

import re

# Скобочные куски, которые не меняют саму запись.
_COSMETIC_WORDS = r"""
    official(?:\s+(?:music\s+)?(?:video|audio|visualizer|lyric\s+video))?
  | lyrics?(?:\s+video)?
  | visuali[sz]er
  | audio
  | video
  | hd | hq | 4k
  | explicit | clean
  | remaster(?:ed)? | \d{4}\s+remaster(?:ed)?
  | remaster(?:ed)?\s+\d{4}
  | radio\s+edit
  | album\s+version | single\s+version | original\s+version
  | bonus\s+track
  | официальн\w*(?:\s+\w+)? | клип | премьера
"""

# «(Official Video)», «[Remastered 2011]»
_BRACKET_RE = re.compile(
    rf"[\(\[]\s*(?:{_COSMETIC_WORDS})\s*[\)\]]",
    re.IGNORECASE | re.VERBOSE,
)

# Хвост через дефис: «Bohemian Rhapsody - Remastered 2011»
_DASH_TAIL_RE = re.compile(
    rf"\s+[-–—]\s+(?:{_COSMETIC_WORDS})\s*$",
    re.IGNORECASE | re.VERBOSE,
)

# «(feat. X)», «ft. X» до конца строки
_FEAT_BRACKET_RE = re.compile(
    r"[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_FEAT_TAIL_RE = re.compile(
    r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$",
    re.IGNORECASE,
)

_TOPIC_RE = re.compile(r"\s*-\s*Topic\s*$", re.IGNORECASE)
_SPACES_RE = re.compile(r"\s{2,}")


def _tidy(text: str) -> str:
    return _SPACES_RE.sub(" ", text).strip(" -–—\t")


def clean_title(title: str) -> str:
    """Убирает из названия мусор оформления и приглашённых артистов."""
    out = title
    for _ in range(3):  # несколько скобочных блоков подряд
        before = out
        out = _BRACKET_RE.sub(" ", out)
        out = _DASH_TAIL_RE.sub("", out)
        out = _FEAT_BRACKET_RE.sub(" ", out)
        if out == before:
            break
    out = _FEAT_TAIL_RE.sub("", out)
    return _tidy(out) or title.strip()


def clean_artist(artist: str) -> str:
    """Оставляет основного исполнителя: без feat., дублей и суффикса Topic."""
    out = _TOPIC_RE.sub("", artist)
    out = _FEAT_BRACKET_RE.sub(" ", out)
    out = _FEAT_TAIL_RE.sub("", out)
    parts = [p.strip() for p in out.split(",") if p.strip()]
    if parts:
        # «LaLion, LaLion» — тег с продублированным артистом
        unique = list(dict.fromkeys(p.casefold() for p in parts))
        out = parts[0] if len(unique) > 1 else parts[0]
    return _tidy(out) or artist.strip()


def query_variants(artist: str, title: str) -> list[tuple[str, str]]:
    """Пары (артист, название) для поиска: сначала как в тегах, затем очищенные.

    Дубли отбрасываются — если чистить нечего, лишних запросов не будет.
    """
    variants = [(artist, title)]
    cleaned = (clean_artist(artist), clean_title(title))
    if (cleaned[0].casefold(), cleaned[1].casefold()) != (artist.casefold(), title.casefold()):
        variants.append(cleaned)
    return variants
