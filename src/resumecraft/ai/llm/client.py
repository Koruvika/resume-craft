import httpx
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
        # httpx.Timeout (not a plain number) on purpose: langchain_openai
        # lru-caches its default async httpx client by (base_url, timeout) when
        # the timeout is hashable. One shared client binds its connections to
        # the first task's event loop, which asyncio.run() closes — the next
        # task in the same worker process then dies with "Event loop is
        # closed". A fresh, unhashable timeout forces a fresh client per task.
        timeout=httpx.Timeout(60),
        max_retries=2,
    )
