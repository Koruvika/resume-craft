from langchain_openai import ChatOpenAI

from resumecraft.core.config import Settings, get_settings


def get_chat_model(settings: Settings | None = None) -> ChatOpenAI:
    """Build a ChatOpenAI against any OpenAI-compatible endpoint from settings."""
    settings = settings or get_settings()
    if settings.openai_api_key is None:
        raise ValueError("RC_OPENAI_API_KEY is not set")
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=60,
        max_retries=2,
    )
