"""
AI Researcher regression harness.

Generates a full equity research report for each test ticker (bypassing the 24h cache) and
asserts the structural criteria from AI_RESEARCHER_IMPROVEMENT_PLAN.md Phases 2-4. Prints a
pass/fail table. Does not call the DCF/valuation data functions directly (those are covered by
tests/test_valuation_data.py) — this exercises the full LLM pipeline end to end.

Usage: uv run python scripts/research_regression.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from api.research_router import _run_research_agent, _DEFAULT_MODEL  # noqa: E402

_TEST_TICKERS = ["NVDA", "UPS", "KO"]
_DEGRADED_TICKER = "ZZZZNOTATICKER"  # absent from pe_stats/av_financials — verifies graceful degradation


def _check(label: str, condition: bool, detail: str = "") -> tuple[str, bool, str]:
    return (label, condition, detail)


async def _run_one(ticker: str) -> tuple[list[tuple[str, bool, str]], list[tuple[str, bool, str]]]:
    """Returns (gating_checks, informational_checks). Informational checks are printed but
    never fail the run — TAM/direct-competitor identification is inherently data-dependent
    (web search may not surface credible figures for every ticker)."""
    checks: list[tuple[str, bool, str]] = []
    info: list[tuple[str, bool, str]] = []
    t0 = time.time()
    try:
        report, findings, valuation_tables_md, direct_competitors_md, market_share_md = \
            await _run_research_agent(ticker, _DEFAULT_MODEL)
    except Exception as e:
        checks.append(_check("report generated", False, str(e)))
        return checks, info

    elapsed = time.time() - t0
    h, v = report.header, report.valuation

    checks.append(_check("report generated", True))
    checks.append(_check("generation time < 180s", elapsed < 180, f"{elapsed:.1f}s"))
    checks.append(_check("target_low <= target_high", h.target_low <= h.target_high))
    checks.append(_check("has intrinsic_valuation section", bool(report.intrinsic_valuation)))
    checks.append(_check("has balance_sheet_analysis section", bool(report.balance_sheet_analysis)))
    checks.append(_check("has valuation model tables", bool(valuation_tables_md)))
    if valuation_tables_md:
        for label in ("DCF Scenario Assumptions", "Key Fundamentals", "Comparable Companies", "Model Summary"):
            checks.append(_check(f"tables include '{label}'", label in valuation_tables_md))

    info.append(_check(
        "direct competitors table", bool(direct_competitors_md),
        "populated" if direct_competitors_md else "none identified this run",
    ))
    info.append(_check(
        "market share table", bool(market_share_md),
        "populated" if market_share_md else "no TAM found this run",
    ))

    fv_populated = v.fair_value_low is not None and v.fair_value_base is not None and v.fair_value_high is not None
    checks.append(_check("fair_value_low/base/high populated", fv_populated))
    if fv_populated:
        checks.append(_check(
            "fair_value_low <= base <= high",
            v.fair_value_low <= v.fair_value_base <= v.fair_value_high,
            f"{v.fair_value_low} / {v.fair_value_base} / {v.fair_value_high}",
        ))

    checks.append(_check("qc_findings == []", findings == [], str(findings)))

    return checks, info


async def main() -> int:
    all_ok = True
    for ticker in _TEST_TICKERS:
        print(f"\n=== {ticker} ===")
        checks, info = await _run_one(ticker)
        for label, ok, detail in checks:
            status = "PASS" if ok else "FAIL"
            suffix = f" ({detail})" if detail else ""
            print(f"  [{status}] {label}{suffix}")
            if not ok:
                all_ok = False
        for label, ok, detail in info:
            suffix = f" ({detail})" if detail else ""
            print(f"  [INFO] {label}{suffix}")

    print(f"\n=== {_DEGRADED_TICKER} (degradation check) ===")
    try:
        report, *_ = await _run_research_agent(_DEGRADED_TICKER, _DEFAULT_MODEL)
        print(f"  [PASS] degraded gracefully, no crash (rating={report.header.rating})")
    except Exception as e:
        print(f"  [FAIL] raised unexpectedly: {e}")
        all_ok = False

    print("\n" + ("ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
