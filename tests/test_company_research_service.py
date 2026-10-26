import uuid
from datetime import UTC, datetime, timedelta

import pytest

from resumecraft.core.enums import JobType, ResearchStatus
from resumecraft.core.exceptions import NotFoundError
from resumecraft.db.models import CompanyResearch, Job
from resumecraft.db.repositories import company_research as research_repo
from resumecraft.services import company_research_service

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


async def _progress_spy() -> tuple[list[float], object]:
    calls: list[float] = []

    async def update_progress(progress: float) -> None:
        calls.append(progress)

    return calls, update_progress


async def _seed_research(
    session,
    user_id: uuid.UUID,
    *,
    company_name: str,
    created_at: datetime,
    deleted: bool = False,
) -> CompanyResearch:
    research = CompanyResearch(
        user_id=user_id,
        company_name=company_name,
        status=ResearchStatus.COMPLETED,
        created_at=created_at,
    )
    if deleted:
        research.deleted_at = created_at + timedelta(hours=1)
    await research_repo.create(session, research)
    await session.commit()
    return research


async def _make_research_job(
    session,
    *,
    user_id: uuid.UUID,
    research_id: uuid.UUID,
    company_name: str = "Acme",
    website: str | None = None,
) -> Job:
    job = Job(
        user_id=user_id,
        type=JobType.COMPANY_RESEARCH,
        input={
            "research_id": str(research_id),
            "company_name": company_name,
            "website": website,
        },
    )
    session.add(job)
    await session.flush()
    return job


async def test_create_pending_research_stores_shell(db_session) -> None:
    user_id = uuid.uuid4()
    research = await company_research_service.create_pending_research(
        db_session, user_id, "Acme", "https://acme.com/"
    )

    stored = await db_session.get(CompanyResearch, research.id)
    assert stored is not None
    assert stored.user_id == user_id
    assert stored.company_name == "Acme"
    assert stored.website == "https://acme.com/"
    assert stored.reports is None
    assert stored.status == ResearchStatus.PENDING


async def test_build_research_job_input_round_trips(db_session) -> None:
    research = await company_research_service.create_pending_research(
        db_session, uuid.uuid4(), "Acme", None
    )

    job_input = company_research_service.build_research_job_input(research)

    assert job_input["research_id"] == str(research.id)
    assert job_input["company_name"] == "Acme"
    assert job_input["website"] is None


async def test_run_research_completes_row_with_reports(db_session, monkeypatch) -> None:
    async def fake_run_company_research(company_name, company_urls, on_query_done=None):
        assert company_name == "Acme"
        assert company_urls == ["https://acme.com/"]
        reports = []
        for i, slug in enumerate(["mission_and_core_purpose", "customers"], start=1):
            if on_query_done is not None:
                await on_query_done(i)
            reports.append({"slug": slug, "query": f"q{i}", "report": f"report {i}"})
        return reports

    monkeypatch.setattr("resumecraft.ai.researcher.run_company_research", fake_run_company_research)
    user_id = uuid.uuid4()
    research = await company_research_service.create_pending_research(
        db_session, user_id, "Acme", "https://acme.com/"
    )
    job = await _make_research_job(
        db_session, user_id=user_id, research_id=research.id, website="https://acme.com/"
    )
    calls, update_progress = await _progress_spy()

    result = await company_research_service.run_research(db_session, job, update_progress)

    stored = await db_session.get(CompanyResearch, research.id)
    assert stored is not None
    assert stored.status == ResearchStatus.COMPLETED
    assert stored.error is None
    assert stored.reports == [
        {"slug": "mission_and_core_purpose", "query": "q1", "report": "report 1"},
        {"slug": "customers", "query": "q2", "report": "report 2"},
    ]
    assert result == {"research_id": str(research.id)}
    # 0.1 at start, 0.1 + 0.8 * done/5 per completed query, 1.0 at the end.
    assert calls == pytest.approx([0.1, 0.26, 0.42, 1.0])


async def test_run_research_without_website_passes_no_sources(db_session, monkeypatch) -> None:
    seen_urls: list[list[str]] = []

    async def fake_run_company_research(company_name, company_urls, on_query_done=None):
        seen_urls.append(company_urls)
        return []

    monkeypatch.setattr("resumecraft.ai.researcher.run_company_research", fake_run_company_research)
    user_id = uuid.uuid4()
    research = await company_research_service.create_pending_research(
        db_session, user_id, "Acme", None
    )
    job = await _make_research_job(db_session, user_id=user_id, research_id=research.id)
    _, update_progress = await _progress_spy()

    await company_research_service.run_research(db_session, job, update_progress)

    assert seen_urls == [[]]

    stored = await db_session.get(CompanyResearch, research.id)
    assert stored is not None
    assert stored.status == ResearchStatus.COMPLETED
    assert stored.reports == []


