"""ORM-модели таблиц.

Схема:

- vacancies            — все увиденные вакансии (дедуп по hh_vacancy_id + вердикт скоринга)
- employers_blacklist  — компании, чьи вакансии не показывать и не откликаться
- applications         — отправленные отклики и их статусы (трекинг)
- resumes              — резюме пользователя (для автоподнятия и привязки откликов)

Числовые идентификаторы hh.ru храним как строки: сайт стабилен, но длина может
меняться, а сравнение строк дешевле миграций.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class DeclarativeBaseTS(DeclarativeBase):
    pass


Base = DeclarativeBaseTS


def utcnow() -> datetime:
    """Одинаковое для всех моделей «сейчас» (timezone-aware UTC)."""

    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class VacancyState(StrEnum):
    NEW = "new"           # сохранена из выдачи, полное описание ещё не читали
    READY_TO_SCORE = "ready_to_score"  # полная карточка прочитана
    SCORED = "scored"     # LLM оценил, письмо не сгенерировано/не нужно
    NOTIFIED = "notified" # карточка + письмо отправлены в Telegram
    APPLIED = "applied"   # отклик отправлен
    SKIPPED = "skipped"   # отсеяна pre-фильтром или скорингом


class ApplicationStatus(StrEnum):
    SENT = "sent"
    SEEN = "seen"
    INVITED = "invited"
    DECLINED = "declined"
    ERROR = "error"


# native_enum=False: SQLite не умеет ENUM, а PostgreSQL получит VARCHAR —
# один диалект-агностичный вид для обеих БД
def _str_enum(enum_cls: type[StrEnum]) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda e: [item.value for item in e],
        length=32,
    )


_STATE_ENUM = _str_enum(VacancyState)
_APPLICATION_STATUS_ENUM = _str_enum(ApplicationStatus)


class Vacancy(Base, TimestampMixin):
    """Вакансия из выдачи hh.ru. Существует, даже если отклика не было.

    `seen_count`/`last_seen_at` — дедупликация: вакансия может «подниматься»
    и попадать в выдачу повторно; мы не теряем уже оценённый вердикт.
    """

    __tablename__ = "vacancies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hh_vacancy_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    employer_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    employer_name: Mapped[str] = mapped_column(String(512), nullable=False)

    area: Mapped[str | None] = mapped_column(String(256), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    salary_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)

    experience: Mapped[str | None] = mapped_column(String(64), nullable=True)
    employment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schedule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    work_formats: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    search_task: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Идемпотентность опросов: сколько раз встречали эту вакансию в выдаче
    seen_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    state: Mapped[VacancyState] = mapped_column(
        _STATE_ENUM, default=VacancyState.NEW, nullable=False, index=True
    )

    # Результат LLM-скоринга
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    match_reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    red_flags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    score_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Черновик сопроводительного письма (регенерация хранит последнюю версию)
    letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    letter_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    applications: Mapped[list[Application]] = relationship(
        back_populates="vacancy", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Частый запрос: какие вакансии дожидаются скоринга или отправки в Telegram
        Index("ix_vacancies_state_seen", "state", "last_seen_at"),
        Index("ix_vacancies_employer_state", "employer_id", "state"),
    )

    def __repr__(self) -> str:
        return f"<Vacancy id={self.id} hh={self.hh_vacancy_id} {self.title!r}>"


class EmployerBlacklist(TimestampMixin, Base):
    """Бан по работодателю: не показывать и не откликаться никогда."""

    __tablename__ = "employers_blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hh_employer_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<EmployerBlacklist id={self.id} employer={self.hh_employer_id} {self.name!r}>"


class Resume(Base, TimestampMixin):
    """Резюме пользователя; для автоподнятия и привязки откликов."""

    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hh_resume_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # Путь к markdown-версии (для LLM); основной data/resume.md — глобальный
    md_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_auto_boost: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_boosted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_boosts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    applications: Mapped[list[Application]] = relationship(back_populates="resume")


class Application(Base, TimestampMixin):
    """Отправленный отклик; фоновая работа трекает status_changed_at."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # hh.ru отдаёт id отклика после отправки; до неё поле пустое
    hh_application_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)

    vacancy_id: Mapped[int] = mapped_column(
        ForeignKey("vacancies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )

    letter: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ApplicationStatus] = mapped_column(
        _APPLICATION_STATUS_ENUM, default=ApplicationStatus.SENT, nullable=False, index=True
    )

    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Уведомление о приглашении (досье к интервью) не теряется при повторной сверке
    dossier_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    vacancy: Mapped[Vacancy] = relationship(back_populates="applications")
    resume: Mapped[Resume | None] = relationship(back_populates="applications")

    def __repr__(self) -> str:
        return f"<Application id={self.id} vacancy={self.vacancy_id} status={self.status}>"
