"""Репозиторий вакансий: дедупликация, состояния, вердикты скоринга."""

from __future__ import annotations

from datetime import timedelta
from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Vacancy, VacancyState, utcnow
from src.domain.models import SearchTaskDTO, VacancyDTO, VacancyScore


class VacancyRepository:
    """Держит живые row-объекты в одной сессии; коммит делает session_scope."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Дедупликация / сохранение
    # ------------------------------------------------------------------

    async def get_by_hh_id(self, hh_vacancy_id: str) -> Vacancy | None:
        result = await self._session.execute(
            select(Vacancy).where(Vacancy.hh_vacancy_id == hh_vacancy_id)
        )
        return result.scalar_one_or_none()

    async def upsert_seen(
        self, dto: VacancyDTO, task: SearchTaskDTO | None = None
    ) -> tuple[Vacancy, bool]:
        """Идемпотентная запись: если вакансия уже есть — только bump last_seen.

        Возврат: (строка, создана_ли_впервые).
        """
        existing = await self.get_by_hh_id(dto.hh_vacancy_id)
        if existing is not None:
            existing.seen_count += 1
            existing.last_seen_at = utcnow()
            if existing.state is VacancyState.NEW and task is not None:
                existing.search_task = task.name
            return existing, False

        row = Vacancy(
            hh_vacancy_id=dto.hh_vacancy_id,
            title=dto.title,
            employer_id=dto.employer_id,
            employer_name=dto.employer_name,
            area=dto.area,
            url=dto.url,
            published_at=dto.published_at,
            salary_from=dto.salary.amount_from if dto.salary else None,
            salary_to=dto.salary.amount_to if dto.salary else None,
            salary_currency=dto.salary.currency if dto.salary else None,
            experience=dto.experience,
            employment=dto.employment,
            schedule=dto.schedule,
            work_formats=list(dto.work_formats),
            is_remote=dto.is_remote,
            snippet=dto.snippet,
            search_task=task.name if task else None,
            state=VacancyState.READY_TO_SCORE
            if dto.is_card_loaded
            else VacancyState.NEW,
        )
        if dto.is_card_loaded:
            row.description = dto.description
        self._session.add(row)
        await self._session.flush()
        return row, True

    async def save_full_card(self, dto: VacancyDTO) -> Vacancy | None:
        """Записывает полное описание после чтения карточки (см. hh_adapter)."""
        row = await self.get_by_hh_id(dto.hh_vacancy_id)
        if row is None:
            return None
        row.description = dto.description
        row.snippet = dto.snippet or row.snippet
        row.published_at = dto.published_at or row.published_at
        row.work_formats = list(dto.work_formats) or row.work_formats
        row.is_remote = row.is_remote or dto.is_remote
        if row.state is VacancyState.NEW:
            row.state = VacancyState.READY_TO_SCORE
        return row

    async def count_by_state(self, state: VacancyState) -> int:
        return await self._session.scalar(
            select(func.count()).select_from(Vacancy).where(Vacancy.state == state)
        ) or 0

    async def take_for_scoring(self, limit: int = 5) -> list[Vacancy]:
        """Пакет вакансий готовых к скорингу (FIFO по поступлению)."""
        result = await self._session.execute(
            select(Vacancy)
            .where(Vacancy.state == VacancyState.READY_TO_SCORE)
            .order_by(Vacancy.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Скоринг и письмо
    # ------------------------------------------------------------------

    async def mark_scored(
        self,
        vacancy_id: int,
        score: VacancyScore,
        skip_state: VacancyState = VacancyState.SKIPPED,
    ) -> Vacancy | None:
        """Сохранение вердикта. Отрицательное решение ведёт в SKIPPED."""
        row = await self._session.get(Vacancy, vacancy_id)
        if row is None:
            return None
        row.score = score.score
        row.verdict = score.verdict.value
        row.match_reasons = list(score.match_reasons)
        row.red_flags = list(score.red_flags)
        row.score_summary = score.summary
        row.scored_at = utcnow()
        if score.verdict.value == "skip":
            row.state = skip_state
        else:
            row.state = VacancyState.SCORED
        return row

    async def save_letter(self, vacancy_id: int, letter: str) -> Vacancy | None:
        row = await self._session.get(Vacancy, vacancy_id)
        if row is None:
            return None
        row.letter = letter
        row.letter_generated_at = utcnow()
        return row

    async def take_ready_for_notification(self) -> list[Vacancy]:
        """Оценённые высоко вакансии с готовым письмом, ещё не отправленные в TG."""
        result = await self._session.execute(
            select(Vacancy).where(Vacancy.state == VacancyState.SCORED)
        )
        rows = list(result.scalars().all())
        return [row for row in rows if row.letter]

    async def mark_notified(self, vacancy_id: int) -> Vacancy | None:
        row = await self._session.get(Vacancy, vacancy_id)
        if row is None:
            return None
        row.state = VacancyState.NOTIFIED
        row.notified_at = utcnow()
        return row

    async def mark_applied(self, vacancy_id: int) -> Vacancy | None:
        row = await self._session.get(Vacancy, vacancy_id)
        if row is None:
            return None
        row.state = VacancyState.APPLIED
        return row

    async def mark_state(self, vacancy_id: int, state: VacancyState) -> Vacancy | None:
        """Общий переход состояния (например, повторное чтение карточки)."""
        row = await self._session.get(Vacancy, vacancy_id)
        if row is None:
            return None
        row.state = state
        return row

    async def blacklist_sweep(self, blocked_employer_ids: set[str]) -> int:
        """Однократный запрос: все необработанные вакансии забаненных компаний -> SKIPPED."""
        if not blocked_employer_ids:
            return 0
        result = cast(
            "CursorResult[None]",
            await self._session.execute(
                update(Vacancy)
                .where(
                    Vacancy.employer_id.in_(blocked_employer_ids),
                    Vacancy.state.in_(
                        [VacancyState.NEW, VacancyState.READY_TO_SCORE, VacancyState.SCORED]
                    ),
                )
                .values(state=VacancyState.SKIPPED, verdict="skip")
            ),
        )
        return int(result.rowcount) if result.rowcount is not None else 0

    async def list_untouched_older_than(self, hours: int) -> list[Vacancy]:
        """Вакансии, застрявшие в NEW (карточку не прочитали) дольше N часов."""
        border = utcnow() - timedelta(hours=hours)
        result = await self._session.execute(
            select(Vacancy).where(
                Vacancy.state == VacancyState.NEW,
                Vacancy.last_seen_at < border,
            )
        )
        return list(result.scalars().all())
