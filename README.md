# hh-smart-hunter

Умная автоматизация поиска работы на hh.ru: антиспам-фильтр и ассистент соискателя —
**без слепого массового отклика**. Каждая вакансия проходит дедупликацию, LLM-скоринг
против вашего резюме и проходит через человека-в-контуре в Telegram.

## Пайплайн

1. **Сбор** — планировщик опрашивает hh.ru по запросам из `config/filters.yaml`
   через CLI-адаптер `x-cli`; вакансии дедуплицируются по `hh_vacancy_id`
   (`seen_count`/`last_seen_at`), забаненные компании отсеиваются мгновенно.
2. **Скоринг** — LLM сопоставляет полную карточку вакансии с `data/resume.md` и
   возвращает строгий JSON (`score` 1–10, `match_reasons`, `red_flags`,
   `verdict: apply|skip`), валидируемый Pydantic.
3. **Письмо** — для `score >= threshold` генерируется короткое деловое письмо:
   боли вакансии ↔ конкретные кейсы из резюме.
4. **Human-in-the-loop** — карточка в Telegram с inline-кнопками:
   ✅ откликнуться (через x-cli) · ✏️ перегенерировать · 🚫 бан вакансии · ⛔ бан компании.
5. **Трекинг** — фоновая сверка статусов откликов; при `invited` — досье по компании
   и чек-лист подготовки к созвону.
6. **Автоподнятие резюме** — каждые 4 часа (лимиты hh.ru соблюдены).

## Архитектура

```
src/
├── config.py               # pydantic-settings (HHSH_*, вложенный "__")
├── logging_setup.py        # структурное JSON-логирование
├── domain/models.py        # DTO: VacancyDTO, VacancyScore, CoverLetterDTO, ApplyResultDTO…
├── domain/filters_config.py# типизированный config/filters.yaml
├── db/                     # SQLAlchemy 2.0 async + Alembic
│   ├── models.py           # vacancies / employers_blacklist / applications / resumes
│   ├── base.py             # движок (sqlite → postgres через HHSH_DB__URL), session_scope
│   └── repositories/       # vacancy, employer, application, resume (+ Repositories-аггрегат)
├── services/hh_adapter.py  # (Шаг 2) изолированный адаптер над CLI x-cli, MOCK-режим
├── services/llm_scorer.py  # (Шаг 2) LLM-скоринг, StrictModel-JSON
├── services/cover_letter.py# (Шаг 2) генерация писем
├── bot/                    # (Шаг 3) aiogram 3: карточки, inline-кнопки, подтверждение откликов
├── scheduler/              # (Шаг 3) APScheduler: опрос, сверка статусов, поднятие резюме
└── main.py                 # (Шаг 3) композиция: бот + планировщик в одном процессе
```

Единственный канал к hh.ru — CLI `x-cli` (`services/hh_adapter.py`): таймауты,
семафор параллельности, парсинг stdout/JSON. Бизнес-код не знает про сайт вообще.
`HHSH_HH__MOCK=true` включает фейковый адаптер — вся система тестируется без
браузера и аккаунта.

## Локальный старт

```bash
cp .env.example .env        # заполнить HHSH_LLM__API_KEY / HHSH_TELEGRAM__*
uv venv --python 3.12 && uv pip install -e ".[dev]"   # или pip в venv
.venv/bin/python -m src.app init-db     # миграции Alembic
.venv/bin/python -m src.app check       # самопроверка окружения
.venv/bin/python -m pytest tests/ -q
```

## Docker

```bash
docker compose up -d        # bot+scheduler в одном контейнер; x-cli и его
                            # сессии смотрятся в ./_xcli (volume, read-only)
docker compose logs -f      # JSON-логи
python -m src.app check     # проверка контейнера (docker compose run --rm hunter …)
```

## Конфигурация

| Раздел | Что задаёт |
|---|---|
| `.env` (HHSH_*) | окружение: БД, LLM, Telegram, x-cli, интервалы планировщика |
| `config/filters.yaml` | поисковые запросы, пороги, стоп-слова, автоподнятие |
| `data/resume.md` | резюме — источник для скоринга и писем |
