"""
AI Researcher Valuation Analyst — data-layer independence tests.

Ensures get_dcf_summary()/get_valuation_inputs() never leak the current stock price, current
multiples, model goal prices, or analyst price targets — the Valuation Analyst sub-agent must
value the business blind. See AI_RESEARCHER_IMPROVEMENT_PLAN.md Phase 1.
"""
from __future__ import annotations

import pytest

_TEST_TICKERS = ["NVDA", "UPS", "KO"]

_BANNED_TERMS = [
    "goal_low",
    "goal_high",
    "goal_2x",
    "analyst_target",
    "current price",
    "upside",
    "market cap",
]


def _combined_output(ticker: str) -> str:
    from api.valuation_data import get_dcf_summary, get_valuation_inputs
    return get_dcf_summary(ticker) + "\n" + get_valuation_inputs(ticker)


@pytest.mark.parametrize("ticker", _TEST_TICKERS)
def test_no_price_or_target_leakage(ticker):
    text = _combined_output(ticker).lower()
    hits = [term for term in _BANNED_TERMS if term in text]
    assert not hits, f"{ticker}: prohibited terms leaked into valuation context: {hits}"


@pytest.mark.parametrize("ticker", _TEST_TICKERS)
def test_dcf_summary_scenarios_ordered(ticker):
    """Bear <= base <= bull intrinsic value per share (ties allowed on degenerate data)."""
    from api.valuation_data import get_dcf_summary
    import re

    text = get_dcf_summary(ticker)
    assert not text.startswith("[ERROR]"), f"{ticker}: DCF summary failed: {text}"

    values = {}
    for label in ("BEAR", "BASE", "BULL"):
        m = re.search(rf"{label}: intrinsic value/share = \$([\d.]+)", text)
        if m:
            values[label] = float(m.group(1))

    assert "BASE" in values, f"{ticker}: base scenario missing from DCF summary"
    if "BEAR" in values and "BULL" in values:
        assert values["BEAR"] <= values["BASE"] <= values["BULL"], (
            f"{ticker}: scenario ordering violated: {values}"
        )


def test_unknown_ticker_degrades_gracefully():
    from api.valuation_data import get_dcf_summary, get_valuation_inputs

    assert get_dcf_summary("ZZZZNOTATICKER").startswith("[ERROR]")
    assert get_valuation_inputs("ZZZZNOTATICKER").startswith("[ERROR]")
