"""Движок и session factory (async).

SQLite — для MVP, PostgreSQL — через смену DATABASE_URL: бизнес-код работает
только со сессиями, диалект не протекает.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import Settings, get_settings
from src.db.models import Base as Metadata  # noqa: F401 — реэкспорт для alembic


def create_engine(settings: Settings) -> AsyncEngine:
    engine = create_async_engine(
        settings.db.url,
        echo=settings.db.echo_sql,
        pool_pre_ping=True,
    )

    if settings.db.is_sqlite:
        # 1) foreign_keys по умолчанию выключены в SQLite — включаем на каждой сессии;
        # 2) WAL для конкурентных читателей (бот + планировщик в одном процессе).
        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # autoflush=True (дефолт SQLAlchemy): репозитории смешивают мутации и
    # SELECT-ы — автопрочистка делает изменение видимым для последующих запросов
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Unit-of-work: коммит при успехе, rollback + проброс ошибки при сбое."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all(engine: AsyncEngine) -> None:
    """Схема из ORM-моделей — удобный MVP-путь; миграции — через Alembic."""
    from src.db.models import Base  # локальный импорт: избегаем цикла

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def build_default_factory() -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий из конфигурации окружения (для бота и планировщика)."""
    settings = get_settings()
    return create_session_factory(create_engine(settings))
