"""Тесты hh_adapter (Шаг 2, Task 2).

Golden-контракт: парсер на сохранённых HTML-фикстурах должен давать то
же, что golden JSON. Живой webbridge в CI не нужен. Недоступный агент →
HHAdapterError.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "tools" / "hh-agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from src.config import Settings  # noqa: E402
from src.services.hh_adapter import (  # noqa: E402
    HhAdapter,
    HHAdapterError,
    MockHhAdapter,
    make_adapter,
)

_FIXTURE_DIR = _ROOT / "tests" / "fixtures"


def _norm(value) -> str | None:
    """Нормализация пробелов (узкий/неразрывный в текстах hh.ru)."""
    if value is None:
        return None
    return re.sub(r"[\s ]+", " ", str(value)).strip() or None


def _check_golden(json_path: Path) -> bool:
    """True, если golden JSON валиден как список CardDTO (Шаг 2)."""

    try:
        cards = json.loads(json_path.read_text())
        return bool(cards) and all(
            _card_valid(c) for c in cards  # type: ignore[arg-type]
        )
    except Exception:
        return False


def _card_valid(card: dict) -> bool:
    from models import CardDTO

    try:
        CardDTO.model_validate(card)
        return True
    except Exception:
        return False


class TestMockAdapter:
    async def test_mock_returns_contract(self) -> None:
        adapter = make_adapter(Settings(hh__mock=True))
        assert isinstance(adapter, MockHhAdapter)
        cards = await adapter.search("python", area="1")
        assert isinstance(cards, list)

    async def test_mock_apply_and_bump(self) -> None:
        adapter = make_adapter(Settings(hh__mock=True))
        assert (await adapter.apply("123456789", "письмо"))["ok"] is True
        assert (await adapter.bump("resume-1"))["bumped"] is True


class TestGoldenContract:
    """Golden JSON — контракт, который hh-agent отдаёт на /call."""

    @pytest.mark.skipif(not list(_FIXTURE_DIR.glob("*.json")), reason="golden-фикстуры не сняты")
    @pytest.mark.parametrize(
        "fixture",
        sorted(_FIXTURE_DIR.glob("*.json")) if _FIXTURE_DIR.exists() else [],
    )
    def test_golden_json_parses_as_card_dto(self, fixture: Path) -> None:
        assert _check_golden(fixture), f"golden {fixture.name} не проходит контракт"

    def test_golden_html_parses_to_golden_json(self) -> None:
        """Парсер на фикстурах → те же значения, что в golden JSON."""
        from parser import parse_search_html

        for html_path in sorted(_FIXTURE_DIR.glob("*.html")):
            golden = json.loads(html_path.with_suffix(".json").read_text())
            parsed = parse_search_html(html_path.read_text())
            assert len(parsed) >= 5, f"{html_path.name}: карточек меньше 5"
            for i, (got, want) in enumerate(zip(parsed[:5], golden[:5], strict=True)):
                for field in ("id", "title", "employer_name", "area_name"):
                    assert _norm(got[field]) == _norm(want[field]), (
                        f"{html_path.name} карточка {i} поле {field}: "
                        f"{got[field]!r} != {want[field]!r}"
                    )

    def test_unreachable_agent_raises(self) -> None:
        settings = Settings(hh__mock=False, hh__agent_endpoint="http://127.0.0.1:1")
        adapter = HhAdapter(settings)
        with pytest.raises((HHAdapterError, OSError)):
            asyncio.run(adapter.search("python"))  # connection refused
