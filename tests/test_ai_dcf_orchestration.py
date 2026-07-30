"""
Agentic AI DCF Valuator — orchestration/caching/status/cancel unit tests (Phase 5).

Covers api/ai_dcf_router.py's DuckDB cache, background-task registry, live status,
cancel/retry-after-cancel guard, and get_or_run_ai_dcf's cache-aware/join-in-flight-task
behavior. `run_ai_dcf` (the actual LLM pipeline) is always monkeypatched here — these tests
exercise the scaffolding around it, not the pipeline itself (already covered end-to-end by
Phase 4's tests and live checks).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import duckdb
import pytest

import api.ai_dcf_router as adr


@pytest.fixture(autouse=True)
def _clean_module_state(tmp_path, monkeypatch):
    """Every test gets an isolated cache file and a clean background-task/status registry —
    these are module-level globals in the real router, so leaking state between tests would
    make results order-dependent."""
    monkeypatch.setattr(adr, "_AI_DCF_DB", tmp_path / "ai_dcf_cache.duckdb")
    adr._background_tasks.clear()
    adr._task_status.clear()
    yield
    adr._background_tasks.clear()
    adr._task_status.clear()


def _fixture_scenario():
    return adr.ScenarioAssumptions(
        revenue_growth=[0.10, 0.09, 0.08, 0.07, 0.06],
        cogs_pct=[0.40] * 5, ebit_margin_pct=[0.20] * 5, capex_pct_revenue=[0.05] * 5,
        terminal_growth_rate=0.025, rationale="test rationale",
    )


def _fixture_result_for(ticker="TXN", model="some-model"):
    """Minimal but fully valid AiDcfResult for cache/status-layer tests — Phase 5 exercises the
    scaffolding around the pipeline, not the pipeline's own numbers (already covered in
    tests/test_ai_dcf.py), so a bear/base/bull-of-None engine result is fine here."""
    assumptions = adr.AiDcfAssumptions(
        bear=_fixture_scenario(), base=_fixture_scenario(), bull=_fixture_scenario(),
        wacc_rationale="test WACC rationale", key_debates=["debate one"],
    )
    fb = adr.FundamentalsBrief(
        growth_history="g", margin_history="m", capital_intensity="c",
        working_capital="w", cyclicality_assessment="cy", sustainable_ranges="s",
    )
    ib = adr.IndustryBrief(
        industry_growth_outlook="g", pricing_margin_direction="p", capex_cycle="c",
        competitive_position="cp", terminal_context="t", used_industry_report=False,
    )
    gb = adr.GuidanceBrief(
        explicit_guidance="e", strategy_shifts="s", demand_inflections="d",
        guidance_credibility="gc", consensus_view="cv",
    )
    return adr.AiDcfResult.build(
        ticker=ticker, model=model, assumptions=assumptions,
        fundamentals_brief=fb, industry_brief=ib, guidance_brief=gb,
        engine_results={"bear": None, "base": None, "bull": None},
        qc_warnings=[], inputs_available={},
    )


# ---------------------------------------------------------------------------
# Cache get/put + TTL
# ---------------------------------------------------------------------------

def test_cache_roundtrip():
    result = _fixture_result_for()
    adr._ai_dcf_cache_put("TXN", "some-model", result.to_json(), "# report markdown")
    cached = adr._ai_dcf_cache_get("TXN", "some-model")
    assert cached is not None
    result_json, markdown = cached
    assert markdown == "# report markdown"
    assert adr.AiDcfResult.from_json(result_json).ticker == "TXN"


def test_cache_miss_returns_none():
    assert adr._ai_dcf_cache_get("NONEXISTENT", "some-model") is None


def test_cache_distinguishes_by_model():
    result = _fixture_result_for()
    adr._ai_dcf_cache_put("TXN", "model-a", result.to_json(), "report A")
    assert adr._ai_dcf_cache_get("TXN", "model-b") is None


def test_cache_ttl_expiry():
    adr._init_ai_dcf_cache()
    stale = datetime.now() - timedelta(hours=adr._AI_DCF_CACHE_TTL_HOURS + 1)
    conn = duckdb.connect(str(adr._AI_DCF_DB))
    conn.execute(
        "INSERT INTO ai_dcf_cache (ticker, model, result_json, report_markdown, generated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ["TXN", "some-model", "{}", "stale report", stale],
    )
    conn.close()
    assert adr._ai_dcf_cache_get("TXN", "some-model") is None


def test_cache_within_ttl_returned():
    adr._init_ai_dcf_cache()
    fresh = datetime.now() - timedelta(hours=1)
    conn = duckdb.connect(str(adr._AI_DCF_DB))
    conn.execute(
        "INSERT INTO ai_dcf_cache (ticker, model, result_json, report_markdown, generated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ["TXN", "some-model", "{}", "fresh report", fresh],
    )
    conn.close()
    cached = adr._ai_dcf_cache_get("TXN", "some-model")
    assert cached is not None
    assert cached[1] == "fresh report"


# ---------------------------------------------------------------------------
# _get_or_start_ai_dcf — status transitions, cancel, retry-after-cancel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_start_returns_cached_immediately_no_task_spawned(monkeypatch):
    result = _fixture_result_for()
    adr._ai_dcf_cache_put("TXN", "some-model", result.to_json(), "# cached report")

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("run_ai_dcf should not be called when cache hits")
    monkeypatch.setattr(adr, "run_ai_dcf", fail_if_called)

    result_md = adr._get_or_start_ai_dcf("TXN", "some-model")
    assert result_md == "# cached report"
    assert adr._background_tasks == {}


@pytest.mark.asyncio
async def test_get_or_start_spawns_background_task_and_eventually_caches(monkeypatch):
    async def fake_run(ticker, model, status_cb=None):
        if status_cb:
            status_cb("gathering_data", "working...")
        await asyncio.sleep(0)
        return _fixture_result_for(ticker, model)
    monkeypatch.setattr(adr, "run_ai_dcf", fake_run)

    first = adr._get_or_start_ai_dcf("TXN", "some-model")
    assert "Generating AI DCF Valuation for TXN" in first
    key = ("TXN", "some-model")
    assert key in adr._background_tasks

    await adr._background_tasks[key]  # let the background task run to completion
    assert adr._task_status[key]["phase"] == "done"
    cached = adr._ai_dcf_cache_get("TXN", "some-model")
    assert cached is not None

    # A subsequent call now serves from cache
    second = adr._get_or_start_ai_dcf("TXN", "some-model")
    assert second == cached[1]


@pytest.mark.asyncio
async def test_error_status_blocks_auto_restart_until_explicit_retry(monkeypatch):
    call_count = 0

    async def failing_run(ticker, model, status_cb=None):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("provider exploded")
    monkeypatch.setattr(adr, "run_ai_dcf", failing_run)

    adr._get_or_start_ai_dcf("TXN", "some-model")
    key = ("TXN", "some-model")
    await adr._background_tasks[key]
    assert adr._task_status[key]["phase"] == "error"
    assert call_count == 1

    # Polling again WITHOUT retry must not silently restart generation
    adr._get_or_start_ai_dcf("TXN", "some-model")
    assert call_count == 1
    assert key not in adr._background_tasks or adr._background_tasks[key].done()

    # Polling WITH retry=True must restart generation
    adr._get_or_start_ai_dcf("TXN", "some-model", retry=True)
    await adr._background_tasks[key]
    assert call_count == 2


@pytest.mark.asyncio
async def test_cancel_running_task_sets_cancelled_status(monkeypatch):
    started = asyncio.Event()

    async def slow_run(ticker, model, status_cb=None):
        started.set()
        await asyncio.sleep(10)
        return _fixture_result_for(ticker, model)
    monkeypatch.setattr(adr, "run_ai_dcf", slow_run)

    adr._get_or_start_ai_dcf("TXN", "some-model")
    key = ("TXN", "some-model")
    await started.wait()

    result = await adr.ai_dcf_cancel(ticker="TXN", model="some-model")
    assert result == {"status": "cancelled"}

    with pytest.raises(asyncio.CancelledError):
        await adr._background_tasks[key]
    assert adr._task_status[key]["phase"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_when_nothing_running_returns_not_running():
    result = await adr.ai_dcf_cancel(ticker="TXN", model="some-model")
    assert result == {"status": "not_running"}


# ---------------------------------------------------------------------------
# get_or_run_ai_dcf — cache-aware, joins in-flight tasks instead of double-starting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_run_ai_dcf_returns_cached_without_calling_run(monkeypatch):
    result = _fixture_result_for()
    adr._ai_dcf_cache_put("TXN", "some-model", result.to_json(), "# cached")

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("run_ai_dcf should not be called on a cache hit")
    monkeypatch.setattr(adr, "run_ai_dcf", fail_if_called)

    got = await adr.get_or_run_ai_dcf("TXN", "some-model")
    assert got is not None
    assert got.ticker == "TXN"


@pytest.mark.asyncio
async def test_get_or_run_ai_dcf_starts_and_awaits_new_run(monkeypatch):
    async def fake_run(ticker, model, status_cb=None):
        await asyncio.sleep(0)
        return _fixture_result_for(ticker, model)
    monkeypatch.setattr(adr, "run_ai_dcf", fake_run)

    got = await adr.get_or_run_ai_dcf("TXN", "some-model")
    assert got is not None
    assert got.ticker == "TXN"
    assert adr._ai_dcf_cache_get("TXN", "some-model") is not None


@pytest.mark.asyncio
async def test_get_or_run_ai_dcf_returns_none_on_failure(monkeypatch):
    async def failing_run(ticker, model, status_cb=None):
        raise RuntimeError("boom")
    monkeypatch.setattr(adr, "run_ai_dcf", failing_run)

    got = await adr.get_or_run_ai_dcf("TXN", "some-model")
    assert got is None


@pytest.mark.asyncio
async def test_get_or_run_ai_dcf_joins_in_flight_task_instead_of_double_starting(monkeypatch):
    """The critical concurrency guarantee (SPEC PLAN 5.2/5.4): if a run is already in flight
    (started by the standalone endpoint, or by a concurrent caller), a second caller must join
    that SAME task rather than triggering a second orchestrator invocation."""
    call_count = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_run(ticker, model, status_cb=None):
        nonlocal call_count
        call_count += 1
        started.set()
        await release.wait()
        return _fixture_result_for(ticker, model)
    monkeypatch.setattr(adr, "run_ai_dcf", slow_run)

    # First caller starts the run (via the standalone get-or-start path).
    adr._get_or_start_ai_dcf("TXN", "some-model")
    await started.wait()
    assert call_count == 1

    # A second, concurrent caller via the in-process path must join the SAME task.
    joiner_task = asyncio.create_task(adr.get_or_run_ai_dcf("TXN", "some-model"))
    await asyncio.sleep(0)  # let the joiner reach the "await existing" point
    release.set()

    joined_result = await joiner_task
    assert joined_result is not None
    assert call_count == 1  # never started a second orchestrator run
