import base64
import json
import uuid

import pytest

from resumecraft.core.enums import JobType, ResumeStatus
from resumecraft.core.exceptions import (
    FileTooLargeError,
    InvalidResumeFileError,
    NotFoundError,
    UnsupportedFileTypeError,
)
from resumecraft.db.models import Job, Resume
from resumecraft.schemas.parsed_resume import ContactInfo, ParsedResume
from resumecraft.services import resume_service


async def _progress_spy() -> tuple[list[float], object]:
    calls: list[float] = []

    async def update_progress(progress: float) -> None:
        calls.append(progress)

    return calls, update_progress


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


FILE_BYTES = json.dumps(
    {"contact_info": {"full_name": "Jane Doe", "headline": "Staff Engineer"}}
).encode()


async def _make_parse_job(
    session,
    *,
    user_id: uuid.UUID,
    resume_id: uuid.UUID,
    source_type: str = "json",
    file_bytes: bytes | None = None,
    filename: str = "resume.json",
    title: str | None = None,
) -> Job:
    job = Job(
        user_id=user_id,
        type=JobType.PARSE_RESUME,
        input={
            "resume_id": str(resume_id),
            "source_type": source_type,
            "file_b64": base64.b64encode(file_bytes or FILE_BYTES).decode(),
            "filename": filename,
            "title": title,
        },
    )
    session.add(job)
    await session.flush()
    return job


async def test_create_pending_import_stores_shell(db_session) -> None:
    user_id = uuid.uuid4()
    resume = await resume_service.create_pending_import(
        db_session, user_id, source_type="json", raw=FILE_BYTES, filename="jane-doe.json"
    )

    stored = await db_session.get(Resume, resume.id)
    assert stored is not None
    assert stored.status == ResumeStatus.PENDING
    assert stored.content is None
    assert stored.title == "jane-doe"


async def test_create_pending_import_custom_title_wins(db_session) -> None:
    resume = await resume_service.create_pending_import(
        db_session,
        uuid.uuid4(),
        source_type="json",
        raw=FILE_BYTES,
        filename="resume.json",
        title="Custom title",
    )
    assert resume.title == "Custom title"


async def test_create_pending_import_rejects_content_type(db_session) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        resume_service.classify_upload("text/plain")


def test_classify_upload_accepts_json_and_pdf() -> None:
    assert resume_service.classify_upload("application/json") == "json"
    assert resume_service.classify_upload("application/PDF; charset=x") == "pdf"


