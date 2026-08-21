"""
Point-in-time correctness for the DCF as-of reconstruction.

The whole risk of the backward reconstruction (features/dcf/PLAN_DCF_ACCURACY.md Phase 2) is
look-ahead: a DCF that sees data published after its as-of date produces a result that looks
excellent and means nothing. The plan is explicit that this must be validated by asserting no
input carries a publication date after the as-of date, not by eyeballing whether the numbers
look sensible — so these tests assert on the inputs, not on the intrinsic value.
"""
from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from dcf.av_data import AV_DB, load_av_annual_financials, load_av_quarterly_financials
from dcf.data import PRICES_DB, load_current_price
from dcf.model import run_dcf_av
from dcf.wacc import get_betas
from historic_fundamentals.pe import LAG_ANNUAL, LAG_QUARTERLY

_AS_OF_DATES = [date(2012, 6, 30), date(2015, 6, 30), date(2019, 6, 30), date(2023, 6, 30)]
_TICKERS = ["AAPL", "MSFT", "JPM", "WMT", "XOM"]
# Wider list for the tests that need *some* ticker to clear the plausibility bound on a given
# date. Five large caps were not enough: none of them produced a DCF on 2012-06-30, which
# silently skipped that date rather than testing it.
_VALUABLE_CANDIDATES = _TICKERS + [
    "JNJ", "PG", "KO", "PEP", "MRK", "PFE", "CVX", "T", "VZ", "IBM",
    "MCD", "HD", "CAT", "MMM", "UNH", "ORCL", "CSCO", "INTC", "TXN", "ADP",
]


@pytest.fixture(scope="module", autouse=True)
def _require_dbs():
    if not AV_DB.exists() or not PRICES_DB.exists():
        pytest.skip("AV or prices database not present")


@pytest.mark.parametrize("as_of", _AS_OF_DATES)
@pytest.mark.parametrize("ticker", _TICKERS)
def test_no_statement_published_after_as_of(ticker: str, as_of: date):
    """Every fiscal period fed to the model must have been public on as_of."""
    annual = load_av_annual_financials(ticker, as_of=as_of)
    quarterly = load_av_quarterly_financials(ticker, as_of=as_of)

    for name, frames, lag in (
        ("annual", annual, LAG_ANNUAL),
        ("quarterly", quarterly, LAG_QUARTERLY),
    ):
        for stmt, df in frames.items():
            if df.empty or "period_end_date" not in df.columns:
                continue
            latest = pd.to_datetime(df["period_end_date"]).max().date()
            available = latest + lag
            assert available <= as_of, (
                f"{ticker} {name}/{stmt}: period ending {latest} would not be public until "
                f"{available}, after as_of {as_of} — look-ahead"
            )


@pytest.mark.parametrize("as_of", _AS_OF_DATES)
@pytest.mark.parametrize("ticker", _TICKERS)
def test_price_and_beta_not_from_the_future(ticker: str, as_of: date):
    price = load_current_price(ticker, as_of=as_of)
    assert price is not None and price > 0, f"{ticker}: no price on/before {as_of}"

    conn = duckdb.connect(str(PRICES_DB), read_only=True)
    try:
        price_date = conn.execute(
            "SELECT max(date) FROM stock_prices WHERE ticker = ? AND date <= ?",
            [ticker, as_of],
        ).fetchone()[0]
        beta_date = conn.execute(
            "SELECT max(computed_date) FROM ticker_betas WHERE ticker = ? AND computed_date <= ?",
            [ticker, as_of],
        ).fetchone()[0]
    finally:
        conn.close()

    assert price_date is not None and price_date <= as_of
    assert beta_date is not None and beta_date <= as_of

    beta_5yr, _ = get_betas(ticker, as_of=as_of)
    assert beta_5yr is not None, f"{ticker}: no beta on/before {as_of}"


