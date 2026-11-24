"""Тестовые фабрики DTO (без внешних зависимостей типа factory_boy)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.domain.models import SalaryDTO, SearchTaskDTO, VacancyDTO


def make_vacancy_dto(
    hh_vacancy_id: str = "100500", **overrides: object
) -> VacancyDTO:
    payload: dict[str, object] = {
        "hh_vacancy_id": hh_vacancy_id,
        "title": "Senior Python Backend",
        "employer_id": "777",
        "employer_name": "OOO Tech Co",
        "area": "Москва",
        "url": f"https://hh.ru/vacancy/{hh_vacancy_id}",
        "published_at": datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
        "salary": SalaryDTO(amount_from=280000, amount_to=400000),
        "experience": "between3And6",
        "is_remote": True,
        "snippet": "Python, asyncio, FastAPI",
        "search_task": "python-backend",
    }
    payload.update(overrides)
    return VacancyDTO.model_validate(payload)


def make_task(name: str = "python-backend") -> SearchTaskDTO:
    return SearchTaskDTO(name=name, query="Python backend", area_id="1")
