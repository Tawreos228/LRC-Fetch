"""Тесты повторов lrclib-клиента: 429/5xx ретраятся, 404/200 — нет. Без сети."""

import lrclib_client
from lrclib_client import LrclibClient


class FakeResp:
    def __init__(self, status, reason="", headers=None):
        self.status_code = status
        self.reason = reason
        self.headers = headers or {}


class FakeSession:
    """Отдаёт заранее заданную последовательность ответов/исключений."""

    def __init__(self, sequence):
        self._seq = list(sequence)
        self.calls = 0
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        item = self._seq.pop(0) if self._seq else self._last
        self._last = item
        if isinstance(item, Exception):
            raise item
        return item


def client_with(sequence):
    c = LrclibClient()
    c._session = FakeSession(sequence)
    return c


def main() -> int:
    failed = 0
    total = 0
    # мгновенные паузы
    orig_sleep = lrclib_client.time.sleep
    lrclib_client.time.sleep = lambda s: None

    def check(name, cond):
        nonlocal failed, total
        total += 1
        if not cond:
            print(f"FAIL {name}")
            failed += 1

    try:
        import requests

        # 429 дважды, затем 200 -> вернётся 200 на 3-й попытке
        c = client_with([FakeResp(429, "Too Many Requests"),
                         FakeResp(429, "Too Many Requests"),
                         FakeResp(200, "OK")])
        r = c._get("search", {})
        check("429,429,200 -> 200", r.status_code == 200)
        check("429,429,200 -> 3 запроса", c._session.calls == 3)

        # всегда 429 -> после RETRIES бросает HTTPError
        c = client_with([FakeResp(429, "Too Many Requests")])
        try:
            c._get("search", {})
            check("всегда 429 -> исключение", False)
        except requests.HTTPError as e:
            check("всегда 429 -> HTTPError", "429" in str(e))
        check("всегда 429 -> RETRIES+1 попыток",
              c._session.calls == lrclib_client.RETRIES + 1)

        # таймаут дважды, затем 200
        c = client_with([requests.Timeout(), requests.Timeout(), FakeResp(200)])
        r = c._get("get", {})
        check("timeout,timeout,200 -> 200", r.status_code == 200)

        # 404 не ретраится, возвращается сразу
        c = client_with([FakeResp(404, "Not Found"), FakeResp(200)])
        r = c._get("get", {})
        check("404 -> сразу без ретрая", r.status_code == 404 and c._session.calls == 1)

        # 500 ретраится
        c = client_with([FakeResp(500), FakeResp(200)])
        r = c._get("get", {})
        check("500 -> ретрай -> 200", r.status_code == 200 and c._session.calls == 2)

        # Retry-After уважается
        s = LrclibClient._sleep_seconds(0, FakeResp(429, headers={"Retry-After": "3"}))
        check("Retry-After=3 -> 3.0", s == 3.0)

        # без Retry-After — экспонента в пределах cap+джиттер
        s0 = LrclibClient._sleep_seconds(0, FakeResp(429))
        s_big = LrclibClient._sleep_seconds(20, FakeResp(429))
        check("бэкофф attempt0 в разумных пределах", 0 <= s0 <= 1.4)
        check("бэкофф ограничен cap", s_big <= lrclib_client.RETRY_CAP + 0.6)
    finally:
        lrclib_client.time.sleep = orig_sleep

    print(f"{'FAIL' if failed else 'OK'}: {total - failed}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
