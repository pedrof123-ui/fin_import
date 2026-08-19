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

from api.research_router import (  # noqa: E402
    _DEFAULT_MODEL, _run_research_agent, compute_cycle_position, render_to_markdown,
)
from api.cycle_data import TROUGH, assess_trough_quality  # noqa: E402

_TEST_TICKERS = ["NVDA", "UPS", "KO", "MU", "FANG"]

# Cycle-position coverage (PLAN_CYCLE_AWARENESS.md Phase 8). NVDA/UPS/KO are all NON_CYCLICAL, so
# before these two were added no run had ever exercised a rendered cycle callout. MU is a PEAK and
# FANG a TROUGH that clears the trough-quality tests, which is also the longest output case in the
# feature and therefore the one to watch for Chief JSON truncation.
_EXPECTED_CYCLE = {"NVDA": "NOT_CYCLICAL", "UPS": "NOT_CYCLICAL", "KO": "NOT_CYCLICAL",
                   "MU": "PEAK", "FANG": "TROUGH"}
_EXPECTED_CALLOUT = {"MU": "Peak-Earnings Trap Alert", "FANG": "Trough-Earnings Opportunity"}
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
        # Star-unpack the tail: _run_research_agent has grown its return tuple twice
        # (dcf_reconciliation, usage_tracker) and a fixed-width unpack here broke silently
        # each time. Only the leading five are asserted on.
        report, findings, valuation_tables_md, direct_competitors_md, market_share_md, *_ = \
            await _run_research_agent(ticker, _DEFAULT_MODEL)
    except Exception as e:
        checks.append(_check("report generated", False, str(e)))
        return checks, info

    elapsed = time.time() - t0
    h, v = report.header, report.valuation

    checks.append(_check("report generated", True))
    # Budget covers the whole pipeline: the four sub-agents, the inline Agentic AI DCF, and both
    # Chief calls (Core + Narrative). The old 180s ceiling was set 2026-07-20, before the AI DCF
    # landed; that alone carries a 600s outer timeout because its per-agent budgets legitimately
    # reach ~800s, so a report can exceed 180s without anything being wrong. Measured 2026-08-17:
    # NVDA 401.5s, UPS 438.6s, KO 394.3s. 900s sits above the legitimate worst case while still
    # catching a genuine hang.
    checks.append(_check("generation time < 900s", elapsed < 900, f"{elapsed:.1f}s"))
    checks.append(_check("target_low <= target_high", h.target_low <= h.target_high))
    checks.append(_check("has intrinsic_valuation section", bool(report.intrinsic_valuation)))
    checks.append(_check("has balance_sheet_analysis section", bool(report.balance_sheet_analysis)))
    checks.append(_check("has valuation model tables", bool(valuation_tables_md)))
    if valuation_tables_md:
        for label in ("DCF Scenario Assumptions", "Key Fundamentals", "Comparable Companies", "Model Summary"):
            checks.append(_check(f"tables include '{label}'", label in valuation_tables_md))
        # P/S and P/FCF cross-check rows are data-dependent (need forward revenue consensus /
        # FCF margin), so informational rather than a hard gate.
        for label in ("Multiples (P/S", "Multiples (P/E", "Multiples (P/FCF"):
            info.append(_check(f"model summary includes '{label}...)'", label in valuation_tables_md))

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

    # Plausibility, not just ordering. The suite once passed a base fair value of $23.58 against
    # MU's $823 price because it only ever asserted low <= base <= high.
    #
    # Two bands, because one threshold cannot serve both purposes. This pipeline runs
    # structurally conservative — NVDA and KO sit at 0.43x and 0.53x of market with nothing
    # wrong — so a band tight enough to flag those would fire constantly. But 0.09x is not a
    # contrarian call, it is an arithmetic error, and the first version of this check was
    # informational-only and duly reported ALL CHECKS PASSED with MU at 0.09x.
    #
    #   absurd  (gating)        — outside 0.15x-5.0x: no defensible valuation lands here
    #   stretched (informational) — outside 0.30x-3.0x: worth a look, not worth failing on
    price = getattr(v, "current_price", None)
    if price and v.fair_value_base:
        ratio = float(v.fair_value_base) / float(price)
        detail = f"base ${v.fair_value_base:.2f} vs price ${price:.2f} = {ratio:.2f}x"
        checks.append(_check("fair_value_base not absurd vs price (0.15x-5.0x)",
                             0.15 <= ratio <= 5.0, detail))
        info.append(_check("fair_value_base within a comfortable band (0.30x-3.0x)",
                           0.30 <= ratio <= 3.0, detail))

    # --- cycle position (PLAN_CYCLE_AWARENESS.md Phase 8) --------------------------------------
    expected = _EXPECTED_CYCLE.get(ticker)
    if expected:
        # The gate is deterministic, so a changed expectation means the data moved under us, not
        # that the model erred — report it as informational rather than failing the suite.
        computed = compute_cycle_position(ticker)
        if computed != expected:
            info.append(_check(
                "cycle expectation still current", False,
                f"expected {expected}, gate now computes {computed} — update _EXPECTED_CYCLE"))
        else:
            checks.append(_check(
                f"cycle_position == {expected}", report.cycle_position == expected,
                f"report says {report.cycle_position}"))

    callout = _EXPECTED_CALLOUT.get(ticker)
    if callout and report.cycle_position in ("PEAK", "TROUGH"):
        quality = (assess_trough_quality(ticker).quality
                   if report.cycle_position == TROUGH else None)
        md = render_to_markdown(report, trough_quality=quality)
        checks.append(_check(f"renders '{callout}'", callout in md))
        checks.append(_check(
            "cycle_position_analysis populated",
            bool((report.cycle_position_analysis or "").strip()),
            f"{len(report.cycle_position_analysis or '')} chars"))

        # Truncation guard. max_tokens=32000 silently truncated the Chief's JSON once before, on
        # a long peak_earnings_analysis (COHR). This feature made the Core call's input and
        # output longer again, so check the cycle narrative has not crowded out the fields that
        # follow it in the same Core response.
        checks.append(_check(
            "Core output not truncated by the cycle section",
            bool(report.key_highlights) and bool(report.financial_performance)
            and bool(report.valuation.fair_value_base is not None),
            f"highlights={len(report.key_highlights)} rows={len(report.financial_performance)}"))

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
