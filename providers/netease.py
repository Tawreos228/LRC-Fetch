"""Провайдер NetEase Cloud Music — запасной источник.

Особенность, определяющая всю логику модуля: на любой запрос, включая
бессмысленный, NetEase возвращает какие-нибудь песни. Пустого ответа не бывает.
Поэтому каждый кандидат обязан пройти проверку matches(), иначе в .lrc уедет
текст постороннего трека.
"""

from __future__ import annotations

import time

import requests

from normalize import query_variants

from .base import LyricsResult, Provider, Query, matches, rank_key

API_BASE = "https://music.163.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://music.163.com/",
}
SEARCH_LIMIT = 10
RETRIES = 2
RETRY_DELAY = 1.0

# Сколько кандидатов из выдачи проверять текстом (каждый — отдельный запрос).
MAX_LYRIC_FETCHES = 4


class NeteaseProvider(Provider):
    name = "NetEase"

    def __init__(self, timeout: float = 15.0):
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self._timeout = timeout

    def _post(self, endpoint: str, data: dict) -> dict:
        last: Exception | None = None
        for attempt in range(RETRIES + 1):
            try:
                # NetEase ставит cookie NMTID, и со второго запроса подряд начинает
                # отдавать выдачу, не связанную с запросом. Чистим перед каждым.
                self._session.cookies.clear()
                resp = self._session.post(f"{API_BASE}/{endpoint}", data=data,
                                          timeout=self._timeout)
                resp.raise_for_status()
                return resp.json()
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = exc
                if attempt < RETRIES:
                    time.sleep(RETRY_DELAY * (attempt + 1))
            except ValueError as exc:  # ответ не JSON
                raise RuntimeError(f"NetEase вернул не JSON: {exc}") from exc
        raise last  # type: ignore[misc]

    def _search(self, artist: str, title: str) -> list[dict]:
        term = f"{artist} {title}".strip() if artist else title
        data = self._post("search/get", {"s": term, "type": 1,
                                         "limit": SEARCH_LIMIT, "offset": 0})
        return ((data.get("result") or {}).get("songs")) or []

    def _fetch_lyrics(self, song_id: int) -> tuple[str, str]:
        """Возвращает (synced, plain)."""
        data = self._post("song/lyric", {"id": song_id, "lv": 1, "kv": 1, "tv": -1})
        text = ((data.get("lrc") or {}).get("lyric") or "").strip()
        if not text:
            return "", ""
        # Строки вида «[00:12.34] ...» — синхронный текст; иначе обычный.
        if text.lstrip().startswith("["):
            return text, ""
        return "", text

    def _song_to_result(self, song: dict) -> LyricsResult:
        artists = ", ".join(a.get("name", "") for a in song.get("artists", []))
        album = (song.get("album") or {}).get("name") or ""
        duration_ms = song.get("duration") or 0
        return LyricsResult(
            source=self.name,
            title=song.get("name") or "",
            artist=artists,
            album=album,
            duration=(duration_ms / 1000) if duration_ms else None,
            remote_id=str(song.get("id", "")),
        )

    def _matching_songs(self, query: Query) -> list[LyricsResult]:
        seen: set[str] = set()
        out: list[LyricsResult] = []
        for q_artist, q_title in query_variants(query.artist, query.title):
            if not q_title:
                continue
            for song in self._search(q_artist, q_title):
                result = self._song_to_result(song)
                if result.remote_id in seen:
                    continue
                seen.add(result.remote_id)
                if matches(result, query):
                    out.append(result)
            if out:
                break  # первый вариант запроса дал совпадения — хватит
        return sorted(out, key=lambda r: rank_key(r, query.duration))

    def find(self, query: Query) -> LyricsResult | None:
        best_plain: LyricsResult | None = None
        for result in self._matching_songs(query)[:MAX_LYRIC_FETCHES]:
            synced, plain = self._fetch_lyrics(int(result.remote_id))
            if synced:
                result.synced = synced
                return result
            if plain and best_plain is None:
                result.plain = plain
                best_plain = result
        return best_plain

    def candidates(self, query: Query) -> list[LyricsResult]:
        out: list[LyricsResult] = []
        for result in self._matching_songs(query)[:MAX_LYRIC_FETCHES]:
            result.synced, result.plain = self._fetch_lyrics(int(result.remote_id))
            if result.has_text:
                out.append(result)
        return sorted(out, key=lambda r: rank_key(r, query.duration))
