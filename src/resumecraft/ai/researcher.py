"""Company research via GPTResearcher, ported from resumebloom's
agents/v3/researcher/agent.py.

The heavy `gpt_researcher` import and the env bridge run lazily inside
run_company_research, so importing this module from the API process stays
cheap — only the worker actually pays. resumebloom's sync-search
monkey-patch is deliberately NOT ported: the gpt-researcher version we
install fixed the blocking retriever.search() call upstream with
asyncio.to_thread, and the old patch's signature now collides with the
upstream `max_results` keyword.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable

ProgressCallback = Callable[[int], Awaitable[None]]

QUERY_TEMPLATES = [
    "What is the mission and core purpose of {company_name}?",
    "What products and services does {company_name} offer?",
    "Who are {company_name}'s customers?",
    "How does {company_name} generate revenue?",
    "What engineering culture and technology stack does {company_name} appear to use?",
]

QUERY_SLUGS = [
    "mission_and_core_purpose",
    "products_and_services",
    "customers",
    "revenue_model",
    "engineering_culture_and_tech_stack",
]

COMMON_PATHS = ["/about", "/about-us", "/careers", "/products", "/blog"]


def build_source_urls(website: str | None) -> list[str]:
    if not website:
        return []
    base = website.rstrip("/")
    urls = [base]
    for path in COMMON_PATHS:
        urls.append(f"{base}{path}")
    return urls


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug


def _bridge_gptr_env() -> None:
    """Map RC_ settings into the env vars gpt_researcher / langchain read.

    GPTResearcher's Config reads FAST_LLM/SMART_LLM/STRATEGIC_LLM as
    '<provider>:<model>' and instantiates langchain_openai.ChatOpenAI for the
    'openai' provider, which reads OPENAI_API_KEY / OPENAI_BASE_URL. Our app
    configures the LLM only via RC_OPENAI_* consumed by get_chat_model(); this
    bridge exposes the same values to the 3rd-party lib without coupling the
    app code to it. setdefault: never clobbers an operator-set real OPENAI_*.
    All three tiers share RC_LLM_MODEL — GPTResearcher needs three names, not
    three different models.

    ponytail: the gateway speaks the OpenAI schema, so the 'openai' provider
    prefix is correct regardless of the underlying model family name.
    """
    import os

    from resumecraft.core.config import get_settings

    settings = get_settings()
    if settings.openai_api_key is not None:
        os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key.get_secret_value())
    if settings.openai_base_url:
        os.environ.setdefault("OPENAI_BASE_URL", settings.openai_base_url)
    os.environ.setdefault("FAST_LLM", f"openai:{settings.llm_model}")
    os.environ.setdefault("SMART_LLM", f"openai:{settings.llm_model}")
    os.environ.setdefault("STRATEGIC_LLM", f"openai:{settings.llm_model}")
    os.environ.setdefault("EMBEDDING", settings.embedding_model)
    if settings.tavily_api_key is not None:
        os.environ.setdefault("TAVILY_API_KEY", settings.tavily_api_key.get_secret_value())
    retriever = "tavily" if os.environ.get("TAVILY_API_KEY") else "duckduckgo"
    os.environ.setdefault("RETRIEVER", retriever)


async def run_company_research(
    company_name: str,
    company_urls: list[str],
    on_query_done: ProgressCallback | None = None,
) -> list[dict]:
    """Run the fixed query set against GPTResearcher and return one
    {slug, query, report} dict per query, in QUERY_SLUGS order.

    GPTResearcher is imported lazily (with its env bridge and sync-search
    patch) so only the worker process loads the heavy dependency.
    Per-query failures surface as a report of 'ERROR: <cause>' — the caller
    decides whether partial results are worth keeping.
    """
    from gpt_researcher import GPTResearcher

    _bridge_gptr_env()

    sources: list[str] = []
    for url in company_urls:
        sources += build_source_urls(url)

    done_count = 0

    async def _run_single(query: str, slug: str) -> dict:
        nonlocal done_count
        try:
            researcher = GPTResearcher(
                query=query,
                report_type="research_report",
                source_urls=sources,
                complement_source_urls=True,
            )
            await researcher.conduct_research()
            report = await researcher.write_report()
        except Exception as e:
            report = f"ERROR: {e}"
        done_count += 1
        if on_query_done is not None:
            await on_query_done(done_count)
        return {"slug": slug, "query": query, "report": report}

    tasks = [
        _run_single(template.format(company_name=company_name), slug)
        for template, slug in zip(QUERY_TEMPLATES, QUERY_SLUGS, strict=True)
    ]
    return list(await asyncio.gather(*tasks))
