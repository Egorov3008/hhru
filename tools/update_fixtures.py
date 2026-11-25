"""Live-smoke: webbridge → парсер → golden-сверка на живой выдаче.

Запускается с машины, где живёт webbridge-даemon (:10086). Прогоняет
парсер по живой HTML-выдаче hh.ru и сверяет первые 5 карточек с
сохранёнными фикстурами. Провал = markup изменился → обновить
фикстуры (tools/update_fixtures.py --save).
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _configure_sys_path() -> None:
    """Путь к parser.py должен быть в sys.path до его импорта."""
    for candidate in (_ROOT, _ROOT / "tools" / "hh-agent"):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


_configure_sys_path()

import httpx  # noqa: E402
from parser import parse_search_html  # noqa: E402

FIXTURE_DIR = _ROOT / "tests" / "fixtures"


def _norm(value):
    """Нормализация пробелов (узкий/неразрывный в текстах hh.ru)."""
    import re

    if value is None:
        return None
    return re.sub(r"[\s ]+", " ", str(value)).strip() or None


def _parse_name(stem: str) -> tuple[str, str, str]:
    """python_area1_p0 → ('python', '1', '0')."""
    import urllib.parse

    parts = stem.split("_")
    return urllib.parse.quote(parts[0]), parts[1][len("area"):], parts[2][1:]


def wb(action: str, args: dict) -> dict:
    resp = httpx.post(
        "http://127.0.0.1:10086/command",
        json={"action": action, "args": args, "session": "hhru"},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    save = "--save" in sys.argv
    ok = 0
    total = 0
    for fx in sorted(FIXTURE_DIR.glob("*.html")) if not save else []:
        total += 1
        name = fx.stem  # e.g. python_area1_p0
        query, area, page = _parse_name(name)
        url = (
            "https://krasnoznamensk.hh.ru/search/vacancy?text="
            + query
            + f"&searchArea={area}&order=submit_date&itemsOnPage=50&page={page}"
        )
        try:
            wb("navigate", {"url": url, "newTab": True})
            html = wb("evaluate", {"code": "document.documentElement.outerHTML"})["data"]["value"]
        except Exception as exc:
            print(f"[fail] {fx.name}: {exc}")
            total -= 1
            continue
        golden = json.loads(fx.with_suffix(".json").read_text())
        parsed = parse_search_html(html)
        mismatches = [
            (i, field)
            for i in range(min(5, len(golden)))
            for field in ("id", "title", "employer_name", "area_name")
            if i < len(parsed) and _norm(parsed[i][field]) != _norm(golden[i][field])
        ]
        if mismatches:
            print(f"[СЛОМАЛОСЬ] {fx.name}: {mismatches[:3]} — обнови фикстуры!")
        else:
            ok += 1
            print(f"[ok] {fx.name}: {len(parsed)} карточек совпадают")
    print(f"\nИтог: {ok}/{total}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
