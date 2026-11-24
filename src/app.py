"""CLI точки входа уровня приложения.

Команды:
  python -m src.app init-db   — миграции до head через Alembic
  python -m src.app check     — самопроверка окружения (конфиг, фильтры, резюме, миграции)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from src.config import get_settings
from src.logging_setup import setup_logging


async def init_db() -> int:
    """Прогон миграций до head. SQLite создаст runtime/ папку сам."""
    from alembic import command
    from alembic.config import Config

    settings = get_settings()
    settings.ensure_dirs()
    alembic_cfg = Config(str(Path("alembic.ini")))
    alembic_cfg.set_main_option("script_location", "migrations")

    def _upgrade() -> None:
        command.upgrade(alembic_cfg, "head")

    await asyncio.to_thread(_upgrade)
    return 0


async def check() -> int:
    """Верифицирует окружение: без отправки чего-либо наружу."""
    from sqlalchemy import text

    from src.db.base import create_engine
    from src.domain.filters_config import FiltersConfig, load_filters

    settings = get_settings()
    problems: list[str] = []

    filters_path = Path(settings.scoring.filters_path)
    resume_path = Path(settings.scoring.resume_path)

    # Блокирующий IO файлов -> в поток (ASYNC240)
    def _read_files() -> tuple[FiltersConfig | Exception, bool]:
        try:
            return load_filters(filters_path), True
        except (FileNotFoundError, ValueError, TypeError) as exc:
            return exc, resume_path.is_file() and resume_path.stat().st_size > 200

    filters, resume_ok = await asyncio.to_thread(_read_files)
    if isinstance(filters, Exception):
        problems.append(f"filters.yaml: {filters}")
    else:
        print(f"[ok]   filters.yaml: {len(filters.searches)} поисковых запрос(а)"
              f", threshold={filters.scoring.score_threshold}")

    if resume_ok:
        print("[ok]   resume.md найден")
    else:
        problems.append(f"resume.md не найден или выглядит пустым: {resume_path}")

    if settings.db.is_sqlite:
        print("[ok]   БД: sqlite (файл в HHSH_DB__URL)")
    else:
        print("[ok]   БД: postgresql-совместимый URL")

    if settings.llm.api_key.get_secret_value():
        print(f"[ok]   LLM: {settings.llm.model} @ {settings.llm.base_url}")
    else:
        problems.append("HHSH_LLM__API_KEY пуст — скоринг и письма не заработают")

    if settings.telegram.is_configured():
        print("[ok]   Telegram бот настроен")
    else:
        problems.append("HHSH_TELEGRAM__BOT_TOKEN / HHSH_TELEGRAM__CHAT_ID не заданы")

    print(f"[info] hh-адаптер: {'MOCK' if settings.hh.mock else 'x-cli: ' + settings.hh.cli_bin}"
          f" (timeout={settings.hh.command_timeout_seconds}s, conc={settings.hh.max_concurrency})")

    # Доступ к БД: реально открываем соединение
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        print("[ok]   БД доступна")
    finally:
        await engine.dispose()

    if problems:
        print("\n[bad] Проблемы конфигурации:")
        for problem in problems:
            print(f"      - {problem}")
        return 1
    print("\n[ok]   Окружение готово к Шагу 2 (адаптер + скоринг)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="hh-sh", description="hh-smart-hunter CLI")
    parser.add_argument(
        "command", choices=["init-db", "check"], help="init-db: миграции; check: самопроверка"
    )
    args = parser.parse_args()

    setup_logging(get_settings().app.log_level, json_output=False)

    if args.command == "init-db":
        return asyncio.run(init_db())
    return asyncio.run(check())


if __name__ == "__main__":
    sys.exit(main())
