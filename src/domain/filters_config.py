"""Типизированная загрузка config/filters.yaml.

YAML-файл — единственный источник поисковых задач и правил pre-фильтрации.
Настройки окружения (токены, URL БД) живут в pydantic-settings (src/config.py).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.models import SearchTaskDTO  # noqa: F401 — реэкспорт для удобства


class StrictConfig(BaseModel):
    """Базовый класс для YAML-конфигов: запрещаем неизвестные секции (опечатки)."""

    model_config = ConfigDict(extra="forbid")


class MinSalary(StrictConfig):
    amount: int | None = None
    currency: str = "RUR"


class LimitsConfig(StrictConfig):
    max_age_days: int = Field(default=14, ge=1)
    min_salary: MinSalary = Field(default_factory=MinSalary)
    hard_reject_keywords: list[str] = Field(default_factory=list)
    employer_name_blacklist: list[str] = Field(default_factory=list)


class ScoringRules(StrictConfig):
    score_threshold: int = Field(default=7, ge=1, le=10)
    red_flag_hints: list[str] = Field(default_factory=list)
    target_domains: list[str] = Field(default_factory=list)


class BoostConfig(StrictConfig):
    enabled: bool = True
    interval_minutes: int = Field(default=240, ge=15)
    max_boosts_per_day_per_resume: int = Field(default=6, ge=1, le=24)
    # hh_resume_id из x-cli; заполняется после первого запуска списка резюме
    resume_ids: list[str] = Field(default_factory=list)


class FiltersConfig(StrictConfig):
    searches: list[SearchTaskDTO]
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    scoring: ScoringRules = Field(default_factory=ScoringRules)
    boost: BoostConfig = Field(default_factory=BoostConfig)

    @field_validator("searches")
    @classmethod
    def _unique_names(cls, value: list[SearchTaskDTO]) -> list[SearchTaskDTO]:
        names = [task.name for task in value]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            msg = f"дубликаты имён поисковых задач: {', '.join(dupes)}"
            raise ValueError(msg)
        if not value:
            msg = "в filters.yaml должен быть хотя бы один поисковый запрос"
            raise ValueError(msg)
        return value

    def find_task(self, name: str) -> SearchTaskDTO | None:
        """Поиск задачи по имени (планировщик указывает, что опрашивать)."""
        return next((task for task in self.searches if task.name == name), None)


def load_filters(path: Path | str) -> FiltersConfig:
    """Читает и валидирует filters.yaml; ошибка содержит путь и позицию в YAML.

    PyYAML поддерживает разделитель разрядов (250_000 -> 250000), поэтому
    pre-обработка не нужна.
    """
    file_path = Path(path)
    if not file_path.is_file():
        msg = f"файл фильтров не найден: {file_path}"
        raise FileNotFoundError(msg)
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        msg = f"yaml сломан в {file_path}: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(raw, dict):
        msg = f"ожидается mapping в корне {file_path}, получено: {type(raw).__name__}"
        raise TypeError(msg)
    return FiltersConfig.model_validate(raw)


__all__ = [
    "BoostConfig",
    "FiltersConfig",
    "LimitsConfig",
    "MinSalary",
    "ScoringRules",
    "SearchTaskDTO",
    "load_filters",
]
