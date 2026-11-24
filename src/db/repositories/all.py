from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories.application_repo import ApplicationRepository
from src.db.repositories.employer_repo import EmployerRepository
from src.db.repositories.resume_repo import ResumeRepository
from src.db.repositories.vacancy_repo import VacancyRepository


@dataclass(slots=True)
class Repositories:
    """Единственный объект-вход для сервисов: session + все репозитории."""

    session: AsyncSession
    vacancies: VacancyRepository
    employers: EmployerRepository
    applications: ApplicationRepository
    resumes: ResumeRepository

    @classmethod
    def make(cls, session: AsyncSession) -> Repositories:
        return cls(
            session=session,
            vacancies=VacancyRepository(session),
            employers=EmployerRepository(session),
            applications=ApplicationRepository(session),
            resumes=ResumeRepository(session),
        )


__all__ = [
    "ApplicationRepository",
    "EmployerRepository",
    "Repositories",
    "ResumeRepository",
    "VacancyRepository",
]
