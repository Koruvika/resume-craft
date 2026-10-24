import uuid

from sqlalchemy import select

from resumecraft.core.enums import JobType
from resumecraft.db.models import Job, Resume
from resumecraft.schemas.parsed_resume import ContactInfo, ParsedResume
from resumecraft.schemas.resume import GenerateResumeRequest
from resumecraft.services import resume_service

REQUEST = GenerateResumeRequest(resume_text="x" * 60, target_role="Backend Engineer")


class FakeStructured:
    def with_structured_output(self, schema: type) -> "FakeStructured":
        assert schema is ParsedResume
        return self

    async def ainvoke(self, prompt: str) -> ParsedResume:
        assert "{resume_text}" not in prompt
        return ParsedResume(
            contact_info=ContactInfo(full_name="Jane Doe", headline="Senior Backend Engineer"),
            summary="Experienced engineer",
        )


async def _make_job(session, input_data: dict) -> Job:
    job = Job(user_id=uuid.uuid4(), type=JobType.GENERATE_RESUME, input=input_data)
    session.add(job)
    await session.flush()
    return job


async def _progress_spy() -> tuple[list[float], object]:
    calls: list[float] = []

    async def update_progress(progress: float) -> None:
        calls.append(progress)

    return calls, update_progress


async def test_generate_persists_parsed_resume(db_session, monkeypatch) -> None:
    monkeypatch.setattr(resume_service, "get_chat_model", lambda: FakeStructured())
    job = await _make_job(db_session, REQUEST.model_dump())
    calls, update_progress = await _progress_spy()

    parsed = await resume_service.generate(db_session, job, update_progress, REQUEST)

    assert parsed.contact_info.headline == "Senior Backend Engineer"
    assert calls == [0.2, 0.7, 1.0]

    result = await db_session.execute(select(Resume))
    resumes = result.scalars().all()
    assert len(resumes) == 1
    assert resumes[0].user_id == job.user_id
    assert resumes[0].title == "Senior Backend Engineer"
    assert resumes[0].content["contact_info"]["full_name"] == "Jane Doe"


async def test_generate_title_falls_back_to_target_role(db_session, monkeypatch) -> None:
    class EmptyModel:
        def with_structured_output(self, schema: type) -> "EmptyModel":
            return self

        async def ainvoke(self, prompt: str) -> ParsedResume:
            return ParsedResume(summary="s")

    monkeypatch.setattr(resume_service, "get_chat_model", lambda: EmptyModel())
    job = await _make_job(db_session, REQUEST.model_dump())
    _, update_progress = await _progress_spy()

    await resume_service.generate(db_session, job, update_progress, REQUEST)

    result = await db_session.execute(select(Resume))
    assert result.scalars().one().title == "Resume for Backend Engineer"


async def test_import_parsed_stores_resume(db_session) -> None:
    user_id = uuid.uuid4()
    parsed = ParsedResume(
        contact_info=ContactInfo(full_name="John Doe", headline="Platform Engineer"),
        summary="A summary",
    )

    resume = await resume_service.import_parsed(db_session, user_id, parsed)

    stored = await db_session.get(Resume, resume.id)
    assert stored is not None
    assert stored.user_id == user_id
    assert stored.title == "Platform Engineer"
    assert stored.content["summary"] == "A summary"


async def test_import_parsed_title_falls_back(db_session) -> None:
    resume = await resume_service.import_parsed(db_session, uuid.uuid4(), ParsedResume(summary="s"))
    assert resume.title == "Imported resume"


async def test_import_parsed_custom_title_wins(db_session) -> None:
    parsed = ParsedResume(
        contact_info=ContactInfo(full_name="John Doe", headline="Platform Engineer")
    )
    resume = await resume_service.import_parsed(
        db_session, uuid.uuid4(), parsed, title="Custom title"
    )
    assert resume.title == "Custom title"
