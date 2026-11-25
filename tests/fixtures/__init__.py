"""Golden-пары: HTML выдачи hh.ru → ожидающий JSON-контракт (Шаг 2, Task 3).

Файлы обновляет tools/update_fixtures.py. Markup hh.ru меняется —
парсер обязан давать те же значения, что в день снятия фикстуры.
`check_golden` валидирует golden JSON как список CardDTO; `norm`
сворачивает узкие/неразрывные пробелы hh.ru к обычным.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent

# узкий/неразрывный пробел в текстах hh.ru → обычный
_NORM_RE = re.compile(r"[\s ]+")


def norm(value) -> str | None:
    return None if value is None else (_NORM_RE.sub(" ", str(value)).strip() or None)


def check_golden(json_path: Path) -> bool:
    """True, если golden JSON валиден как список CardDTO."""
    from models import CardDTO

    try:
        cards = json.loads(json_path.read_text())
        return bool(cards) and all(CardDTO.model_validate(c) for c in cards)
    except Exception:
        return False
