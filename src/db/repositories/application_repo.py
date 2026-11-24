"""Репозиторий откликов: создание, статус-трекинг, пакет для фоновой сверки."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Application, ApplicationStatus, Vacancy, utcnow
from src.domain.models import ApplicationState


class ApplicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        vacancy_id: int,
        letter: str,
        resume_id: int | None = None,
        hh_application_id: str | None = None,
    ) -> Application:
        """Отклик создан и уходит в статус SENT (или ERROR, если адаптер вернул сбой)."""
        row = Application(
            vacancy_id=vacancy_id,
            resume_id=resume_id,
            letter=letter,
            hh_application_id=hh_application_id,
            status=ApplicationStatus.SENT,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_by_hh_application_id(self, hh_application_id: str) -> Application | None:
        result = await self._session.execute(
            select(Application).where(Application.hh_application_id == hh_application_id)
        )
        return result.scalar_one_or_none()

    async def get_with_vacancy(self, application_id: int) -> Application | None:
        result = await self._session.execute(
            select(Application)
            .options(selectinload(Application.vacancy))
            .where(Application.id == application_id)
        )
        return result.scalar_one_or_none()

    async def take_for_status_check(
        self, limit: int = 20, older_than_minutes: int = 0
    ) -> list[Application]:
        """Отклики в живых статусах, дожидающиеся сверки (SENT/SEEN)."""
        border = utcnow() - timedelta(minutes=older_than_minutes)
        result = await self._session.execute(
            select(Application)
            .options(selectinload(Application.vacancy))
            .where(
                Application.status.in_([ApplicationStatus.SENT, ApplicationStatus.SEEN]),
                or_(Application.last_checked_at.is_(None), Application.last_checked_at < border),
            )
            .order_by(Application.applied_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def set_status(
        self,
        application_id: int,
        state: ApplicationState,
        comment: str | None = None,
        changed_at: datetime | None = None,
    ) -> Application | None:
        """Обновление статуса.

        ERROR не перезатирает известный статус: сверка ещё раз вернёт правду,
        а сбой адаптера не должен «сбрасывать» приглашение или отказ.
        """
        row = await self._session.get(Application, application_id)
        if row is None:
            return None
        if state is ApplicationState.ERROR:
            row.last_checked_at = utcnow()
            if comment:
                row.status_comment = comment
            return row
        row.status = ApplicationStatus(state.value)
        row.last_checked_at = utcnow()
        if comment:
            row.status_comment = comment
        row.status_changed_at = changed_at if isinstance(changed_at, datetime) else utcnow()
        return row

    async def mark_dossier_sent(self, application_id: int) -> Application | None:
        row = await self._session.get(Application, application_id)
        if row is None:
            return None
        row.dossier_sent_at = utcnow()
        return row

    async def list_by_status(self, state: ApplicationState) -> list[Application]:
        result = await self._session.execute(
            select(Application)
            .options(selectinload(Application.vacancy))
            .where(Application.status == ApplicationStatus(state.value))
            .order_by(Application.applied_at)
        )
        return list(result.scalars().all())

    async def list_all_with_vacancies(self, limit: int = 50) -> list[tuple[Application, Vacancy]]:
        result = await self._session.execute(
            select(Application, Vacancy)
            .join(Vacancy, Application.vacancy_id == Vacancy.id)
            .order_by(Application.applied_at.desc())
            .limit(limit)
        )
        return list(result.all())
