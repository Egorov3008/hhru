"""Структурное (JSON) логирование.

Один JSON-объект на строку: удобно для `docker logs | jq` и для разбора
инцидентов. В тестах/локальной консоли остаётся читаемый формат.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

_NOISY_LIBRARIES = ("aiosqlite", "apscheduler.executors", "httpx", "openai")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Структурные поля: logger.info("...", extra={"vacancy_id": ...})
        for key, value in getattr(record, "__dict__", {}).items():
            if key.startswith("_struct_"):
                payload[key.removeprefix("_struct_")] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO", *, json_output: bool | None = None) -> None:
    """Инициализация root-логгера. Повторный вызов безвреден (idempotent)."""
    if json_output is None:
        json_output = os.environ.get("HHSH_LOG_JSON", "1") == "1"

    formatter: logging.Formatter
    if json_output:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for name in _NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
