"""Тесты форматирования оценки времени. Без Qt. Запуск: python test_eta.py"""

import re
from pathlib import Path

# format_eta лежит в app.py, который тянет PySide6 — берём функцию напрямую,
# чтобы тест оставался быстрым и не требовал GUI.
_src = (Path(__file__).parent / "app.py").read_text(encoding="utf-8")
_match = re.search(r"def format_eta.*?(?=\n\ndef )", _src, re.DOTALL)
_ns: dict = {}
exec(_match.group(0), _ns)
format_eta = _ns["format_eta"]

CASES = [
    (0, "почти готово"),
    (5, "почти готово"),
    (9.9, "почти готово"),
    (12, "~10 с"),
    (13, "~15 с"),
    (44, "~45 с"),
    (59, "~60 с"),
    (60, "~1 мин"),
    (90, "~2 мин"),
    (600, "~10 мин"),
    (1620, "~27 мин"),
    (3540, "~59 мин"),
    (3600, "~1 ч"),
    (4500, "~1 ч 15 мин"),
    (7200, "~2 ч"),
]


def main() -> int:
    failed = 0
    for seconds, expected in CASES:
        got = format_eta(seconds)
        if got != expected:
            print(f"FAIL format_eta({seconds}) -> {got!r}, ожидалось {expected!r}")
            failed += 1
    print(f"{'FAIL' if failed else 'OK'}: {len(CASES) - failed}/{len(CASES)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
