# Шаг 2: hh-клиент и адаптер hh.ru — реализационный план

> **Для исполнителя:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development
> (рекомендуется) или superpowers:executing-plans. Шаги — чекбоксы (`- [ ]`).

**Цель:** научить сервис на VPS получать структурированные вакансии с hh.ru
через hh-agent (FastAPI на хосте с живым Chrome) и обернуть это в
`hh_adapter.py` c сохранённым MOCK-режимом.

**Архитектура:** два процесса. **Хост:** hh-agent — FastAPI-демон, который
через kimi-webbridge daemon (`127.0.0.1:10086`) рендерит страницы выдачи
hh.ru и парсит их по `data-qa` в JSON. **VPS:** `src/services/hh_adapter.py`
— aiohttp-клиент к hh-agent, возвращает DTO-объекты (`VacancyDTO`, уже
определённые в `src/domain/models.py`). Сессия и cookies живут на хосте,
VPS ничего не знает про сайт.

**Технологии:** Python 3.12, FastAPI + uvicorn (hh-agent), aiohttp
(hh_adapter), selectolax (парсер HTML, fallback beautifulsoup4),
pydantic v2 (DTO). Golden-фикстуры уже сняты и лежат в
`tests/fixtures/` (3 HTML + 3 JSON).

**Спека:** `/home/vladimir/.claude/plans/cli-declarative-fairy.md`.

## Глобальные ограничения

- Python 3.12, async-first; синхронный IO — через `asyncio.to_thread`.
- Числовые id hh.ru — **строки**; времена — timezone-aware UTC.
- Все DTO — `StrictModel` (`extra="forbid"`) из `src/domain/models.py`.
- Конфиг — pydantic-settings с префиксом `HHSH_`, вложенность `__`
  (`src/config.py`, `get_settings()` — lru_cache).
- Структурный JSON-лог (`src/logging_setup.py`), `extra={"_struct_x": ...}`.
- Datasent: hh.ru доступен **только** через hh-agent; бизнес-слой не знает
  про сайт.

## Фокус ревью

| Риск | Что проверяем | Задача |
|---|---|---|
| hh-agent недоступен / таймаут | `HHAdapterError` с текстом исходной ошибки | Task 2 |
| Зарплатный блок без `data-qa` | fallback на текст с `₽` даёт `salary_min/max` | Task 1 |
| hh.ru меняет markup | golden-фикстуры ловят поломку до прода | Task 3 |
| Дубли в выдаче | повторный `search` даёт тот же `hh_vacancy_id`, репозиторий инкрементит `seen_count` | Task 2 |
| Часовая зона | `published_at` — UTC (hh.ru отдаёт Europe/Moscow — конвертим) | Task 1 |

---

## Task 1: hh-agent (FastAPI-демон на хосте)

**Файлы:**
- Создать: `tools/hh-agent/server.py` (FastAPI-приложение, `POST /call`)
- Создать: `tools/hh-agent/parser.py` (`parse_search_html(html: str) -> list[dict]`)
- Создать: `tools/hh-agent/models.py` (Pydantic-модели ответа)
- Создать: `tools/hh-agent/__init__.py`
- Тест: `tests/test_parser.py`

**Интерфейсы:**
- `POST /call {"cmd": "search", "query": str, "area": str, "limit": int, "page": int}`
- Отвечает `{"ok": true, "data": [...]}`; ошибка → HTTP 500 / `{"ok": false}`.
- `parser.parse_search_html(html)` → `list[dict]` со строками-`id`.
- `data[].id, .title, .employer_name, .employer_id, .area_name,
  .salary_min (int|null), .salary_max (int|null), .salary_text, .experience,
  .published_at (ISO 8601 UTC)` — имена совпадают с `VacancyDTO` из
  `src/domain/models.py` (Шаг 1).

- [ ] **Шаг 1. Модель ответа и парсер**

`tools/hh-agent/models.py`: Pydantic-модель `CardDTO` c полями
`id: str, title: str, employer_name: str, employer_id: str | None,
area_name: str, salary_min: int | None, salary_max: int | None,
salary_text: str | None, experience: str | None, published_at: datetime`
(UTC). Поля `salary_min/max` считаются из `salary_text` парсером
(числа в тексте → int, `null` если текста нет).

- [ ] **Шаг 2. Парсер по golden-фикстурам**

`tools/hh-agent/parser.py::parse_search_html(html: str) -> list[dict]`:
selectolax parses `data-qa="serp-item__title"` и др. атрибуты;
зарплатный блок ловим по тексту с `₽`. Конверсия «N минут/часов назад»
из Europe/Moscow → UTC — отдельной функцией `to_utc()`, чтобы тестировалась
отдельно.

