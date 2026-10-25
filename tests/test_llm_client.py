import pytest

from resumecraft.ai.llm.client import get_chat_model
from resumecraft.core.config import Settings
from resumecraft.schemas.parsed_resume import ParsedResume


def test_get_chat_model_returns_configured_chat_openai() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        openai_base_url="http://localhost:4000/v1",
        llm_model="test-model",
    )
    model = get_chat_model(settings)
    assert model.model_name == "test-model"


def test_get_chat_model_builds_fresh_http_client_per_instance() -> None:
    """langchain lru-caches its default async client when timeout is hashable;
    a shared client binds to the first task's (closed) event loop and kills
    every later task in the same worker process with "Event loop is closed"."""
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        openai_base_url="http://localhost:4000/v1",
        llm_model="test-model",
    )
    first = get_chat_model(settings)
    second = get_chat_model(settings)
    assert first.root_async_client is not None
    assert second.root_async_client is not None
    # The httpx client each AsyncOpenAI wraps must be distinct.
    assert first.root_async_client._client is not second.root_async_client._client


def test_get_chat_model_requires_api_key() -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(ValueError, match="RC_OPENAI_API_KEY"):
        get_chat_model(settings)


def test_parsed_resume_round_trip() -> None:
    data = {
        "contact_info": {"full_name": "Jane Doe", "headline": "Staff Engineer"},
        "summary": "Experienced",
        "skills": {"groups": [{"category": "Languages", "skills": ["python"]}]},
    }
    parsed = ParsedResume.model_validate(data)
    assert parsed.contact_info.full_name == "Jane Doe"
    assert parsed.model_dump()["contact_info"]["full_name"] == "Jane Doe"


def test_skills_section_normalizes_flat_list() -> None:
    parsed = ParsedResume.model_validate({"skills": ["python", "LLM: GenAI, RAG"]})
    groups = parsed.skills.groups
    assert (groups[0].category, groups[0].skills) == ("LLM", ["GenAI", "RAG"])
    assert (groups[1].category, groups[1].skills) == (None, ["python"])
