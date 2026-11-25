"""Pydantic-модели ответа hh-agent (Шаг 2, Task 1).

hh-agent отвечает на `POST /call` объектом `SearchResponse` со списком
`CardDTO`. Имена и типы полей совпадают с `VacancyDTO` из
`src/domain/models.py` (Шаг 1): golden-пары и живой smoke сверяют
именно эти поля.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator


class CardDTO(BaseModel):
    """Карточка вакансии из выдачи hh.ru (golden-контракт).

    Соответствует полям VacancyDTO: area → area_name, salary →
    salary_min/salary_max. published_at — timezone-aware UTC
    (hh.ru отдаёт Europe/Moscow, конвертируем здесь).
    """

    id: str
    title: str
    employer_name: str
    area_name: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_text: str | None = None
    experience: str | None = None
    published_at: datetime | None = None
    snippet: str | None = None

    @field_validator("published_at")
    @classmethod
    def _utc_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("published_at должен быть timezone-aware (UTC)")
        return value

    @field_validator("id")
    @classmethod
    def _id_non_empty(cls, value: str) -> str:
        """Карточка без id не проходит golden-контракт."""
        value = value.strip()
        if not value:
            raise ValueError("id не может быть пустой строкой")
        return value


class SearchArgs(BaseModel):
    """Тело запроса /call для cmd=search."""

    cmd: str = "search"
    query: str
    area: str = "1"
    limit: int = 50
    page: int = 0


class SearchResponse(BaseModel):
    """Ответ hh-agent на cmd=search."""

    ok: bool = True
    data: list[CardDTO]
    error: str | None = None