- [ ] **Шаг 3. Тест на фикстурах**

`tests/test_parser.py` прогоняет `parse_search_html` по трём фикстурам
из `tests/fixtures/` и сверяет первые 5 карточек с golden JSON.
Запуск: `pytest tests/test_parser.py -v` → PASS.

- [ ] **Шаг 4. FastAPI-сервер**

`tools/hh-agent/server.py`: POST `/call` → внутри webbridge `navigate`
(даём отрисоваться) → `evaluate` с JS-парсером → JSON. Порт из env
`HH_AGENT_PORT` (дефолт 10087). Запуск для разработки:
`uvicorn server:app --port 10087`.

- [ ] **Шаг 5. Живой smoke**

`curl -s localhost:10087/call -d '{"cmd":"search","query":"python","area":"1","limit":5,"page":0}' -H 'content-type: application/json'`
→ в ответе ≥ 3 карточки, у первой `id` — строка из 8–9 цифр,
`published_at` — ISO 8601 с зоной.

- [ ] **Шаг 6. Коммит**

`git add tools/hh-agent/ tests/test_parser.py && git commit -m "Шаг 2.1: hh-agent — парсер выдачи hh.ru в JSON"`

---

## Task 2: hh_adapter (aiohttp-клиент на VPS)

**Файлы:**
- Создать: `src/services/hh_adapter.py`
- Изменить: `src/config.py` (секция `HhSettings`: `endpoint`, `mock`,
  `timeout_seconds`, `max_concurrency`) — по образцу существующих секций
- Тест: `tests/test_hh_adapter.py`

**Интерфейсы:**
- Consumes: HTTP `POST /call` Task 1 (эндпоинт в `settings.hh.endpoint`).
- Производит: класс `HhAdapter` c async-методами `search(request) ->
  list[VacancyDTO]`, `statuses(ids) -> list[ApplyResultDTO]`,
  `bump(resume_id) -> BumpResultDTO`, `apply(vacancy_id, letter) ->
  ApplyResultDTO`. Ошибки → `HHAdapterError(RuntimeError)`.
- Фабрика `make_adapter(settings)` возвращает mock при
  `settings.hh.mock`, иначе — реальный клиент.

- [ ] **Шаг 1. Секция конфига**

Добавить `HhSettings(BaseSettings)` c `endpoint: str`, `mock: bool = True`,
`timeout_seconds: int = 90`, `max_concurrency: int = 2`; в `Settings` —
поле `hh: HhSettings`. В `.env.example` — `HHSH_HH__MOCK`,
`HHSH_HH__AGENT_ENDPOINT` (заменяет `CLI_BIN`),
`HHSH_HH__COMMAND_TIMEOUT_SECONDS`, `HHSH_HH__MAX_CONCURRENCY`.

- [ ] **Шаг 2. Клиент**

`HhAdapter`: aiohttp-сессия с `timeout=ClientTimeout(total=…)` и
`asyncio.Semaphore(max_concurrency)`. `_call(cmd, **args)` → POST,
ошибки → `HHAdapterError`. `search()` возвращает
`[VacancyDTO.model_validate(item) for item in data]`.

- [ ] **Шаг 3. Тест на mock-ветке и на разборе ответа**

`tests/test_hh_adapter.py`: mock возвращает детерминированный набор;
парсер ответа на реальном golden JSON (тот же файл, что и для Task 1)
даёт те же значения.

- [ ] **Шаг 4. Прогон и коммит**

`pytest tests/test_hh_adapter.py -v` → PASS.
`git commit -m "Шаг 2.2: hh_adapter — aiohttp-клиент к hh-agent"`

---

## Task 3: интеграция и golden-фикстуры

- Создать: `tests/fixtures/README.md` (как снять новую фикстуру)
- Изменить: `tests/test_hh_adapter.py` — parametrized по 3 фикстурам
- Изменить: `README.md` (раздел «Шаг 2»)

- [ ] **Шаг 1. Параметризованный тест на фикстурах** — те же golden JSON,
      что Task 1 использует в парсере; прогоняем через
      `HhAdapter._parse` и сверяем с `VacancyDTO`.
- [ ] **Шаг 2. Обновление README** — раздел «Шаг 2»: как запустить hh-agent,
      как обновить фикстуры (`tools/update_fixtures.sh`).
- [ ] **Шаг 3. Коммит** — `git commit -m "Шаг 2.3: golden-фикстуры и раздел Шага 2"`

## Проверка всего Шага 2

- `pytest tests/ -q` — все зелёные (включая тесты Шага 1, не ломая их).
- `python -m src.app check` — самопроверка с `HHSH_HH__MOCK=false`
  находит hh-agent.
- Живой дубль: два `search` подряд дают пересечение по id (дедуп
  работает).
