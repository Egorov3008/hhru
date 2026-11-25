"""Конфигурация окружения (pydantic-settings).

Всё через переменные окружения с префиксом ``HHSH_`` и разделителем ``__``
между секциями, например: ``HHSH_LLM__BASE_URL``, ``HHSH_HH__MOCK``.
.env подхватывается автоматически; приоритет: env > .env > дефолты.

Поисковые задачи и правила фильтрации — не здесь, а в config/filters.yaml
(см. src/domain/filters_config.py): их правят чаще и они не про окружение.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseModel):
    log_level: str = "INFO"
    timezone: str = "Europe/Moscow"
    data_dir: Path = Path("data")
    config_dir: Path = Path("config")
    # Локальные артефакты (SQLite, досье к интервью) — в отдельной папке
    runtime_dir: Path = Path("runtime")


class DatabaseSettings(BaseModel):
    # SQLite по умолчанию; PostgreSQL: postgresql+asyncpg://user:pass@host:5432/hh
    url: str = "sqlite+aiosqlite:///./runtime/hh-smart-hunter.db"
    echo_sql: bool = False

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith("sqlite")


class LLMSettings(BaseModel):
    # Любой OpenAI-совместимый роутер: OpenRouter, LiteLLM, Ollama (/v1)…
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: SecretStr = SecretStr("")
    model: str = "anthropic/claude-sonnet-4.6"
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1600, ge=1)
    timeout_seconds: float = 120.0
    # Простая защита от burst при массовом скоринге новой выдачи
    requests_per_minute: int = 30


class TelegramSettings(BaseModel):
    bot_token: SecretStr = SecretStr("")
    # Личный чат владельца: сюда уходят карточки и уведомления
    chat_id: int = 0

    def is_configured(self) -> bool:
        return bool(self.bot_token.get_secret_value()) and self.chat_id != 0


class HHAdapterSettings(BaseModel):
    # true — адаптер отдаёт реалистичные тестовые данные; запуск без hh.ru
    mock: bool = True
    # hh-agent (демон-парсер на хосте с живым Chrome): базовый URL,
    # например "http://127.0.0.1:10087" либо ssh-туннель на него
    agent_endpoint: str = "http://127.0.0.1:10087"
    # Имя webbridge-сессии (группа вкладок) для hh.ru
    session: str = "hhru"
    command_timeout_seconds: float = 90.0
    # Параллельных обращений к агенту — не больше двух (один браузер)
    max_concurrency: int = 2


class SchedulerSettings(BaseModel):
    poll_interval_minutes: int = Field(default=30, ge=1)
    status_check_interval_minutes: int = Field(default=90, ge=1)
    # Минимальная пауза между подъёмами одного и того же резюме
    minutes_between_boosts: int = Field(default=240, ge=15)


class ScoringSettings(BaseModel):
    score_threshold: int = Field(default=7, ge=1, le=10)
    resume_path: Path = Path("data/resume.md")
    filters_path: Path = Path("config/filters.yaml")
    prompts_dir: Path = Path("prompts")


class Settings(BaseSettings):
    """Корневая конфигурация. Все секции имеют дефолты для мгновенного старта."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="HHSH_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    app: AppSettings = Field(default_factory=AppSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    hh: HHAdapterSettings = Field(default_factory=HHAdapterSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)

    def ensure_dirs(self) -> None:
        """Создаёт runtime/data папки, если их нет (запуск из любого cwd)."""
        self.app.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.app.data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Синглтон-конфиг (кэш в процессе; тесты сбрасывают через cache_clear)."""
    settings = Settings()
    settings.ensure_dirs()
    return settings
