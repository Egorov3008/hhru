"""Общие фикстуры и sys.path-вставки для тестов.

tools/hh-agent — пакет с дефисом: обычный импорт невозможен,
поэтому sys.path настраивается до импорта parser.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# sys.path-вставка до импорта src и tools/hh-agent
for _p in (_ROOT, _ROOT / "tools" / "hh-agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402
from src.db.base import create_all  # noqa: E402
from src.db.repositories.all import Repositories  # noqa: E402


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
