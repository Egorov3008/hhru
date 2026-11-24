"""Общие фикстуры: in-memory SQLite с живой ORM-схемой."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from src.db.base import create_all
from src.db.repositories.all import Repositories


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    await create_all(engine)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def repos(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Repositories]:
    """Коммитится автоматически — как в проде через session_scope."""
    async with session_factory() as session:
        repositories = Repositories.make(session)
        yield repositories
        await session.commit()
