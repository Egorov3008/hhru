"""Доменные модели — транспортный контракт между слоями.

Бизнес-логика (дедупликация, скоринг, письма, бот) знает только эти Pydantic
модели. Как именно они были получены — живым CLI `x-cli` или mock-адаптером —
бизнес-логике неважно.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Базовый класс: только известные поля, строгая валидация (для LLM-вывода)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ---------------------------------------------------------------------------
# Вакансия
# ---------------------------------------------------------------------------


class SalaryDTO(BaseModel):
    """Зарплатная вилка. amount_from/amount_to = None, если hh.ru не раскрыл вилку."""

    amount_from: int | None = None
    amount_to: int | None = None
    currency: str | None = "RUR"

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if (
            self.amount_from is not None
            and self.amount_to is not None
            and self.amount_from > self.amount_to
        ):
            msg = f"salary_from ({self.amount_from}) > salary_to ({self.amount_to})"
            raise ValueError(msg)
        return self

    def display(self) -> str:
        if self.amount_from is None and self.amount_to is None:
            return "не указана"
        left = f"от {self.amount_from}" if self.amount_from is not None else None
        right = f"до {self.amount_to}" if self.amount_to is not None else None
        body = " ".join(x for x in (left, right) if x)
        return f"{body} {self.currency or ''}".strip()


class VacancyDTO(BaseModel):
    """Вакансия, как её возвращает адаптер (из выдачи или полной карточки).

    `is_card_loaded` отличает запись из ленты поиска (краткая) от полного
    чтения описания через адаптер — скоринг требует полной карточки.
    """

    hh_vacancy_id: str
    title: str
    employer_id: str
    employer_name: str
    area: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    salary: SalaryDTO | None = None
    experience: str | None = None
    employment: str | None = None
    schedule: str | None = None
    work_formats: list[str] = Field(default_factory=list)
    is_remote: bool = False
    snippet: str | None = None
    description: str | None = None
    # Какой поисковый запрос из filters.yaml нашёл вакансию
    search_task: str | None = None
    # Сырой словарь из адаптера (для повторного парсинга / отладки)
    raw: dict[str, Any] | None = None

    @field_validator("hh_vacancy_id", "employer_id")
    @classmethod
    def _id_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            msg = "hh_vacancy_id/employer_id не может быть пустой строкой"
            raise ValueError(msg)
        return value

    @property
    def is_card_loaded(self) -> bool:
        return bool(self.description and self.description.strip())

    def has_keyword(self, *keywords: str) -> bool:
        """Регистронезависимый поиск подстроки по названию и описанию."""
        haystack = " ".join(
            part
            for part in (
                self.title,
                self.snippet,
                self.description,
                self.employer_name,
                " ".join(self.work_formats),
            )
            if part
        ).lower()
        return any(kw.lower() in haystack for kw in keywords)


class SearchTaskDTO(BaseModel):
    """Один поисковый запрос из config/filters.yaml, передаваемый адаптеру."""

    name: str
    query: str
    area_id: str | None = None
    experience: str | None = None
    employment: str | None = None
    schedule: str | None = None
    exclude_words: list[str] = Field(default_factory=list)
    # Период опроса x-cli (в поисковых командах hh.ru)
    search_period_days: int = 1


# ---------------------------------------------------------------------------
# Скоринг LLM
# ---------------------------------------------------------------------------


class Verdict(StrEnum):
    APPLY = "apply"
    SKIP = "skip"


class VacancyScore(StrictModel):
    """Строгий JSON-ответ LLM после сопоставления вакансии с резюме."""

    score: int = Field(ge=1, le=10)
    verdict: Verdict
    match_reasons: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    summary: str | None = None

    @field_validator("match_reasons")
    @classmethod
    def _reasons_length(cls, value: list[str]) -> list[str]:
        return [line.strip() for line in value if line.strip()][:5]

    @field_validator("red_flags")
    @classmethod
    def _flags_length(cls, value: list[str]) -> list[str]:
        return [line.strip() for line in value if line.strip()][:10]

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        # 9–10 без причины — признак галлюцинации; 3+ красных флага не дают "apply"
        if self.score >= 9 and not self.match_reasons:
            msg = "score >= 9 требует хотя бы одной причины (match_reasons)"
            raise ValueError(msg)
        if len(self.red_flags) >= 3 and self.verdict is Verdict.APPLY:
            msg = "3+ red_flags несовместимы с verdict=apply"
            raise ValueError(msg)
        return self


# ---------------------------------------------------------------------------
# Сопроводительное письмо
# ---------------------------------------------------------------------------


class CoverLetterDTO(StrictModel):
    """Письмо, сгенерированное по болям вакансии + кейсам из резюме."""

    letter: str = Field(min_length=120, max_length=4000)
    pain_point_refs: list[str] = Field(default_factory=list)

    @field_validator("letter")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @property
    def char_count(self) -> int:
        return len(self.letter)


# ---------------------------------------------------------------------------
# Отклик и трекинг статусов
# ---------------------------------------------------------------------------


class ApplicationState(StrEnum):
    SENT = "sent"            # отклик отправлен, hh.ru ещё не отметил
    SEEN = "seen"            # просмотрено рекрутером
    INVITED = "invited"      # приглашение на интервью
    DECLINED = "declined"    # отказ работодателя
    ERROR = "error"          # адаптер не смог определить/ошибка отправки


class ApplyResultDTO(BaseModel):
    """Результат нажатия «Откликнуться» через x-cli."""

    ok: bool
    hh_vacancy_id: str
    hh_application_id: str | None = None
    message: str | None = None

    @classmethod
    def failed(cls, hh_vacancy_id: str, message: str) -> Self:
        return cls(ok=False, hh_vacancy_id=hh_vacancy_id, message=message)


class ApplicationStatusDTO(BaseModel):
    """Снимок статуса одного отклика (фоновая сверка)."""

    hh_vacancy_id: str | None = None
    hh_application_id: str | None = None
    status: ApplicationState
    status_changed_at: datetime | None = None
    comment: str | None = None


# ---------------------------------------------------------------------------
# Резюме и карточка для Telegram
# ---------------------------------------------------------------------------


class ResumeDTO(BaseModel):
    hh_resume_id: str
    title: str
    can_boost: bool = True


class VacancyCard(BaseModel):
    """Собранная бизнес-единица для карточки в Telegram.

    Не транспорт адаптера: собирается сервисным слоем после скоринга и
    генерации письма.
    """

    vacancy: VacancyDTO
    score: VacancyScore
    letter: CoverLetterDTO | None = None
    application_id: int | None = None

    @property
    def is_actionable(self) -> bool:
        """«Откликнуться» доступен, если всё поле готово."""
        return self.letter is not None and self.score.verdict is Verdict.APPLY
