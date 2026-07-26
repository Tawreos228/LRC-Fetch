"""Провайдер lrclib.net — основной источник."""

from __future__ import annotations

from lrclib_client import LrclibClient

from .base import LyricsResult, Provider, Query, rank_key


class LrclibProvider(Provider):
    name = "LRCLIB"

    def __init__(self, client: LrclibClient | None = None):
        self._client = client or LrclibClient()

    def _to_result(self, rec: dict) -> LyricsResult:
        return LyricsResult(
            source=self.name,
            title=rec.get("trackName") or "",
            artist=rec.get("artistName") or "",
            album=rec.get("albumName") or "",
            duration=rec.get("duration"),
            synced=(rec.get("syncedLyrics") or "").strip(),
            plain=(rec.get("plainLyrics") or "").strip(),
            instrumental=bool(rec.get("instrumental")),
            remote_id=str(rec.get("id", "")),
        )

    def find(self, query: Query) -> LyricsResult | None:
        record = self._client.find_lyrics(
            query.artist, query.title, query.album, query.duration)
        # lrclib на бессмысленный запрос отдаёт пустой ответ, а не мусор,
        # плюс сам клиент фильтрует по длительности — доверяем его выбору.
        return self._to_result(record) if record else None

    def candidates(self, query: Query) -> list[LyricsResult]:
        records = self._client.list_candidates(
            query.artist, query.title, query.duration)
        results = [self._to_result(r) for r in records]
        return sorted([r for r in results if r.has_text],
                      key=lambda r: rank_key(r, query.duration))
