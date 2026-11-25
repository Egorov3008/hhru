"""Golden-пары: HTML выдачи hh.ru → ожидающий JSON-контракт.

Файлы обновляет tools/update_fixtures.py. Markup hh.ru меняется —
парсер обязан давать те же значения, что в день снятия фикстуры.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent


def _norm(value) -> str | None:
    """Нормализация пробелов (узкий/неразрывный в текстах hh.ru)."""
    if value is None:
        return None
    return re.sub(r"[\s ]+", " ", str(value)).strip() or None


def check_golden(json_path: Path) -> bool:
    """True, если golden JSON валиден как список CardDTO (Шаг 2)."""
    try:
        cards = json.loads(json_path.read_text())
        return bool(cards)
    except Exception:
        return False