async def test_create_pending_import_rejects_oversize_json(db_session, monkeypatch) -> None:
    monkeypatch.setattr(resume_service, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(FileTooLargeError):
        await resume_service.create_pending_import(
            db_session, uuid.uuid4(), source_type="json", raw=b"x" * 11, filename="r.json"
        )


async def test_create_pending_import_rejects_oversize_pdf(db_session, monkeypatch) -> None:
    monkeypatch.setattr(resume_service, "MAX_PDF_UPLOAD_BYTES", 10)
    with pytest.raises(FileTooLargeError):
        await resume_service.create_pending_import(
            db_session, uuid.uuid4(), source_type="pdf", raw=b"x" * 11, filename="r.pdf"
        )


async def test_parse_upload_json_completes_resume(db_session) -> None:
    user_id = uuid.uuid4()
    resume = await resume_service.create_pending_import(
        db_session, user_id, source_type="json", raw=FILE_BYTES, filename="resume.json"
    )
    job = await _make_parse_job(db_session, user_id=user_id, resume_id=resume.id)
    calls, update_progress = await _progress_spy()

    result = await resume_service.parse_upload(db_session, job, update_progress)

    stored = await db_session.get(Resume, resume.id)
    assert stored is not None
    assert stored.status == ResumeStatus.COMPLETED
    assert stored.error is None
    assert stored.content["contact_info"]["full_name"] == "Jane Doe"
    # No user title: the parsed headline replaces the filename stem.
    assert stored.title == "Staff Engineer"
    assert calls == [0.2, 0.8, 1.0]
    assert result == {"resume_id": str(resume.id)}


async def test_parse_upload_json_keeps_custom_title(db_session) -> None:
    user_id = uuid.uuid4()
    resume = await resume_service.create_pending_import(
        db_session,
        user_id,
        source_type="json",
        raw=FILE_BYTES,
        filename="resume.json",
        title="Keep me",
    )
    job = await _make_parse_job(db_session, user_id=user_id, resume_id=resume.id, title="Keep me")

    await resume_service.parse_upload(db_session, job, (await _progress_spy())[1])

    stored = await db_session.get(Resume, resume.id)
    assert stored is not None
    assert stored.title == "Keep me"


async def test_parse_upload_json_invalid_marks_resume_failed(db_session) -> None:
    user_id = uuid.uuid4()
    bad = b"{not json"
    resume = await resume_service.create_pending_import(
        db_session, user_id, source_type="json", raw=bad, filename="resume.json"
    )
    job = await _make_parse_job(db_session, user_id=user_id, resume_id=resume.id, file_bytes=bad)
    _, update_progress = await _progress_spy()

    with pytest.raises(InvalidResumeFileError):
        await resume_service.parse_upload(db_session, job, update_progress)

    stored = await db_session.get(Resume, resume.id)
    assert stored is not None
    assert stored.status == ResumeStatus.FAILED
    assert stored.content is None
    assert stored.error == "File is not valid JSON"


async def test_parse_upload_pdf_calls_parser_and_completes(db_session, monkeypatch) -> None:
    async def fake_parse_pdf(file_bytes, filename):
        assert file_bytes == b"%PDF-fake"
        assert filename == "resume.pdf"
        return ParsedResume(
            contact_info=ContactInfo(full_name="Jane Doe", headline="Staff Engineer")
        )

    monkeypatch.setattr(resume_service, "parse_pdf", fake_parse_pdf)
    user_id = uuid.uuid4()
    resume = await resume_service.create_pending_import(
        db_session, user_id, source_type="pdf", raw=b"%PDF-fake", filename="resume.pdf"
    )
    job = await _make_parse_job(
        db_session,
        user_id=user_id,
        resume_id=resume.id,
        source_type="pdf",
        file_bytes=b"%PDF-fake",
        filename="resume.pdf",
    )
    _, update_progress = await _progress_spy()

    await resume_service.parse_upload(db_session, job, update_progress)

    stored = await db_session.get(Resume, resume.id)
    assert stored is not None
    assert stored.status == ResumeStatus.COMPLETED
    assert stored.content["contact_info"]["full_name"] == "Jane Doe"
    assert stored.title == "Staff Engineer"


async def test_parse_upload_pdf_failure_marks_resume_failed(db_session, monkeypatch) -> None:
    async def broken_parse_pdf(file_bytes, filename):
        raise RuntimeError("LlamaCloud exploded")

    monkeypatch.setattr(resume_service, "parse_pdf", broken_parse_pdf)
    user_id = uuid.uuid4()
    resume = await resume_service.create_pending_import(
        db_session, user_id, source_type="pdf", raw=b"%PDF-fake", filename="resume.pdf"
    )
    job = await _make_parse_job(
        db_session,
        user_id=user_id,
        resume_id=resume.id,
        source_type="pdf",
        file_bytes=b"%PDF-fake",
        filename="resume.pdf",
    )
    _, update_progress = await _progress_spy()

    with pytest.raises(RuntimeError):
        await resume_service.parse_upload(db_session, job, update_progress)

    stored = await db_session.get(Resume, resume.id)
    assert stored is not None
    assert stored.status == ResumeStatus.FAILED
    assert stored.error == "LlamaCloud exploded"


async def test_parse_upload_unknown_resume_raises_not_found(db_session) -> None:
    user_id = uuid.uuid4()
    job = await _make_parse_job(db_session, user_id=user_id, resume_id=uuid.uuid4())
    _, update_progress = await _progress_spy()

    with pytest.raises(NotFoundError):
        await resume_service.parse_upload(db_session, job, update_progress)
