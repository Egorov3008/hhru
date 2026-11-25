"""hh-agent: FastAPI-демон-парсер на хосте с живым Chrome (Шаг 2).

Один эндпоинт `POST /call`: cmd=search → webbridge navigate (страница
должна отрисоваться) → evaluate с JS-парсером по data-qa → golden-контракт.
VPS не знает про hh.ru: получает структурированный JSON.

Запуск: `uvicorn server:app --host 0.0.0.0 --port ${HH_AGENT_PORT:-10087}`
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from models import CardDTO, SearchResponse
from parser import parse_search_html

app = FastAPI(title="hh-agent", version="0.1.0")

WEBBRIDGE_URL = os.environ.get("WEBBRIDGE_URL", "http://127.0.0.1:10086")
SESSION = os.environ.get("HH_SESSION", "hhru")


def build_search_url(query: str, area: str, page: int) -> str:
    """URL выдачи hh.ru: текстовый запрос, регион, страница."""
    from urllib.parse import quote

    return (
        "https://krasnoznamensk.hh.ru/search/vacancy"
        f"?text={quote(query)}&searchArea={area}"
        "&order=submit_date&itemsOnPage=50"
        f"&page={page}"
    )


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "hh-agent"}


@app.post("/call", response_model=SearchResponse)
async def call(body: dict) -> SearchResponse:
    """search → webbridge navigate → evaluate → парсер → CardDTO[]."""
    import httpx

    cmd = body.get("cmd")
    if cmd != "search":
        return SearchResponse(ok=False, data=[], error=f"неизвестный cmd: {cmd!r}")

    args = body.get("args", {})
    url = build_search_url(str(args.get("query", "")), str(args.get("area", "1")), int(args.get("page", 0)))
    async with httpx.AsyncTimeout(90.0).client() as client:
        navigate = await client.post(
            f"{WEBBRIDGE_URL}/command",
            json={"action": "navigate", "args": {"url": url, "newTab": True}, "session": SESSION},
        )
        navigate.raise_for_status()
        evaluate = await client.post(
            f"{WEBBRIDGE_URL}/command",
            json={
                "action": "evaluate",
                "args": {"code": "document.documentElement.outerHTML"},
                "session": SESSION,
            },
        )
        evaluate.raise_for_status()
    html = evaluate.json()["data"]["value"]
    cards = [CardDTO.model_validate(c) for c in parse_search_html(html)]
    return SearchResponse(ok=True, data=cards[: int(args.get("limit", 50))])