def _first_valuable(as_of: date):
    """First ticker that produces a DCF on `as_of`.

    Not pinned to one name on purpose: the plausibility bound legitimately rejects individual
    ticker-dates (AAPL reconstructs to 3.2x price in 2015), and a test of the as-of plumbing
    should not fail because one company tripped an unrelated guard.
    """
    for ticker in _VALUABLE_CANDIDATES:
        try:
            return run_dcf_av(ticker, as_of=as_of)
        except ValueError:
            continue
    pytest.skip(f"no ticker in {_VALUABLE_CANDIDATES} produced a DCF on {as_of}")


@pytest.mark.parametrize("as_of", _AS_OF_DATES)
def test_as_of_run_uses_no_analyst_estimates(as_of: date):
    """earnings_estimates only begins 2026-05-10, so any analyst input in a historical run is
    by definition from the future. run_dcf_av must drop it rather than leave it to the caller."""
    result = _first_valuable(as_of)
    assert result.analyst_years_applied == 0
    assert result.analyst_estimates == []


def test_as_of_moves_every_dated_input():
    """A guard against as_of being silently ignored — the failure mode that produces a
    look-ahead-clean-looking result. Each input must differ between two distant dates.

    Asserted on the loaders rather than on run_dcf_av, so that a ticker tripping the
    plausibility bound on one of the two dates cannot mask a genuine as_of regression.
    """
    old_d, new_d = date(2015, 6, 30), date(2023, 6, 30)

    assert load_current_price("AAPL", as_of=old_d) != load_current_price("AAPL", as_of=new_d)
    assert get_betas("AAPL", as_of=old_d)[0] != get_betas("AAPL", as_of=new_d)[0]

    old_stmt = load_av_annual_financials("AAPL", as_of=old_d)["income"]
    new_stmt = load_av_annual_financials("AAPL", as_of=new_d)["income"]
    assert pd.to_datetime(old_stmt["period_end_date"]).max() < pd.to_datetime(new_stmt["period_end_date"]).max()

    from dcf.data import load_risk_free_rate_30y
    assert load_risk_free_rate_30y(as_of=old_d) != load_risk_free_rate_30y(as_of=new_d)


def test_live_path_unchanged_by_as_of_plumbing():
    """as_of=None must behave exactly as before: live quote, latest statements, estimates honoured."""
    live = run_dcf_av("AAPL")
    latest_annual = load_av_annual_financials("AAPL")
    assert live.current_price is not None and live.current_price > 0
    assert not latest_annual["income"].empty


# ── Plausibility bound: two thresholds, two questions ────────────────────────

def test_plausibility_bound_splits_by_who_drove_the_forecast():
    """The 2.5x bound is a signal-quality threshold fitted against runaway extrapolation BY THE
    MODEL. A caller who supplies per-year forecasts owns the output, so those runs get the looser
    10x sanity backstop instead.

    Without this split, tightening the mechanical bound tripled AI-DCF bull-scenario loss
    (2/25 -> 7/25), truncating the bear/base/bull range asymmetrically and biasing the presented
    valuation downward.
    """
    from dcf.assumptions import UserOverrides, YearOverride
    from dcf.model import MAX_INTRINSIC_TO_PRICE, MAX_INTRINSIC_TO_PRICE_OVERRIDE

    assert MAX_INTRINSIC_TO_PRICE < MAX_INTRINSIC_TO_PRICE_OVERRIDE

    as_of = date(2015, 6, 30)

    # AAPL reconstructs to ~3.2x price here: over the default bound, under the override one.
    with pytest.raises(ValueError, match=r"plausibility bound"):
        run_dcf_av("AAPL", as_of=as_of)

    overrides = UserOverrides(years={i: YearOverride(revenue_growth=0.10) for i in range(1, 6)})
    result = run_dcf_av("AAPL", overrides=overrides, as_of=as_of)
    assert result.intrinsic_value_per_share > 0


def test_non_forecast_overrides_still_get_the_default_bound():
    """Only `years` counts. Overriding beta or terminal growth alone leaves the revenue and
    margin path forecaster-driven, which is exactly what the 2.5x bound was fitted against —
    so it must NOT buy the looser threshold."""
    from dcf.assumptions import UserOverrides

    with pytest.raises(ValueError, match=r"2\.5x plausibility bound"):
        run_dcf_av("AAPL", overrides=UserOverrides(beta=1.1), as_of=date(2015, 6, 30))
