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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Acme", "acme"),
        ("  ACME,  Inc. ", "acme"),
        ("Acme Corporation", "acme"),
        ("Société Générale S.A.", "societe generale"),
        ("Procter & Gamble Co.", "procter and gamble"),
        ("Acme Holdings Ltd", "acme holdings"),
        # Never strip a name down to nothing.
        ("Inc.", "inc"),
    ],
)
def test_normalize_company_name(raw: str, expected: str) -> None:
    assert company_research_service.normalize_company_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://acme.com/", "acme.com"),
        ("http://WWW.Acme.com", "acme.com"),
        ("https://www.acme.com:443/about?x=1#top", "acme.com"),
        ("https://careers.acme.com/", "careers.acme.com"),
        (None, None),
    ],
)
def test_normalize_website(raw: str | None, expected: str | None) -> None:
    assert company_research_service.normalize_website(raw) == expected


async def _seed_dedup_candidate(
    session,
    user_id: uuid.UUID,
    *,
    company_name: str = "Acme Inc.",
    website: str | None = "https://acme.com/",
    status: ResearchStatus = ResearchStatus.COMPLETED,
    age: timedelta = timedelta(days=1),
    deleted: bool = False,
    with_job: bool = True,
) -> tuple[CompanyResearch, Job | None]:
    created_at = datetime.now(UTC) - age
    research = CompanyResearch(
        user_id=user_id,
        company_name=company_name,
        website=website,
        status=status,
        created_at=created_at,
        deleted_at=created_at if deleted else None,
    )
    await research_repo.create(session, research)
    job = None
    if with_job:
        job = await _make_research_job(
            session,
            user_id=user_id,
            research_id=research.id,
            company_name=company_name,
            website=website,
        )
    await session.commit()
    return research, job


async def test_find_duplicate_matches_similar_name_and_same_website(db_session) -> None:
    user_id = uuid.uuid4()
    research, job = await _seed_dedup_candidate(db_session, user_id)

    found = await company_research_service.find_duplicate_research(
        db_session, user_id, "ACME", "http://www.acme.com"
    )

    assert found is not None
    assert found[0].id == research.id
    assert job is not None and found[1].id == job.id


async def test_find_duplicate_tolerates_typos_in_name(db_session) -> None:
    user_id = uuid.uuid4()
    research, _ = await _seed_dedup_candidate(db_session, user_id, company_name="Microsoft")

    found = await company_research_service.find_duplicate_research(
        db_session, user_id, "Microsfot Corp", "https://acme.com/"
    )

    assert found is not None and found[0].id == research.id


async def test_find_duplicate_name_alone_decides_when_a_website_is_missing(db_session) -> None:
    user_id = uuid.uuid4()
    with_site, _ = await _seed_dedup_candidate(db_session, user_id)

    found = await company_research_service.find_duplicate_research(
        db_session, user_id, "Acme", None
    )
    assert found is not None and found[0].id == with_site.id

    other_user = uuid.uuid4()
    without_site, _ = await _seed_dedup_candidate(db_session, other_user, website=None)
    found = await company_research_service.find_duplicate_research(
        db_session, other_user, "Acme", "https://acme.com/"
    )
    assert found is not None and found[0].id == without_site.id


async def test_find_duplicate_requires_both_name_and_website(db_session) -> None:
    user_id = uuid.uuid4()
    await _seed_dedup_candidate(db_session, user_id)

    different_site = await company_research_service.find_duplicate_research(
        db_session, user_id, "Acme", "https://acme.io/"
    )
    different_name = await company_research_service.find_duplicate_research(
        db_session, user_id, "Globex", "https://acme.com/"
    )

    assert different_site is None
    assert different_name is None


async def test_find_duplicate_rejects_prefix_only_names(db_session) -> None:
    user_id = uuid.uuid4()
    await _seed_dedup_candidate(db_session, user_id, company_name="Apple", website=None)

    found = await company_research_service.find_duplicate_research(
        db_session, user_id, "Apple Music", None
    )

    assert found is None


@pytest.mark.parametrize(
    "candidate",
    [
        {"status": ResearchStatus.FAILED},
        {"age": timedelta(days=31)},
        {"deleted": True},
        {"with_job": False},
    ],
    ids=["failed", "older-than-window", "soft-deleted", "no-job"],
)
async def test_find_duplicate_ignores_ineligible_rows(db_session, candidate) -> None:
    user_id = uuid.uuid4()
    await _seed_dedup_candidate(db_session, user_id, **candidate)

    found = await company_research_service.find_duplicate_research(
        db_session, user_id, "Acme", "https://acme.com/"
    )

    assert found is None


@pytest.mark.parametrize("status", [ResearchStatus.PENDING, ResearchStatus.PROCESSING])
async def test_find_duplicate_counts_in_flight_research(db_session, status) -> None:
    user_id = uuid.uuid4()
    research, _ = await _seed_dedup_candidate(db_session, user_id, status=status)

    found = await company_research_service.find_duplicate_research(
        db_session, user_id, "Acme", "https://acme.com/"
    )

    assert found is not None and found[0].id == research.id


async def test_find_duplicate_scopes_to_user(db_session) -> None:
    await _seed_dedup_candidate(db_session, uuid.uuid4())

    found = await company_research_service.find_duplicate_research(
        db_session, uuid.uuid4(), "Acme", "https://acme.com/"
    )

    assert found is None


async def test_find_duplicate_returns_latest_match(db_session) -> None:
    user_id = uuid.uuid4()
    await _seed_dedup_candidate(db_session, user_id, age=timedelta(days=10))
    newest, _ = await _seed_dedup_candidate(db_session, user_id, age=timedelta(days=2))

    found = await company_research_service.find_duplicate_research(
        db_session, user_id, "Acme", "https://acme.com/"
    )

    assert found is not None and found[0].id == newest.id
