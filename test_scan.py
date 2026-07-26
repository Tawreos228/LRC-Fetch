"""Тесты определения текста по .lrc и апгрейда plain→synced. Без сети."""

import tempfile
from pathlib import Path

from core import (
    Options, Status, Track, has_any_text, has_synced_text, is_synced_lyrics,
    process_track, scan_lrc_status,
)

SYNCED = "[00:12.34] line one\n[00:15.00] line two\n"
SYNCED_HMS = "[01:02:03] long track line\n"
PLAIN = "just a line\nanother line\n"
# Plain-текст с LRC-метатегами: НЕ должен считаться синхронным.
PLAIN_WITH_META = "[ti:Song]\n[ar:Artist]\n[al:Album]\nfirst line\nsecond line\n"


def test_is_synced():
    cases = [
        (SYNCED, True), (SYNCED_HMS, True),
        (PLAIN, False), (PLAIN_WITH_META, False), ("", False),
    ]
    failed = 0
    for text, expected in cases:
        if is_synced_lyrics(text) != expected:
            print(f"FAIL is_synced_lyrics({text[:20]!r}) != {expected}")
            failed += 1
    return failed, len(cases)


def test_scan_status(tmp: Path):
    cases = [
        (SYNCED, Status.HAS_SYNCED),
        (PLAIN, Status.HAS_PLAIN),
        (PLAIN_WITH_META, Status.HAS_PLAIN),
        (None, Status.NO_LYRICS),          # файла нет
        ("   \n", Status.NO_LYRICS),        # пустой
    ]
    failed = 0
    for i, (content, expected) in enumerate(cases):
        lrc = tmp / f"t{i}.lrc"
        if content is None:
            lrc.unlink(missing_ok=True)
        else:
            lrc.write_text(content, encoding="utf-8")
        got = scan_lrc_status(lrc)
        if got != expected:
            print(f"FAIL scan_lrc_status(case {i}) -> {got}, ожидалось {expected}")
            failed += 1
    return failed, len(cases)


def test_categories():
    cases = [
        (Status.HAS_SYNCED, True, True),
        (Status.SYNCED, True, True),
        (Status.HAS_PLAIN, False, True),
        (Status.PLAIN, False, True),
        (Status.NO_LYRICS, False, False),
        (Status.NOT_FOUND, False, False),
        (Status.PENDING, False, False),
    ]
    failed = 0
    for status, want_synced, want_any in cases:
        if has_synced_text(status) != want_synced:
            print(f"FAIL has_synced_text({status}) != {want_synced}"); failed += 1
        if has_any_text(status) != want_any:
            print(f"FAIL has_any_text({status}) != {want_any}"); failed += 1
    return failed, len(cases) * 2


class FakeProvider:
    """Отдаёт заранее заданный результат, не ходя в сеть."""
    name = "fake"

    def __init__(self, result):
        self._result = result

    def find(self, query):
        return self._result


def _result(synced="", plain=""):
    from providers.base import LyricsResult
    return LyricsResult(source="fake", title="t", artist="a", synced=synced, plain=plain)


def test_process(tmp: Path):
    failed = 0
    total = 0

    def check(name, track, providers, options, want_status, want_written):
        nonlocal failed, total
        total += 1
        process_track(track, providers, options)
        ok = track.status == want_status
        written = track.lrc_path.read_text(encoding="utf-8") if track.lrc_path.exists() else None
        if written is not None:
            written = written.strip()
        if want_written is not None and written != want_written:
            ok = False
        if not ok:
            print(f"FAIL [{name}] статус={track.status} (ждали {want_status}), "
                  f"файл={written!r} (ждали {want_written!r})")
            failed += 1

    # синхронный .lrc уже есть, overwrite off -> пропуск без записи
    p = tmp / "a.wav"; lrc = p.with_suffix(".lrc")
    lrc.write_text(SYNCED, encoding="utf-8")
    check("skip synced", Track(path=p), [FakeProvider(_result(synced="[00:01.00] new"))],
          Options(overwrite=False), Status.HAS_SYNCED, SYNCED.strip())

    # plain .lrc есть, онлайн нашёлся synced -> апгрейд без overwrite
    p = tmp / "b.wav"; lrc = p.with_suffix(".lrc")
    lrc.write_text(PLAIN, encoding="utf-8")
    check("upgrade plain->synced", Track(path=p),
          [FakeProvider(_result(synced="[00:02.00] upgraded"))],
          Options(overwrite=False), Status.SYNCED, "[00:02.00] upgraded")

    # plain .lrc есть, онлайн только plain -> не трогаем, остаётся plain
    p = tmp / "c.wav"; lrc = p.with_suffix(".lrc")
    lrc.write_text(PLAIN, encoding="utf-8")
    check("keep plain", Track(path=p), [FakeProvider(_result(plain="different plain"))],
          Options(overwrite=False), Status.HAS_PLAIN, PLAIN.strip())

    # файла нет, онлайн synced -> пишем
    p = tmp / "d.wav"
    check("fresh synced", Track(path=p), [FakeProvider(_result(synced="[00:03.00] fresh"))],
          Options(overwrite=False), Status.SYNCED, "[00:03.00] fresh")

    # synced .lrc есть, overwrite ON -> перезапись
    p = tmp / "e.wav"; lrc = p.with_suffix(".lrc")
    lrc.write_text(SYNCED, encoding="utf-8")
    check("overwrite synced", Track(path=p),
          [FakeProvider(_result(synced="[00:04.00] replaced"))],
          Options(overwrite=True), Status.SYNCED, "[00:04.00] replaced")

    return failed, total


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        results = [
            test_is_synced(),
            test_scan_status(tmp),
            test_categories(),
            test_process(tmp),
        ]
    failed = sum(f for f, _ in results)
    total = sum(t for _, t in results)
    print(f"{'FAIL' if failed else 'OK'}: {total - failed}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
