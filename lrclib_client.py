"""Клиент API lrclib.net: точный поиск + fallback-поиск с выбором лучшего кандидата."""

from __future__ import annotations

import random
import threading
import time

import requests

from normalize import query_variants

API_BASE = "https://lrclib.net/api"
USER_AGENT = "lrcfetch/1.0 (https://lrclib.net)"

# Допустимое расхождение длительности трека и кандидата из поиска, сек.
DURATION_TOLERANCE = 5.0

RETRIES = 4
RETRY_BASE = 0.8          # база экспоненциального бэкоффа, сек
RETRY_CAP = 10.0          # потолок паузы между попытками, сек
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# lrclib режет за ПАРАЛЛЕЛЬНЫЙ залп (429), а не за объём: 20 запросов подряд
# проходят, 8 одновременных — нет. Ограничиваем одновременные запросы к нему
# на весь процесс, чтобы burst не возникал. Гейт общий для всех потоков.
MAX_CONCURRENT = 4
_gate = threading.BoundedSemaphore(MAX_CONCURRENT)


class LrclibClient:
    def __init__(self, timeout: float = 15.0):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._timeout = timeout

    @staticmethod
    def _sleep_seconds(attempt: int, resp: requests.Response | None) -> float:
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    return float(retry_after)
                except ValueError:
                    pass
        # Экспонента с джиттером: без джиттера все потоки повторяют разом.
        return min(RETRY_BASE * (2 ** attempt), RETRY_CAP) + random.uniform(0, 0.5)

    def _get(self, endpoint: str, params: dict) -> requests.Response:
        """Запрос с повтором на таймаут/обрыв/429/5xx и общим лимитом параллелизма."""
        last_exc: Exception | None = None
        for attempt in range(RETRIES + 1):
            resp: requests.Response | None = None
            try:
                with _gate:
                    resp = self._session.get(f"{API_BASE}/{endpoint}", params=params,
                                             timeout=self._timeout)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
            else:
                if resp.status_code not in RETRYABLE_STATUS:
                    return resp
                last_exc = requests.HTTPError(
                    f"{resp.status_code} {resp.reason}", response=resp)
            if attempt < RETRIES:
                time.sleep(self._sleep_seconds(attempt, resp))
        raise last_exc  # type: ignore[misc]

    def get_exact(self, artist: str, track: str, album: str = "",
                  duration: float | None = None) -> dict | None:
        """GET /api/get — точное совпадение. None, если записи нет (404)."""
        params = {"artist_name": artist, "track_name": track}
        if album:
            params["album_name"] = album
        if duration is not None:
            params["duration"] = str(int(round(duration)))
        resp = self._get("get", params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def search(self, artist: str, track: str) -> list[dict]:
        """GET /api/search — нестрогий поиск."""
        if artist:
            params = {"track_name": track, "artist_name": artist}
        else:
            params = {"q": track}
        resp = self._get("search", params)
        resp.raise_for_status()
        return resp.json()

    def find_lyrics(self, artist: str, track: str, album: str = "",
                    duration: float | None = None) -> dict | None:
        """Полный цикл поиска: /get с длительностью, затем /search с фильтром.

        Цель — синхронный текст: запись без таймкодов не останавливает поиск,
        а сохраняется как запасной вариант на случай, если synced нигде нет.

        Возвращает запись lrclib (dict) или None.
        """
        def is_final(record: dict | None) -> bool:
            return bool(record and (record.get("syncedLyrics") or record.get("instrumental")))

        fallback: dict | None = None
        # Сначала теги как есть, затем очищенный вариант («Song (Official Video)»
        # → «Song»): точный запрос работает лучше на исходных тегах, а поиск —
        # на очищенных, поэтому проходим оба этапа по каждому варианту.
        for q_artist, q_track in query_variants(artist, track):
            if not q_track:
                continue
            if q_artist and duration is not None:
                for alb in ([album, ""] if album else [""]):
                    record = self.get_exact(q_artist, q_track, alb, duration)
                    if is_final(record):
                        return record
                    if record is not None and fallback is None:
                        fallback = record
            best = pick_best(self.search(q_artist, q_track), duration)
            if is_final(best):
                return best
            if best is not None and fallback is None:
                fallback = best
        return fallback


    def list_candidates(self, artist: str, track: str,
                        duration: float | None = None) -> list[dict]:
        """Все варианты для ручного выбора — без жёсткого отсева по длительности.

        Порядок: сначала synced, затем по близости длительности. Отбрасываются
        только записи вообще без текста.
        """
        found: dict[int, dict] = {}
        for q_artist, q_track in query_variants(artist, track):
            if not q_track:
                continue
            for rec in self.search(q_artist, q_track):
                if rec.get("syncedLyrics") or rec.get("plainLyrics") or rec.get("instrumental"):
                    found.setdefault(rec["id"], rec)

        def sort_key(rec: dict):
            delta = float("inf")
            if duration is not None and rec.get("duration") is not None:
                delta = abs(float(rec["duration"]) - duration)
            return (not rec.get("syncedLyrics"), delta)

        return sorted(found.values(), key=sort_key)


def pick_best(candidates: list[dict], duration: float | None) -> dict | None:
    """Лучший кандидат: сначала с таймкодами, ближайший по длительности.

    Если длительность трека известна, кандидаты дальше DURATION_TOLERANCE
    отбрасываются — чужая версия песни с другим таймингом хуже, чем ничего.
    """
    if not candidates:
        return None

    def usable(c: dict) -> bool:
        return bool(c.get("syncedLyrics") or c.get("plainLyrics") or c.get("instrumental"))

    pool = [c for c in candidates if usable(c)]
    if duration is not None:
        pool = [c for c in pool
                if c.get("duration") is not None
                and abs(float(c["duration"]) - duration) <= DURATION_TOLERANCE]
        pool.sort(key=lambda c: (not c.get("syncedLyrics"),
                                 abs(float(c["duration"]) - duration)))
    else:
        pool.sort(key=lambda c: not c.get("syncedLyrics"))
    return pool[0] if pool else None
