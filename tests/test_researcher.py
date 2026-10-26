import asyncio
import sys
import time
import types
from types import SimpleNamespace

from resumecraft.ai import researcher


def _install_stub_gptr(
    monkeypatch,
    hang_queries: tuple[str, ...] = (),
    stall_once_queries: tuple[str, ...] = (),
) -> dict:
    """Replace gpt_researcher with a configurable stub.

    - hang_queries: matching queries sleep forever on every attempt.
    - stall_once_queries: matching queries sleep forever on the first
      attempt only, then complete — a transient provider stall.
    Returns a state dict with per-query attempt counts and the observed
    max number of conduct_research() calls in flight at once.
    """

    state: dict = {"attempt_counts": {}, "in_flight": 0, "max_in_flight": 0}

    class StubGPTResearcher:
        def __init__(
            self,
            query: str,
            report_type: str,
            source_urls: list,
            complement_source_urls: bool,
        ) -> None:
            self.query = query
            state["attempt_counts"][query] = state["attempt_counts"].get(query, 0) + 1

        async def conduct_research(self) -> None:
            state["in_flight"] += 1
            state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
            try:
                if any(q in self.query for q in hang_queries):
                    await asyncio.sleep(30)
                elif (
                    any(q in self.query for q in stall_once_queries)
                    and state["attempt_counts"][self.query] == 1
                ):
                    await asyncio.sleep(30)
                else:
                    await asyncio.sleep(0.05)
            finally:
                state["in_flight"] -= 1

        async def write_report(self) -> str:
            return f"REPORT for {self.query}"

    stub = types.ModuleType("gpt_researcher")
    stub.GPTResearcher = StubGPTResearcher  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gpt_researcher", stub)
    return state


def _patch_settings(monkeypatch, timeout: float, concurrency: int) -> None:
    monkeypatch.setattr(researcher, "_bridge_gptr_env", lambda: None)
    monkeypatch.setattr(
        researcher,
        "get_settings",
        lambda: SimpleNamespace(
            research_query_timeout=timeout, research_max_concurrency=concurrency
        ),
    )


def _by_slug(reports: list[dict]) -> dict[str, str]:
    return {r["slug"]: r["report"] for r in reports}


GOOD_SLUGS = (
    "mission_and_core_purpose",
    "products_and_services",
    "revenue_model",
    "engineering_culture_and_tech_stack",
)


async def test_hung_query_times_out_and_keeps_partial_results(monkeypatch) -> None:
    state = _install_stub_gptr(monkeypatch, hang_queries=("customers",))
    _patch_settings(monkeypatch, timeout=0.2, concurrency=2)

    done_counts: list[int] = []

    async def on_query_done(done: int) -> None:
        done_counts.append(done)

    start = time.monotonic()
    reports = await researcher.run_company_research(
        company_name="Anthropic", company_urls=[], on_query_done=on_query_done
    )
    elapsed = time.monotonic() - start

    assert elapsed < 3, f"hung query was not bounded: took {elapsed:.1f}s"
    assert len(reports) == 5
    assert sorted(done_counts) == [1, 2, 3, 4, 5]
    assert state["attempt_counts"]["Who are Anthropic's customers?"] == 2

    by_slug = _by_slug(reports)
    assert by_slug["customers"].startswith("ERROR: query timed out after 0.2s")
    for slug in GOOD_SLUGS:
        assert by_slug[slug].startswith("REPORT for"), slug


async def test_stalled_query_retries_once_and_completes(monkeypatch) -> None:
    state = _install_stub_gptr(monkeypatch, stall_once_queries=("customers",))
    _patch_settings(monkeypatch, timeout=0.2, concurrency=2)

    reports = await researcher.run_company_research(company_name="Anthropic", company_urls=[])

    assert state["attempt_counts"]["Who are Anthropic's customers?"] == 2
    by_slug = _by_slug(reports)
    for slug in ("customers", *GOOD_SLUGS):
        assert by_slug[slug].startswith("REPORT for"), slug


async def test_queries_run_at_bounded_concurrency(monkeypatch) -> None:
    state = _install_stub_gptr(monkeypatch)
    _patch_settings(monkeypatch, timeout=5, concurrency=2)

    reports = await researcher.run_company_research(company_name="Anthropic", company_urls=[])

    assert len(reports) == 5
    assert state["max_in_flight"] == 2, (
        f"expected max 2 concurrent queries, saw {state['max_in_flight']}"
    )
