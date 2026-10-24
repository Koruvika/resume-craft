import uuid

from sqlalchemy import select

from resumecraft.core.enums import JobType
from resumecraft.db.models import Job, Resume
from resumecraft.schemas.resume import GeneratedResume, GenerateResumeRequest
from resumecraft.services import resume_service

REQUEST = GenerateResumeRequest(resume_text="x" * 60, target_role="Backend Engineer")


class FakeStructured:
    def with_structured_output(self, schema: type) -> "FakeStructured":
        return self

    async def ainvoke(self, prompt: str) -> GeneratedResume:
        assert "{resume_text}" not in prompt
        return GeneratedResume(
            title="Senior Backend Engineer",
            summary="Experienced engineer",
            highlights=["Built things", "Shipped stuff"],
            skills=["python", "fastapi"],
        )


async def test_generate_persists_resume_and_reports_progress(db_session, monkeypatch) -> None:
    monkeypatch.setattr(resume_service, "get_chat_model", lambda: FakeStructured())
    progress_calls: list[float] = []

    async def update_progress(progress: float) -> None:
        progress_calls.append(progress)

    job = Job(user_id=uuid.uuid4(), type=JobType.GENERATE_RESUME, input=REQUEST.model_dump())
    db_session.add(job)
    await db_session.flush()

    generated = await resume_service.generate(db_session, job, update_progress, REQUEST)

    assert generated.title == "Senior Backend Engineer"
    assert progress_calls == [0.2, 0.7, 1.0]

    result = await db_session.execute(select(Resume))
    resumes = result.scalars().all()
    assert len(resumes) == 1
    assert resumes[0].user_id == job.user_id
    assert resumes[0].content["title"] == "Senior Backend Engineer"
