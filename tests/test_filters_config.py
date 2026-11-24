"""Проверки загрузки и валидации config/filters.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.domain.filters_config import FiltersConfig, load_filters

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_FILTERS = REPO_ROOT / "config" / "filters.yaml"


class TestShippedFile:
    def test_shipped_filters_load(self) -> None:
        filters = load_filters(REAL_FILTERS)

        assert len(filters.searches) == 2
        first = filters.find_task("python-backend")
        assert first is not None
        assert first.query == "Python backend разработчик"
        assert first.exclude_words

        assert filters.limits.min_salary.amount == 250_000      # YAML поддерживает '_'
        assert filters.scoring.score_threshold == 7
        assert filters.boost.interval_minutes == 240
        assert filters.boost.enabled is True

    def test_find_task_unknown_returns_none(self) -> None:
        filters = load_filters(REAL_FILTERS)
        assert filters.find_task("nope") is None


class TestValidationError:
    def test_duplicate_search_names_rejected(self, tmp_path: Path) -> None:
        file = tmp_path / "filters.yaml"
        file.write_text(
            """
searches:
  - {name: dup, query: "a"}
  - {name: dup, query: "b"}
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="дубликаты имён"):
            load_filters(file)

    def test_empty_searches_rejected(self, tmp_path: Path) -> None:
        file = tmp_path / "filters.yaml"
        file.write_text("searches: []\n", encoding="utf-8")
        with pytest.raises(ValueError, match="хотя бы один"):
            load_filters(file)

    def test_unknown_section_rejected(self, tmp_path: Path) -> None:
        file = tmp_path / "filters.yaml"
        file.write_text("searches: []\ntypo_section: 1\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_filters(file)  # pydantic extra=forbid -> ValidationError

    def test_broken_yaml_reports_path(self, tmp_path: Path) -> None:
        file = tmp_path / "filters.yaml"
        file.write_text("searches: [ unbalanced\n", encoding="utf-8")
        with pytest.raises(ValueError, match=str(file)):
            load_filters(file)

    def test_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_filters("/nonexistent/filters.yaml")


class TestModelDefaults:
    def test_limits_defaults(self) -> None:
        filters = FiltersConfig.model_validate(
            {"searches": [{"name": "x", "query": "y"}]}
        )
        assert filters.limits.max_age_days == 14
        assert filters.boost.interval_minutes == 240
        assert filters.boost.resume_ids == []
