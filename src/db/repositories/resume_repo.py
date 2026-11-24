"""Репозиторий резюме: реестр для автоподнятия."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Resume, utcnow
from src.domain.models import ResumeDTO


class ResumeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_hh_id(self, hh_resume_id: str) -> Resume | None:
        result = await self._session.execute(
            select(Resume).where(Resume.hh_resume_id == hh_resume_id)
        )
        return result.scalar_one_or_none()

    async def upsert(self, dto: ResumeDTO, *, auto_boost: bool | None = None) -> Resume:
        existing = await self.get_by_hh_id(dto.hh_resume_id)
        if existing is not None:
            existing.title = dto.title
            existing.is_auto_boost = (
                existing.is_auto_boost if auto_boost is None else auto_boost
            )
            return existing
        row = Resume(
            hh_resume_id=dto.hh_resume_id,
            title=dto.title,
            is_auto_boost=bool(auto_boost) and dto.can_boost,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_boostable(self) -> list[Resume]:
        result = await self._session.execute(
            select(Resume).where(Resume.is_auto_boost.is_(True)).order_by(Resume.id)
        )
        return list(result.scalars().all())

    async def mark_boosted(self, resume_id: int) -> Resume | None:
        row = await self._session.get(Resume, resume_id)
        if row is None:
            return None
        row.last_boosted_at = utcnow()
        row.total_boosts += 1
        return row