async def test_run_research_failure_marks_row_failed(db_session, monkeypatch) -> None:
    async def broken_run_company_research(company_name, company_urls, on_query_done=None):
        raise RuntimeError("GPTResearcher exploded")

    monkeypatch.setattr(
        "resumecraft.ai.researcher.run_company_research", broken_run_company_research
    )
    user_id = uuid.uuid4()
    research = await company_research_service.create_pending_research(
        db_session, user_id, "Acme", None
    )
    job = await _make_research_job(db_session, user_id=user_id, research_id=research.id)
    _, update_progress = await _progress_spy()

    with pytest.raises(RuntimeError):
        await company_research_service.run_research(db_session, job, update_progress)

    stored = await db_session.get(CompanyResearch, research.id)
    assert stored is not None
    assert stored.status == ResearchStatus.FAILED
    assert stored.reports is None
    assert stored.error == "GPTResearcher exploded"


async def test_run_research_unknown_row_raises_not_found(db_session) -> None:
    job = await _make_research_job(db_session, user_id=uuid.uuid4(), research_id=uuid.uuid4())
    _, update_progress = await _progress_spy()

    with pytest.raises(NotFoundError):
        await company_research_service.run_research(db_session, job, update_progress)


async def test_get_research_scopes_to_user(db_session) -> None:
    research = await _seed_research(
        db_session, uuid.uuid4(), company_name="Mine", created_at=BASE_TIME
    )

    assert (
        await company_research_service.get_research_for_user(
            db_session, research.id, research.user_id
        )
    ).company_name == "Mine"
    with pytest.raises(NotFoundError):
        await company_research_service.get_research_for_user(db_session, research.id, uuid.uuid4())


async def test_list_researches_scopes_orders_and_excludes_deleted(db_session) -> None:
    user_id = uuid.uuid4()
    older = await _seed_research(db_session, user_id, company_name="Alpha", created_at=BASE_TIME)
    newer = await _seed_research(
        db_session, user_id, company_name="Beta", created_at=BASE_TIME + timedelta(minutes=1)
    )
    await _seed_research(
        db_session, uuid.uuid4(), company_name="Other user's", created_at=BASE_TIME
    )
    await _seed_research(
        db_session, user_id, company_name="Deleted", created_at=BASE_TIME, deleted=True
    )

    items, total = await company_research_service.list_researches(
        db_session, user_id, limit=10, offset=0
    )
    assert total == 2
    assert [r.id for r in items] == [newer.id, older.id]


async def test_list_researches_paginates_and_searches_name_ci(db_session) -> None:
    user_id = uuid.uuid4()
    await _seed_research(db_session, user_id, company_name="Acme", created_at=BASE_TIME)
    await _seed_research(
        db_session, user_id, company_name="Globex", created_at=BASE_TIME + timedelta(minutes=1)
    )

    page, total = await company_research_service.list_researches(
        db_session, user_id, limit=1, offset=1
    )
    assert total == 2
    assert [r.company_name for r in page] == ["Acme"]

    hits, total = await company_research_service.list_researches(
        db_session, user_id, limit=10, offset=0, search="GLOBEX"
    )
    assert total == 1
    assert [r.company_name for r in hits] == ["Globex"]


async def test_soft_delete_research_hides_but_keeps_row(db_session) -> None:
    research = await _seed_research(
        db_session, uuid.uuid4(), company_name="Doomed", created_at=BASE_TIME
    )

    await company_research_service.soft_delete_research(db_session, research.user_id, research.id)

    with pytest.raises(NotFoundError):
        await company_research_service.get_research_for_user(
            db_session, research.id, research.user_id
        )

    _, total = await company_research_service.list_researches(
        db_session, research.user_id, limit=10, offset=0
    )
    assert total == 0

    stored = await db_session.get(CompanyResearch, research.id)
    assert stored is not None
    assert stored.deleted_at is not None

    with pytest.raises(NotFoundError):
        await company_research_service.soft_delete_research(
            db_session, research.user_id, research.id
        )
