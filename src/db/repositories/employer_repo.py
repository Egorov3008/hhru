"""Репозиторий чёрного списка работодателей."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import EmployerBlacklist


class EmployerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, hh_employer_id: str) -> EmployerBlacklist | None:
        result = await self._session.execute(
            select(EmployerBlacklist).where(
                EmployerBlacklist.hh_employer_id == hh_employer_id
            )
        )
        return result.scalar_one_or_none()

    async def is_blacklisted(self, hh_employer_id: str) -> bool:
        return await self.get(hh_employer_id) is not None

    async def all_banned_ids(self) -> set[str]:
        result = await self._session.execute(select(EmployerBlacklist.hh_employer_id))
        return {row for (row,) in result.all()}

    async def add(
        self, hh_employer_id: str, name: str, reason: str | None = None
    ) -> EmployerBlacklist:
        """Идемпотентный бан: повторный вызов обновляет причину, а не падает."""
        existing = await self.get(hh_employer_id)
        if existing is not None:
            if reason:
                existing.reason = reason
            if name:
                existing.name = name
            return existing
        row = EmployerBlacklist(hh_employer_id=hh_employer_id, name=name, reason=reason)
        self._session.add(row)
        await self._session.flush()
        return row

    async def remove(self, hh_employer_id: str) -> bool:
        row = await self.get(hh_employer_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True
