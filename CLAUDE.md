# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Проект

**hh-smart-hunter** — автоматизация поиска работы на hh.ru: сбор вакансий по
запросам, LLM-скоринг против резюме, генерация сопроводительных писем,
human-in-the-loop подтверждение откликов в Telegram. Спроектирован как один
долгоживущий процесс (бот + планировщик в одном контейнере).

Реализован **Шаг 1** (каркас: DTO, схема БД, репозитории, конфиг — см. коммит
`Шаг 1`). Папки `src/services/`, `src/bot/`, `src/scheduler/`, `src/main.py`,
`prompts/`, а также `src/app run` **ещё не существуют** — они заложены в
архитектуре README.md как следующие шаги. Не считай их автоматически
готовыми.

## Команды

```bash
cp .env.example .env                                  # секреты и пути
uv venv --python 3.12 && uv pip install -e ".[dev]"    # установка с dev-зависимостями
.venv/bin/python -m src.app init-db                 # миграции Alembic (создаёт runtime/)
.venv/bin/python -m src.app check                   # самопроверка окружения
.venv/bin/python -m pytest tests/ -q                # тесты (asyncio_mode=auto)
.venv/bin/python -m pytest tests/test_repositories.py::TestVacancyDedup -q   # одна группа
.venv/bin/python -m ruff check src tests            # линтер (E,F,W,I,N,UP,B,ASYNC,SIM)
.venv/bin/python -m mypy src                        # strict-мypy
docker compose up -d                                # prod-режим (x-cli read-only volume)
```

Нужен реальный режим (не MOCK): `HHSH_HH__MOCK=false`, x-cli в `./_xcli`.

## Архитектура — ключевые договорённости

Данные текут строго в одну сторону: **hh.ru → адаптер → DTO → репозитории → БД**,
а сервисный слой собирает из DTO карточки для Telegram.

| Слой | Файлы | Роль |
|---|---|---|
| Конфиг | `src/config.py` | `Settings` из pydantic-settings; префикс `HHSH_`, вложенность через `__`. `get_settings()` — `lru_cache`-синглтон, в тестах сбрасывать `cache_clear()`. |
| Конфиг фильтров | `src/domain/filters_config.py` | Типизированный взгляд на `config/filters.yaml` (запросы, лимиты, red-flag-подсказки). |
| DTO | `src/domain/models.py` | Единственный контракт между слоями: `VacancyDTO`, `SearchTaskDTO`, `VacancyScore`, `CoverLetterDTO`, `ApplyResultDTO`, `VacancyCard`. Всё, что приходит от LLM, — на базе `StrictModel` (`extra="forbid"`). |
| БД | `src/db/models.py`, `src/db/base.py` | SQLAlchemy 2.0 async + Alembic. SQLite (WAL) по умолчанию, PostgreSQL — сменой `HHSH_DB__URL`, код не меняется. `session_scope` = unit-of-work. |
| Репозитории | `src/db/repositories/` | Один объект-вход `Repositories.make(session)`; агрегатор `all.py`. |
| Готовые шаги 2–3 | `src/services/`, `src/bot/`, `src/scheduler/`, `src/main.py` | Ещё не написаны. |

Правила, из-за которых правки должны выглядеть одинаково с остальным кодом:

- **hh.ru доступен только через CLI `x-cli`** (`src/services/hh_adapter.py`), не
  через HTTP API. Бизнес-слой не должен знать про сайт: парсинг stdout и
  лимиты живут в адаптере. `HHSH_HH__MOCK=true` — весь пайплайн работает без
  аккаунта.
- **Дедупликация, а не отклик по расписанию**: `hh_vacancy_id` уникален,
  `seen_count`/`last_seen_at` считаются при повторном попадании в выдачу;
  `state` (`VacancyState`) — конечный автомат новой вакансии (`NEW →
  READY_TO_SCORE → SCORED → NOTIFIED → APPLIED`, либо `SKIPPED`).
- **Жёсткие фильтры до LLM** (`limits` в `filters.yaml`: возраст вакансии,
  минимальная зарплата, стоп-слова, чёрный список работодателей), семантика —
  после. Так экономятся токены.
- **LLM отвечает строгим JSON** и проходит `VacancyScore`-валидацию; модель
  не имеет права «договаривать»: `score >= 9` требует причин, 3+ `red_flags`
  запрещают `apply`.
- Числовые id hh.ru храним как **строки**.
- Эпоха/таймзоны: `timezone-aware UTC` (`utcnow()` в `src/db/models.py`),
  `Europe/Moscow` — только для расписания.

## Конвенции

- Python 3.12+, async-first (`asyncio`, `aiosqlite`); синхронный IO — через
  `asyncio.to_thread`, чтобы не ловить `ASYNC240`.
- Type hints обязательны (mypy `strict = true`), докстринги на русском
  кратко объясняют *зачем*, а не *что*.
- Коммиты на русском, по одному логическому шагу (`Шаг N: ...`).
- Логи — структурный JSON (`src/logging_setup.py`), `extra={"_struct_x": ...}`.
