"""Golden-тесты парсера выдачи hh.ru (Шаг 2, Task 1).

Фикстуры — сохранённые HTML-страницы выдачи (tests/fixtures/*.html) и
ожидающий JSON рядом с ними. Markup hh.ru меняется — парсер обязан
давать те же поля, что в день снятия фикстуры.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# tools/hh-agent — отдельный корень импорта: имя пакета с дефисом,
# обычному пакету не подходит, поэтому sys.path-вставка до импорта
_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "tools" / "hh-agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from parser import (  # noqa: E402
    UTC,
    parse_published,
    parse_salary,
    parse_search_html,
)

_FIXTURE_DIR = _ROOT / "tests" / "fixtures"


def _norm(value) -> str | None:
    """Нормализация пробелов (узкий/неразрывный в текстах hh.ru)."""
    import re

    if value is None:
        return None
    return re.sub(r"[\s ]+", " ", str(value)).strip() or None


def _pairs() -> list[tuple[str, list[dict]]]:
    """(имя, golden-карточки) — фикстуры в алфавитном порядке."""
    return [
        (p.stem, json.loads(p.with_suffix(".json").read_text()))
        for p in sorted(_FIXTURE_DIR.glob("*.html"))
    ]


@pytest.mark.skipif(not _pairs(), reason="golden-фикстуры не сняты (tools/update_fixtures.py)")
@pytest.mark.parametrize("name", [name for name, _ in _pairs()])
def test_golden_parser(name: str) -> None:
    golden = dict(_pairs())[name]
    html = _FIXTURE_DIR / f"{name}.html"
    parsed = parse_search_html(html.read_text())
    assert len(parsed) == len(golden), f"число карточек: {len(parsed)} != {len(golden)}"
    for got, want in zip(parsed[:5], golden[:5], strict=True):
        for field in ("id", "title", "employer_name", "area_name"):
            assert _norm(got[field]) == _norm(want[field]), (
                f"{name}: поле {field}: {got[field]!r} != {want[field]!r}"
            )


def test_golden_fixtures_exist() -> None:
    """Хотя бы три фикстуры в репозитории — защита от тихой потери."""
    assert len(_pairs()) >= 3, f"фикстур меньше трёх: {len(_pairs())}"


def test_salary_text_to_min_max() -> None:
    """Числа вилки из текстового зарплатного блока (₽-блок без data-qa)."""
    assert parse_salary("20 000 – 150 000 ₽") == (20000, 150000)
    assert parse_salary("140 000 ₽") == (140000, None)
    assert parse_salary(None) == (None, None)
    assert parse_salary("100 000 ₽ — 200 000 ₽") == (100000, 200000)


def test_published_to_utc() -> None:
    """Конверсия «N часов назад» / «Вчера, HH:MM» (Europe/Moscow) в UTC."""
    assert parse_published("2 часа назад") is not None
    assert parse_published("Вчера, 18:45") is not None
    assert parse_published("Сегодня, 10:00") is not None
    result = parse_published("3 дня назад")
    assert result is not None and result.tzinfo is UTC
