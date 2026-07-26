"""Тесты проверки совпадения. Без сети. Запуск: python test_providers.py"""

from providers.base import LyricsResult, Query, matches, similarity


def res(title, artist, duration=None):
    return LyricsResult(source="test", title=title, artist=artist, duration=duration)


MATCH_CASES = [
    # (результат, запрос, ожидаем совпадение?, пояснение)
    (res("Creep", "Radiohead", 239), Query("Radiohead", "Creep", "", 239),
     True, "точное совпадение"),
    (res("Creep", "Radiohead", 241), Query("Radiohead", "Creep", "", 239),
     True, "длительность в пределах допуска"),
    (res("Creep", "Radiohead", 259), Query("Radiohead", "Creep", "", 239),
     False, "акустика на 20с длиннее — другая версия"),
    (res("SEROTONIN", "LaLion, Kordhell", 208), Query("LaLion", "SEROTONIN", "", 207),
     True, "артист из списка совпадает по части"),
    (res("SEROTONIN (REMIX)", "LaLion", 157), Query("LaLion", "SEROTONIN", "", 207),
     False, "ремикс, длительность не та"),

    # главное: мусор от источника, который всегда что-то возвращает
    (res("Fell Orient (PHONK)", "WQ", 140), Query("Zzxqv", "Qqqwww", "", 140),
     False, "посторонний трек с совпавшей длительностью"),
    (res("忘情水", "刘德华", 239), Query("Radiohead", "Creep", "", 239),
     False, "совсем чужой трек"),
    (res("POSE", "KINO", 179), Query("Кино", "Группа крови", "", 179),
     False, "другой исполнитель KINO"),

    # длительности нет — требования к названиям строже
    (res("Creep", "Radiohead"), Query("Radiohead", "Creep"),
     True, "без длительности, но названия точные"),
    (res("Creep (Acoustic)", "Radiohead"), Query("Radiohead", "Creep"),
     True, "подстрока названия"),
    (res("Creepin'", "Metro Boomin"), Query("Radiohead", "Creep"),
     False, "похожее название, чужой артист"),
]

SIMILARITY_CASES = [
    ("Creep", "creep", 1.0),
    ("Creep", "CREEP!", 1.0),
    ("Группа крови", "группа  крови", 1.0),
]


def main() -> int:
    failed = 0
    for result, query, expected, note in MATCH_CASES:
        got = matches(result, query)
        if got != expected:
            print(f"FAIL [{note}] matches({result.artist!r} — {result.title!r}, "
                  f"{query.artist!r} — {query.title!r}) -> {got}, ожидалось {expected}")
            failed += 1
    for a, b, expected in SIMILARITY_CASES:
        got = similarity(a, b)
        if abs(got - expected) > 0.001:
            print(f"FAIL similarity({a!r}, {b!r}) -> {got:.3f}, ожидалось {expected}")
            failed += 1

    total = len(MATCH_CASES) + len(SIMILARITY_CASES)
    print(f"{'FAIL' if failed else 'OK'}: {total - failed}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
