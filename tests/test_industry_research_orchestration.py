"""
Industry AI Researcher — orchestration/caching/status/cancel unit tests (Phase 5).

Covers api/industry_research_router.py's DuckDB cache, background-task registry, live status,
and cancel/retry-after-cancel guard. `_run_industry_research` (the actual LLM pipeline) is always
monkeypatched here — these tests exercise the scaffolding around it, not the pipeline itself
(already covered end-to-end by Phases 3-4's tests and a live smoke test).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import duckdb
import pytest

import api.industry_research_router as rr


@pytest.fixture(autouse=True)
def _clean_module_state(tmp_path, monkeypatch):
    """Every test gets an isolated cache file and a clean background-task/status registry —
    these are module-level globals in the real router, so leaking state between tests would
    make results order-dependent."""
    monkeypatch.setattr(rr, "_INDUSTRY_RESEARCH_DB", tmp_path / "industry_research_cache.duckdb")
    rr._background_tasks.clear()
    rr._task_status.clear()
    yield
    rr._background_tasks.clear()
    rr._task_status.clear()


# ---------------------------------------------------------------------------
# Cache get/put + TTL
# ---------------------------------------------------------------------------

def test_cache_roundtrip():
    rr._cache_put("SEMICONDUCTORS", "some-model", "# report content")
    assert rr._cache_get("SEMICONDUCTORS", "some-model") == "# report content"


def test_cache_miss_returns_none():
    assert rr._cache_get("NONEXISTENT", "some-model") is None


def test_cache_distinguishes_by_model():
    rr._cache_put("SEMICONDUCTORS", "model-a", "report A")
    assert rr._cache_get("SEMICONDUCTORS", "model-b") is None


def test_cache_ttl_expiry():
    rr._init_cache()
    stale = datetime.now() - timedelta(hours=rr._CACHE_TTL_HOURS + 1)
    conn = duckdb.connect(str(rr._INDUSTRY_RESEARCH_DB))
    conn.execute(
        "INSERT INTO industry_research_cache (scope_key, model, report_markdown, generated_at) "
        "VALUES (?, ?, ?, ?)",
        ["SEMICONDUCTORS", "some-model", "stale report", stale],
    )
    conn.close()
    assert rr._cache_get("SEMICONDUCTORS", "some-model") is None


def test_cache_within_ttl_returned():
    rr._init_cache()
    fresh = datetime.now() - timedelta(hours=1)
    conn = duckdb.connect(str(rr._INDUSTRY_RESEARCH_DB))
    conn.execute(
        "INSERT INTO industry_research_cache (scope_key, model, report_markdown, generated_at) "
        "VALUES (?, ?, ?, ?)",
        ["SEMICONDUCTORS", "some-model", "fresh report", fresh],
    )
    conn.close()
    assert rr._cache_get("SEMICONDUCTORS", "some-model") == "fresh report"


# ---------------------------------------------------------------------------
# _get_or_start / _background_generate — status transitions, cancel, retry-after-cancel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_start_returns_cached_immediately_no_task_spawned(monkeypatch):
    rr._cache_put("SEMICONDUCTORS", "some-model", "# cached report")

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("_run_industry_research should not be called when cache hits")
    monkeypatch.setattr(rr, "_run_industry_research", fail_if_called)

    result = rr._get_or_start("Semiconductors", None, "some-model")
    assert result == "# cached report"
    assert rr._background_tasks == {}


@pytest.mark.asyncio
async def test_get_or_start_spawns_background_task_and_eventually_caches(monkeypatch):
    async def fake_run(industry, custom_tickers, model, status_key=None):
        if status_key:
            rr._set_status(status_key, "gathering_data", "working...")
        await asyncio.sleep(0)
        return "# freshly generated report"
    monkeypatch.setattr(rr, "_run_industry_research", fake_run)

    first = rr._get_or_start("Semiconductors", None, "some-model")
    assert first == rr._GENERATING_MD
    key = (rr.ind.scope_key("Semiconductors"), "some-model")
    assert key in rr._background_tasks

    await rr._background_tasks[key]  # let the background task run to completion
    assert rr._task_status[key]["phase"] == "done"
    assert rr._cache_get("SEMICONDUCTORS", "some-model") == "# freshly generated report"

    # A subsequent call now serves from cache
    second = rr._get_or_start("Semiconductors", None, "some-model")
    assert second == "# freshly generated report"


@pytest.mark.asyncio
async def test_error_status_blocks_auto_restart_until_explicit_retry(monkeypatch):
    call_count = 0

    async def failing_run(industry, custom_tickers, model, status_key=None):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("provider exploded")
    monkeypatch.setattr(rr, "_run_industry_research", failing_run)

    rr._get_or_start("Semiconductors", None, "some-model")
    key = (rr.ind.scope_key("Semiconductors"), "some-model")
    await rr._background_tasks[key]
    assert rr._task_status[key]["phase"] == "error"
    assert call_count == 1

    # Polling again WITHOUT retry must not silently restart generation
    rr._get_or_start("Semiconductors", None, "some-model")
    assert call_count == 1
    assert key not in rr._background_tasks or rr._background_tasks[key].done()

    # Polling WITH retry=True must restart generation
    rr._get_or_start("Semiconductors", None, "some-model", retry=True)
    await rr._background_tasks[key]
    assert call_count == 2


@pytest.mark.asyncio
async def test_cancel_running_task_sets_cancelled_status(monkeypatch):
    started = asyncio.Event()

    async def slow_run(industry, custom_tickers, model, status_key=None):
        started.set()
        await asyncio.sleep(10)
        return "# should not complete"
    monkeypatch.setattr(rr, "_run_industry_research", slow_run)

    rr._get_or_start("Semiconductors", None, "some-model")
    key = (rr.ind.scope_key("Semiconductors"), "some-model")
    await started.wait()

    result = await rr.industry_research_cancel(industry="Semiconductors", tickers=None, model="some-model")
    assert result == {"status": "cancelled"}

    with pytest.raises(asyncio.CancelledError):
        await rr._background_tasks[key]
    assert rr._task_status[key]["phase"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_when_nothing_running_returns_not_running():
    result = await rr.industry_research_cancel(industry="Semiconductors", tickers=None, model="some-model")
    assert result == {"status": "not_running"}


# ---------------------------------------------------------------------------
# Custom ticker basket bypasses classification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_report_endpoint_custom_tickers_bypasses_classification(monkeypatch):
    captured = {}

    async def fake_run(industry, custom_tickers, model, status_key=None):
        captured["industry"] = industry
        captured["custom_tickers"] = custom_tickers
        return "# custom basket report"
    monkeypatch.setattr(rr, "_run_industry_research", fake_run)

    result = await rr.industry_research_report(industry=None, tickers="nvda, amd", model="some-model")
    key = (rr.ind.scope_key(None, ["nvda", "amd"]), "some-model")
    await rr._background_tasks[key]

    assert captured["industry"] is None
    assert captured["custom_tickers"] == ["nvda", "amd"]
    assert rr._cache_get(rr.ind.scope_key(None, ["nvda", "amd"]), "some-model") == "# custom basket report"


@pytest.mark.asyncio
async def test_report_endpoint_requires_industry_or_tickers():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await rr.industry_research_report(industry=None, tickers=None, model="some-model")
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_endpoint_idle_when_nothing_cached_or_running():
    result = await rr.industry_research_status(industry="Semiconductors", tickers=None, model="some-model")
    assert result["phase"] == "idle"


@pytest.mark.asyncio
async def test_status_endpoint_done_when_cached():
    rr._cache_put("SEMICONDUCTORS", "some-model", "# cached")
    result = await rr.industry_research_status(industry="Semiconductors", tickers=None, model="some-model")
    assert result["phase"] == "done"


# ---------------------------------------------------------------------------
# _parse_tickers
# ---------------------------------------------------------------------------

def test_parse_tickers_splits_and_strips():
    assert rr._parse_tickers("nvda, amd , intc") == ["nvda", "amd", "intc"]


def test_parse_tickers_none_and_empty():
    assert rr._parse_tickers(None) is None
    assert rr._parse_tickers("") is None
    assert rr._parse_tickers("   ") is None
