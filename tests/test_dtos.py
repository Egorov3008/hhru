"""Проверки доменных DTO: границы LLM-вывода и контракт адаптера."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from src.domain.models import (
    ApplicationState,
    ApplyResultDTO,
    CoverLetterDTO,
    SalaryDTO,
    VacancyCard,
    VacancyDTO,
    VacancyScore,
    Verdict,
)


def _vacancy(**overrides: object) -> VacancyDTO:
    payload: dict[str, object] = {
        "hh_vacancy_id": "12345",
        "title": "Senior Python Backend",
        "employer_id": "999",
        "employer_name": "OOO Tech",
        "published_at": datetime(2026, 11, 24, 12, 0, tzinfo=UTC),
        "description": "Ищем Python разработчика в команду платежей. asyncio, FastAPI.",
    }
    payload.update(overrides)
    return VacancyDTO.model_validate(payload)


class TestSalaryDTO:
    def test_range_must_not_be_inverted(self) -> None:
        with pytest.raises(ValidationError):
            SalaryDTO(amount_from=300000, amount_to=200000)

    def test_display_for_unset_salary(self) -> None:
        assert SalaryDTO().display() == "не указана"

    def test_display_with_both_sides(self) -> None:
        salary = SalaryDTO(amount_from=250000, amount_to=350000)
        assert salary.display() == "от 250000 до 350000 RUR"


class TestVacancyDTO:
    def test_empty_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _vacancy(hh_vacancy_id="  ")

    def test_is_card_loaded_needs_description(self) -> None:
        assert _vacancy().is_card_loaded is True
        assert _vacancy(description="   ").is_card_loaded is False
        assert _vacancy(description=None).is_card_loaded is False

    def test_has_keyword_case_insensitive(self) -> None:
        dto = _vacancy()
        assert dto.has_keyword("fastapi") is True
        assert dto.has_keyword("bitrix") is False

    def test_negative_salary_ok_if_in_range(self) -> None:
        assert VacancyDTO.model_validate(_vacancy(salary={"amount_from": 0, "amount_to": 100}))


class TestVacancyScore:
    def test_valid_high_score(self) -> None:
        score = VacancyScore.model_validate(
            {
                "score": 9,
                "verdict": "apply",
                "match_reasons": ["5 лет asyncio", "опыт FastAPI"],
                "red_flags": ["оформление как ИП"],
            }
        )
        assert score.verdict is Verdict.APPLY

    def test_score_bounds(self) -> None:
        for bad in (0, 11):
            with pytest.raises(ValidationError):
                VacancyScore.model_validate({"score": bad, "verdict": "skip"})

    def test_high_score_requires_reasons(self) -> None:
        with pytest.raises(ValidationError, match="требует хотя бы одной причины"):
            VacancyScore.model_validate({"score": 9, "verdict": "apply"})

    def test_three_red_flags_cannot_apply(self) -> None:
        with pytest.raises(ValidationError, match="несовместимы"):
            VacancyScore.model_validate(
                {
                    "score": 8,
                    "verdict": "apply",
                    "match_reasons": ["совпадение стека"],
                    "red_flags": ["флаг один", "флаг два", "флаг три"],
                }
            )

    def test_verdict_must_be_from_enum(self) -> None:
        with pytest.raises(ValidationError):
            VacancyScore.model_validate({"score": 6, "verdict": "maybe"})

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            VacancyScore.model_validate({"score": 6, "verdict": "skip", "surprise": True})


class TestCoverLetterDTO:
    def test_too_short_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least 120"):
            CoverLetterDTO(letter="коротко")

    def test_char_count(self) -> None:
        letter = CoverLetterDTO(letter="z" * 130, pain_point_refs=["p99 латентность"])
        assert letter.char_count == 130


class TestApplyAndCard:
    def test_failed_factory(self) -> None:
        result = ApplyResultDTO.failed("100500", "нет отклика в кнопке")
        assert result.ok is False
        assert result.hh_application_id is None

    def test_card_actionable(self) -> None:
        vacancy = _vacancy()
        score = VacancyScore.model_validate(
            {"score": 8, "verdict": "apply", "match_reasons": ["совпадение"]}
        )
        card = VacancyCard(vacancy=vacancy, score=score)
        assert card.is_actionable is False  # письма нет
        assert VacancyCard(
            vacancy=vacancy, score=score, letter=CoverLetterDTO(letter="x" * 140)
        ).is_actionable is True

    def test_application_state_values(self) -> None:
        assert ApplicationState("invited") is ApplicationState.INVITED
