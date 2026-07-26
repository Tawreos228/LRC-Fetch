"""Тесты нормализации запросов. Запуск: python test_normalize.py"""

from normalize import clean_artist, clean_title, query_variants

TITLE_CASES = [
    # мусор оформления — вычищаем
    ("Houdini (Official Audio)", "Houdini"),
    ("Houdini [Official Music Video]", "Houdini"),
    ("Numb (Official Video)", "Numb"),
    ("Creep (Remastered 2011)", "Creep"),
    ("Creep (2011 Remaster)", "Creep"),
    ("Bohemian Rhapsody - Remastered 2011", "Bohemian Rhapsody"),
    ("Smells Like Teen Spirit (Radio Edit)", "Smells Like Teen Spirit"),
    ("Song (Album Version)", "Song"),
    ("Song [Explicit]", "Song"),
    ("Song (HD)", "Song"),
    ("Song (Lyric Video)", "Song"),
    ("Song (Visualizer)", "Song"),
    ("Song (feat. Drake)", "Song"),
    ("Song ft. Drake", "Song"),
    ("Песня (Официальный клип)", "Песня"),
    ("Song (Official Video) (Remastered)", "Song"),
    ("  Song   (Official Video)  ", "Song"),

    # версии, меняющие саму запись, — НЕ трогаем: у них свой текст и тайминг
    ("Creep (Acoustic)", "Creep (Acoustic)"),
    ("Song (Live at Wembley)", "Song (Live at Wembley)"),
    ("Song (Remix)", "Song (Remix)"),
    ("Song (Instrumental)", "Song (Instrumental)"),
    ("Song (Demo)", "Song (Demo)"),
    ("Song (Sped Up)", "Song (Sped Up)"),

    # ничего лишнего нет — оставляем как есть
    ("Creep", "Creep"),
    ("SEROTONIN", "SEROTONIN"),
    ("#3 (Rhubarb)", "#3 (Rhubarb)"),
]

ARTIST_CASES = [
    ("Eminem feat. Drake", "Eminem"),
    ("Eminem ft. Drake", "Eminem"),
    ("Eminem featuring Drake", "Eminem"),
    ("LaLion, LaLion", "LaLion"),
    ("Radiohead - Topic", "Radiohead"),
    ("Кино", "Кино"),
    ("AC/DC", "AC/DC"),
    ("Simon & Garfunkel", "Simon & Garfunkel"),
]

VARIANT_CASES = [
    # (артист, название) -> ожидаемый список пар (порядок важен)
    (("Eminem feat. Drake", "Houdini (Official Audio)"),
     [("Eminem feat. Drake", "Houdini (Official Audio)"),
      ("Eminem", "Houdini")]),
    # чистить нечего — один вариант, лишних запросов не делаем
    (("Radiohead", "Creep"), [("Radiohead", "Creep")]),
    # чистится только название
    (("Radiohead", "Creep (Remastered 2011)"),
     [("Radiohead", "Creep (Remastered 2011)"), ("Radiohead", "Creep")]),
]


def main() -> int:
    failed = 0
    for raw, expected in TITLE_CASES:
        got = clean_title(raw)
        if got != expected:
            print(f"FAIL clean_title({raw!r}) -> {got!r}, ожидалось {expected!r}")
            failed += 1
    for raw, expected in ARTIST_CASES:
        got = clean_artist(raw)
        if got != expected:
            print(f"FAIL clean_artist({raw!r}) -> {got!r}, ожидалось {expected!r}")
            failed += 1
    for (artist, title), expected in VARIANT_CASES:
        got = query_variants(artist, title)
        if got != expected:
            print(f"FAIL query_variants({artist!r}, {title!r}) ->\n  {got}\n  ожидалось {expected}")
            failed += 1

    total = len(TITLE_CASES) + len(ARTIST_CASES) + len(VARIANT_CASES)
    print(f"{'FAIL' if failed else 'OK'}: {total - failed}/{total}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
