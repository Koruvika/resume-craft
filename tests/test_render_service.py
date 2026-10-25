import uuid

import pytest

from resumecraft.core.exceptions import InvalidRenderOptionError, NotFoundError, PdfRenderError
from resumecraft.schemas.parsed_resume import ParsedResume
from resumecraft.services import render_service, resume_service

SAMPLE_PARSED = ParsedResume.model_validate(
    {"contact_info": {"full_name": "Jane Doe", "headline": "Staff Engineer"}}
)


def _fake_pdf_bytes(monkeypatch, payload: bytes = b"%PDF-1.4 fake") -> None:
    def fake_generate(model, filename):
        assert model is not None
        return payload, filename

    monkeypatch.setattr(render_service, "generate_pdf_bytes", fake_generate)


async def test_render_resume_pdf_returns_bytes(db_session, monkeypatch) -> None:
    _fake_pdf_bytes(monkeypatch, b"%PDF-1.4 fake")
    resume = await resume_service.import_parsed(db_session, uuid.uuid4(), SAMPLE_PARSED)

    pdf_bytes, filename = await render_service.render_resume_pdf(
        db_session, resume.user_id, resume.id
    )

    assert pdf_bytes == b"%PDF-1.4 fake"
    assert filename == f"resume-{resume.id}.pdf"


async def test_render_resume_pdf_scopes_by_user(db_session, monkeypatch) -> None:
    _fake_pdf_bytes(monkeypatch)
    resume = await resume_service.import_parsed(db_session, uuid.uuid4(), SAMPLE_PARSED)

    with pytest.raises(NotFoundError) as exc_info:
        await render_service.render_resume_pdf(db_session, uuid.uuid4(), resume.id)
    assert exc_info.value.code == "resume_not_found"


async def test_render_resume_pdf_unknown_resume(db_session, monkeypatch) -> None:
    _fake_pdf_bytes(monkeypatch)

    with pytest.raises(NotFoundError):
        await render_service.render_resume_pdf(db_session, uuid.uuid4(), uuid.uuid4())


async def test_render_resume_pdf_rejects_unknown_theme(db_session, monkeypatch) -> None:
    _fake_pdf_bytes(monkeypatch)
    resume = await resume_service.import_parsed(db_session, uuid.uuid4(), SAMPLE_PARSED)

    with pytest.raises(InvalidRenderOptionError):
        await render_service.render_resume_pdf(db_session, resume.user_id, resume.id, theme="nope")


async def test_render_resume_pdf_wraps_pipeline_failures(db_session, monkeypatch) -> None:
    def broken_generate(model, filename):
        raise RuntimeError("typst exploded")

    monkeypatch.setattr(render_service, "generate_pdf_bytes", broken_generate)
    resume = await resume_service.import_parsed(db_session, uuid.uuid4(), SAMPLE_PARSED)

    with pytest.raises(PdfRenderError) as exc_info:
        await render_service.render_resume_pdf(db_session, resume.user_id, resume.id)
    assert exc_info.value.code == "pdf_render_failed"
    assert isinstance(exc_info.value.__cause__, RuntimeError)


@pytest.mark.render
async def test_generate_pdf_bytes_renders_real_pdf() -> None:
    """Runs the real rendercv/typst pipeline (excluded from the default suite)."""
    from resumecraft.rendering import (
        build_rendercv_model,
        generate_pdf_bytes,
        parsed_resume_to_rendercv,
        validate_render_options,
    )

    model = build_rendercv_model(
        parsed_resume_to_rendercv(SAMPLE_PARSED), validate_render_options(None, None)
    )
    pdf_bytes, filename = generate_pdf_bytes(model, "smoke.pdf")

    assert filename == "smoke.pdf"
    assert pdf_bytes.startswith(b"%PDF-")


async def test_render_resume_pdf_rejects_pending_resume(db_session) -> None:
    from resumecraft.core.enums import ResumeStatus
    from resumecraft.core.exceptions import ResumeNotReadyError
    from resumecraft.db.models import Resume

    resume = Resume(user_id=uuid.uuid4(), title="Pending", status=ResumeStatus.PENDING)
    db_session.add(resume)
    await db_session.flush()

    with pytest.raises(ResumeNotReadyError) as exc_info:
        await render_service.render_resume_pdf(db_session, resume.user_id, resume.id)
    assert exc_info.value.details["status"] == "pending"
