"""Адаптер к hh-agent (aiohttp-клиент) и mock-ветка (Шаг 2, Task 2).

Бизнес-слой (сервисы, бот, планировщик) знает только `HhAdapter.search/
statuses/apply/bump` и `VacancyDTO` (Шаг 1). hh-agent живёт на хосте с
живым Chrome и отдаёт golden-контракт; mock отдаёт детерминированный
набор без сети.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import aiohttp

from src.config import Settings
from src.domain.models import VacancyDTO


class HHAdapterError(RuntimeError):
    """Ошибка адаптера: недоступность hh-agent, таймаут, битый ответ."""


class HhAdapter:
    """Настоящий адаптер: aiohttp → hh-agent /call (хост с Chrome)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.hh.max_concurrency)
        self._endpoint = settings.hh.agent_endpoint.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=settings.hh.command_timeout_seconds)
        self._client: aiohttp.ClientSession | None = None

    async def _get_client(self) -> aiohttp.ClientSession:
        """Один переиспользуемый клиент (keep-alive к hh-agent)."""
        if self._client is None or self._client.closed:
            self._client = aiohttp.ClientSession(timeout=self._timeout)
        return self._client

    async def _call(self, cmd: str, **args) -> dict:
        """POST /call {cmd, args} на hh-agent; ошибки → HHAdapterError."""
        async with self._semaphore:
            try:
                client = await self._get_client()
                async with client.post(f"{self._endpoint}/call", json={"args": args}) as resp:
                    if resp.status >= 500:
                        raise HHAdapterError(f"hh-agent вернул HTTP {resp.status}")
                    payload = await resp.json()
            except (aiohttp.ClientError, TimeoutError) as exc:
                raise HHAdapterError(f"hh-agent недоступен: {exc}") from exc
        if not payload.get("ok", False):
            raise HHAdapterError(f"hh-agent ok=false: {payload.get('error')}")
        return payload["data"]

    async def search(self, query: str, area: str = "1", limit: int = 50, page: int = 0) -> list[VacancyDTO]:
        """Одна страница выдачи hh.ru → список VacancyDTO."""
        cards = await self._call("search", query=query, area=area, limit=limit, page=page)
        return [VacancyDTO.model_validate(c) for c in cards[:limit]]

    async def statuses(self, ids: Sequence[str]) -> list[dict]:
        """Снимок статусов откликов по списку hh_vacancy_id."""
        return await self._call("statuses", ids=list(ids))

    async def apply(self, vacancy_id: str, letter: str) -> dict:
        """Отклик (x-cli apply внутри hh-agent) → ApplyResultDTO-готовый dict."""
        return await self._call("apply", vacancy_id=vacancy_id, letter=letter)

    async def bump(self, resume_id: str) -> dict:
        """Поднять резюме (hh-agent → x-cli resume bump)."""
        return await self._call("bump", resume_id=resume_id)

    async def close(self) -> None:
        """Закрыть HTTP-сессию (graceful shutdown)."""
        if self._client and not self._client.closed:
            await self._client.close()


class MockHhAdapter:
    """MOCK-режим: тот же контракт без сети и браузера (для разработки)."""

    async def search(self, query: str, area: str = "1", limit: int = 50, page: int = 0) -> list[VacancyDTO]:
        return []

    async def statuses(self, ids: Sequence[str]) -> list[dict]:
        return []

    async def apply(self, vacancy_id: str, letter: str) -> dict:
        return {"ok": True, "hh_vacancy_id": vacancy_id}

    async def bump(self, resume_id: str) -> dict:
        return {"bumped": True, "reason": "ok"}


def make_adapter(settings: Settings) -> HhAdapter | MockHhAdapter:
    """Фабрика: mock=true → MockHhAdapter, иначе живой HhAdapter."""
    return MockHhAdapter() if settings.hh.mock else HhAdapter(settings)
