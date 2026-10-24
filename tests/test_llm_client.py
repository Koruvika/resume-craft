import pytest

from resumecraft.ai.llm.client import get_chat_model
from resumecraft.core.config import Settings
from resumecraft.prompts.resume import GENERATE_RESUME_PROMPT
from resumecraft.schemas.resume import GeneratedResume, GenerateResumeRequest


def test_get_chat_model_returns_configured_chat_openai() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        openai_base_url="http://localhost:4000/v1",
        llm_model="test-model",
    )
    model = get_chat_model(settings)
    assert model.model_name == "test-model"


def test_get_chat_model_requires_api_key() -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(ValueError, match="RC_OPENAI_API_KEY"):
        get_chat_model(settings)


def test_generate_resume_request_min_lengths() -> None:
    with pytest.raises(ValueError):
        GenerateResumeRequest(resume_text="short", target_role="x")


def test_prompt_formats_without_leftover_placeholders() -> None:
    formatted = GENERATE_RESUME_PROMPT.format(resume_text="my resume", target_role="SWE")
    assert "{resume_text}" not in formatted
    assert "{target_role}" not in formatted
    assert "my resume" in formatted


def test_generated_resume_round_trip() -> None:
    data = {
        "title": "Senior Backend Engineer",
        "summary": "Experienced",
        "highlights": ["a", "b"],
        "skills": ["python"],
    }
    assert GeneratedResume.model_validate(data).model_dump() == data
