"""Проверки репозиториев: дедупликация, чёрный список, статусы откликов."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.db.models import VacancyState
from src.db.repositories.all import Repositories
from src.domain.models import ApplicationState, ResumeDTO, VacancyScore

from tests.factories import make_task, make_vacancy_dto


class TestVacancyDedup:
    async def test_first_upsert_creates(self, repos: Repositories) -> None:
        row, created = await repos.vacancies.upsert_seen(make_vacancy_dto("111"), make_task())
        assert created is True
        assert row.seen_count == 1
        assert row.state is VacancyState.NEW  # выдача без полного описания
        assert row.search_task == "python-backend"

    async def test_repeat_upsert_bumps_seen_without_new_row(self, repos: Repositories) -> None:
        await repos.vacancies.upsert_seen(make_vacancy_dto("111"), make_task())
        row, created = await repos.vacancies.upsert_seen(make_vacancy_dto("111"), make_task())
        assert created is False
        assert row.seen_count == 2
        total = await repos.vacancies.count_by_state(VacancyState.NEW)
        assert total == 1

    async def test_full_card_moves_to_ready_to_score(self, repos: Repositories) -> None:
        created_row, _ = await repos.vacancies.upsert_seen(make_vacancy_dto("111"), make_task())
        full = make_vacancy_dto("111", description="Полное описание вакансии, asyncio, K8s.")
        updated = await repos.vacancies.save_full_card(full)
        assert updated is not None
        assert updated.id == created_row.id
        assert updated.state is VacancyState.READY_TO_SCORE
        pending = await repos.vacancies.take_for_scoring()
        assert [v.id for v in pending] == [created_row.id]

    async def test_untouched_hung_rows_listed(self, repos: Repositories) -> None:
        row, _ = await repos.vacancies.upsert_seen(make_vacancy_dto("222"), make_task())
        row.last_seen_at = datetime.now(UTC) - timedelta(hours=48)
        await repos.session.flush()
        stale = await repos.vacancies.list_untouched_older_than(hours=24)
        assert [v.id for v in stale] == [row.id]


class TestScoringPersistence:
    async def test_mark_scored_positive_and_negative(self, repos: Repositories) -> None:
        row, _ = await repos.vacancies.upsert_seen(
            make_vacancy_dto("300", description="desc"), make_task()
        )
        apply_score = VacancyScore.model_validate(
            {"score": 8, "verdict": "apply", "match_reasons": ["asyncio"]}
        )
        saved = await repos.vacancies.mark_scored(row.id, apply_score)
        assert saved is not None
        assert saved.state is VacancyState.SCORED
        assert saved.score == 8

        skip_score = VacancyScore.model_validate({"score": 3, "verdict": "skip"})
        second, _ = await repos.vacancies.upsert_seen(
            make_vacancy_dto("301", description="desc"), make_task()
        )
        skipped = await repos.vacancies.mark_scored(second.id, skip_score)
        assert skipped is not None
        assert skipped.state is VacancyState.SKIPPED
        # skip-вакансии больше не попадают в обработку
        assert await repos.vacancies.take_ready_for_notification() == []

    async def test_letter_saved_and_notification_flow(self, repos: Repositories) -> None:
        row, _ = await repos.vacancies.upsert_seen(
            make_vacancy_dto("310", description="desc"), make_task()
        )
        await repos.vacancies.mark_scored(
            row.id,
            VacancyScore.model_validate({"score": 9, "verdict": "apply", "match_reasons": ["x"]}),
        )
        await repos.vacancies.save_letter(row.id, "Драфт письма " * 20)
        ready = await repos.vacancies.take_ready_for_notification()
        assert len(ready) == 1
        await repos.vacancies.mark_notified(row.id)
        assert await repos.vacancies.take_ready_for_notification() == []

    async def test_blacklist_sweep_disposes_pending_rows(self, repos: Repositories) -> None:
        row, _ = await repos.vacancies.upsert_seen(
            make_vacancy_dto("320", employer_id="777", description="d"), make_task()
        )
        assert row.employer_id == "777"
        removed = await repos.vacancies.blacklist_sweep({"777"})
        assert removed == 1
        swept = await repos.vacancies.get_by_hh_id("320")
        assert swept is not None
        assert swept.state is VacancyState.SKIPPED


class TestEmployerBlacklist:
    async def test_add_is_idempotent(self, repos: Repositories) -> None:
        await repos.employers.add("777", "OOO Tech", "мусорные офферы")
        again = await repos.employers.add("777", "OOO Tech", "обновлённая причина")
        assert again.reason == "обновлённая причина"
        banned = await repos.employers.all_banned_ids()
        assert banned == {"777"}

    async def test_remove(self, repos: Repositories) -> None:
        await repos.employers.add("888", "X", None)
        assert await repos.employers.remove("888") is True
        assert await repos.employers.is_blacklisted("888") is False


class TestApplications:
    async def _applied_vacancy(self, repos: Repositories) -> int:
        row, _ = await repos.vacancies.upsert_seen(
            make_vacancy_dto("400", description="d"), make_task()
        )
        await repos.vacancies.mark_applied(row.id)
        return row.id

    async def test_create_and_status_flow(self, repos: Repositories) -> None:
        vacancy_id = await self._applied_vacancy(repos)
        application = await repos.applications.create(vacancy_id, "письмо", hh_application_id="987")
        assert application.status.value == "sent"

        await repos.applications.set_status(
            application.id, ApplicationState.INVITED, comment="Позвоните"
        )
        fetched = await repos.applications.get_by_hh_application_id("987")
        assert fetched is not None
        assert fetched.status.value == "invited"
        assert fetched.status_changed_at is not None

    async def test_error_does_not_overwrite_invitation(self, repos: Repositories) -> None:
        vacancy_id = await self._applied_vacancy(repos)
        application = await repos.applications.create(vacancy_id, "письмо")
        await repos.applications.set_status(application.id, ApplicationState.INVITED)
        await repos.applications.set_status(application.id, ApplicationState.ERROR, comment="таймаут")
        fetched = await repos.applications.get_with_vacancy(application.id)
        assert fetched is not None
        assert fetched.status.value == "invited"
        assert fetched.vacancy.hh_vacancy_id == "400"

    async def test_status_check_queue(self, repos: Repositories) -> None:
        vacancy_id = await self._applied_vacancy(repos)
        sent = await repos.applications.create(vacancy_id, "письмо 1")
        await repos.applications.create(vacancy_id, "письмо 2")
        declined = await repos.applications.get_with_vacancy(sent.id)
        assert declined is not None
        await repos.applications.set_status(declined.id, ApplicationState.DECLINED)

        queue = await repos.applications.take_for_status_check()
        # Отклонённый выпадает из очереди сверок
        assert len(queue) == 1
        assert queue[0].letter == "письмо 2"


class TestResumes:
    async def test_upsert_and_boost_counter(self, repos: Repositories) -> None:
        dto = ResumeDTO(hh_resume_id="555", title="Python Backend", can_boost=True)
        await repos.resumes.upsert(dto, auto_boost=True)
        row = await repos.resumes.get_by_hh_id("555")
        assert row is not None
        assert row.is_auto_boost is True

        boosted = await repos.resumes.mark_boosted(row.id)
        assert boosted is not None
        assert boosted.total_boosts == 1
        assert boosted.last_boosted_at is not None

        blocked = await repos.resumes.upsert(
            ResumeDTO(hh_resume_id="556", title="Другое", can_boost=False), auto_boost=True
        )
        assert blocked.is_auto_boost is False
        assert len(await repos.resumes.list_boostable()) == 1
