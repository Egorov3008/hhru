"""Парсер HTML выдачи hh.ru в карточки golden-контракта (Шаг 2).

Карточка = div с числовым атрибутом id. Поля title/employer/area
извлекаются по стабильным `data-qa`; зарплатный блок и дата публикации
`data-qa` не имеют — берём по тексту (₽ / «N часов назад»). Работает
одинаково на живом DOM (webbridge `evaluate`) и на сохранённых
HTML-фикстурах tests/fixtures/*.html.

Поле `area_name` — из data-qa, но содержит город/адрес; golden JSON
хранит его как есть. Поле `employer_id` парсер не извлекает (в выдаче
его нет) — адаптер заполняет его из url или留 None.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")
_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"

# data-qa селекторы (стабильны годами)
_QA_SELECTORS: dict[str, str] = {
    "title": "serp-item__title",
    "employer_name": "vacancy-serp__vacancy-employer",
    "area_name": "vacancy-serp__vacancy-address",
}

_RUB = re.compile("₽")
_DATE_RE = re.compile(
    r"(\d+\s*(?:минут|мин|час|дн\.|дня)|Вчера|Сегодня|только что)", re.IGNORECASE
)
_EXPERIENCE_RE = re.compile(r"(Без опыта|Опыт)")


def _norm(value: str | None) -> str | None:
    """Нормализация пробелов: hh.ru использует узкий/неразрывный пробел."""
    if value is None:
        return None
    text = re.sub(r"[\s ]+", " ", str(value)).strip()
    return text or None


def parse_salary(text: str | None) -> tuple[int | None, int | None]:
    """Числа вилки из текстового зарплатного блока (₽-блок без data-qa)."""
    text = _norm(text)
    if not text or "₽" not in text:
        return (None, None)
    nums = [int(n.replace(" ", "").replace(" ", "")) for n in re.findall(r"\d+(?:\s\d+)*", text)]
    nums = [n for n in nums if n > 100]  # «Сейчас смотрят 10 человек» — не зарплата
    if not nums:
        return (None, None)
    return (nums[0], None) if len(nums) == 1 else (min(nums[:2]), max(nums[:2]))


def parse_published(text: str | None) -> datetime | None:
    """Дата публикации (Europe/Moscow) → timezone-aware UTC."""
    text = _norm(text)
    if not text:
        return None
    now_moscow = datetime.now(MOSCOW)
    if "только что" in text.lower():
        return now_moscow.astimezone(UTC)
    m = re.search(r"(\d+)\s*(минут|мин|час|дн\.|дня)", text, re.IGNORECASE)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        delta = (
            timedelta(minutes=n)
            if unit.startswith("мин")
            else timedelta(hours=n)
            if unit.startswith("час")
            else timedelta(days=n)
        )
        return (now_moscow - delta).astimezone(UTC)
    m = re.search(r"(Вчера|Сегодня),?\s*(\d{1,2}):(\d{2})", text)
    if m:
        hours, minutes = int(m.group(2)), int(m.group(3))
        day = (
            now_moscow.date()
            if m.group(1).lower() == "сегодня"
            else now_moscow.date() - timedelta(days=1)
        )
        naive = datetime(day.year, day.month, day.day, hours, minutes, tzinfo=MOSCOW)
        return naive.astimezone(UTC)
    return None


def parse_search_html(html: str) -> list[dict]:
    """Разобрать HTML выдачи hh.ru в golden-контракт (список dict).

    Поля: id, title, employer_name, area_name (по data-qa);
    salary_min/max, salary_text, published_at (по тексту);
    experience, snippet.
    """
    return [_parse_card(chunk) for chunk in _split_cards(html)]


def _split_cards(html: str) -> list[str]:
    """Выделить HTML каждой карточки по div с числовым id."""
    positions = [m.start() for m in re.finditer(r'<div\b[^>]*id="\d{8,9}"', html)]
    bounds = positions[1:] + [len(html)]
    return [html[start:end] for (start, end) in zip(positions, bounds, strict=True)]


def _parse_card(chunk: str) -> dict:
    from selectolax.lexbor import LexborHTMLParser

    root = LexborHTMLParser(chunk).root
    card_id = re.search(r'<div\b[^>]*id="(\d{8,9})"', str(chunk).strip())
    raw_html = str(chunk)

    def text_of(data_qa: str) -> str | None:
        node = root.css_first(f'[data-qa^="{data_qa}"]')
        return _norm(node.text()) if node else None

    # зарплатный блок: первый текст с ₽
    salary_line: str | None = None
    for node in root.css("[class]") or []:
        t = _norm(node.text())
        if t and "₽" in t:
            salary_line = t
            break

    salary_min, salary_max = parse_salary(salary_line)
    date_line = _find_date_line(raw_html)

    return {
        "id": _norm(card_id.group(1)) if card_id else None,
        "title": text_of(_QA_SELECTORS["title"]),
        "employer_name": text_of(_QA_SELECTORS["employer_name"]),
        "area_name": text_of(_QA_SELECTORS["area_name"]),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_text": _norm(salary_line),
        "published_at": parse_published(date_line),
        "experience": None,
        "snippet": None,
    }


def _find_date_line(html: str) -> str | None:
    """Строка с датой публикации в карточке (текст «N часов назад»)."""
    from selectolax.lexbor import LexborHTMLParser

    root = LexborHTMLParser(html).root
    for node in root.css("[class]"):
        t = _norm(node.text())
        if t and _DATE_RE.search(t):
            return t
    return None


# ── helpers для golden-тестов (tests/test_parser.py) ──────────────────────────


def golden_pairs() -> list[tuple[str, list[dict]]]:
    """(имя, golden-карточки) — фикстуры tests/fixtures в алфавитном порядке."""
    return [
        (p.stem, json.loads(p.with_suffix(".json").read_text()))
        for p in sorted(_FIXTURE_DIR.glob("*.html"))
    ]


def check_golden(json_path: Path) -> bool:
    """True, если golden JSON валиден как список CardDTO."""

    try:
        cards = json.loads(json_path.read_text())
        if not cards:
            return False
        return all(_card_valid(c) for c in cards)
    except Exception:
        return False


def _card_valid(card: dict) -> bool:
    from models import CardDTO

    try:
        CardDTO.model_validate(card)
        return True
    except Exception:
        return False
