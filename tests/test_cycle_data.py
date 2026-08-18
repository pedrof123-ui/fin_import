"""Cyclicality gate tests.

The gate's load-bearing property is precision, not recall: a false positive puts a cycle
verdict on a company where the peak/trough rubric is inapplicable, which is the defect
PLAN_CYCLE_AWARENESS.md exists to fix. See scripts/cyclicality_calibration.py for the full
labelled sample and the universe confusion matrix.
"""
from __future__ import annotations

import pytest

from api.cycle_data import CYCLICAL, INSUFFICIENT_HISTORY, NON_CYCLICAL, classify_cyclicality

# Mega-cap compounders. A CYCLICAL verdict here is the failure the gate must prevent.
_COMPOUNDERS = ["AAPL", "MSFT", "KO", "PG", "COST", "WMT", "JNJ"]

# Deep cyclicals whose revenue visibly swings with their industry.
_CYCLICALS = ["MU", "CLF", "NUE", "DAL", "UAL", "OXY", "DVN", "AAL"]


@pytest.mark.parametrize("ticker", _COMPOUNDERS)
def test_compounders_are_not_cyclical(ticker):
    c = classify_cyclicality(ticker)
    assert c.verdict == NON_CYCLICAL, f"{ticker} classified {c.verdict} (amplitude {c.amplitude})"


@pytest.mark.parametrize("ticker", _CYCLICALS)
def test_known_cyclicals_are_cyclical(ticker):
    c = classify_cyclicality(ticker)
    assert c.verdict == CYCLICAL, f"{ticker} classified {c.verdict} (amplitude {c.amplitude})"


def test_unknown_ticker_degrades():
    c = classify_cyclicality("ZZZZNOTATICKER")
    assert c.verdict == INSUFFICIENT_HISTORY
    assert c.reason
    assert not c.is_cyclical


def test_verdict_carries_its_evidence():
    c = classify_cyclicality("DAL")
    assert c.is_cyclical
    assert c.amplitude == pytest.approx(abs(c.beta) * c.factor_sd, rel=1e-9)
    assert c.peer_count >= 8
    assert c.months >= 36
    assert c.peer_group


def test_split_artifact_does_not_drive_the_verdict():
    """monthly_pe.shares is transiently wrong around splits (AAPL reads 56,899M shares in
    2020-09 against a true ~17,100M), which craters ttm_eps and mimics an earnings collapse.
    The gate reads ttm_revenue, which carries no share count, so AAPL stays well clear."""
    c = classify_cyclicality("AAPL")
    assert c.verdict == NON_CYCLICAL
    assert c.amplitude < 0.08


# --- Phase 2: the cycle-position data block -------------------------------------------------

def _block(ticker: str) -> str:
    from api.research_router import get_cycle_position_data
    return get_cycle_position_data(ticker)


def test_block_reports_the_cyclicality_verdict():
    assert "Cyclicality:" in _block("MU")
    aapl = _block("AAPL")
    assert "NON_CYCLICAL" in aapl
    assert "does not apply" in aapl, "non-cyclicals must be told the rubric is inapplicable"


def test_loss_periods_are_no_longer_deleted():
    """The old query filtered ttm_eps > 0, which erased the trough entirely and biased
    mid-cycle earnings upward on exactly the deep cyclicals that matter."""
    mu = _block("MU")
    assert "trough" in mu.lower()
    assert "Months at a loss" in mu
    trough = [l for l in mu.splitlines() if "min (trough)" in l][0]
    assert "-" in trough.split("$")[1], "MU's 5yr trough EPS is negative and must show as such"


def test_midcycle_matches_the_unfiltered_average():
    """Guards the Phase 2 fix against regression: mid-cycle EPS must track the average over
    all months, not just profitable ones. Plan finding 2 measured MU at $4.74 true against
    $7.57 with the filter on; the shipped figure is restated on the current share count, so
    it is compared loosely."""
    line = [l for l in _block("MU").splitlines() if "mid-cycle avg" in l][0]
    value = float(line.split("$")[1])
    assert 4.0 < value < 5.5, f"mid-cycle EPS {value} looks filtered (unfiltered truth ~4.74)"


def test_ratio_is_suppressed_when_currently_loss_making():
    """CLF at a trough: current -$2.13 against $1.08 mid-cycle rendered as '-196%', a number
    with no interpretation."""
    clf = _block("CLF")
    for line in clf.splitlines():
        if line.startswith("Current EPS as %"):
            assert "loss-making" in line and "%" not in line.split(":")[1].replace("% of", "")


def test_ratio_is_suppressed_when_midcycle_is_negative():
    line = [l for l in _block("AAL").splitlines() if l.startswith("Current EPS as % of mid-cycle")][0]
    assert "n/a" in line and "negative" in line


def test_forward_change_does_not_invert_on_negative_eps():
    """CLF improving from -$2.13 to -$0.36 computed as -83.1%, reading as a collapse when the
    loss is narrowing — the exact signal a trough reading depends on."""
    line = [l for l in _block("CLF").splitlines() if l.startswith("Forward vs. TTM EPS")][0]
    assert "loss narrowing" in line
    assert "-83" not in line


def test_split_artifact_does_not_become_the_trough():
    """AAPL's raw 5yr MIN(ttm_eps) is $1.03 from the 2020-09 share-count defect, against a
    true ~$5.60 — an 82% phantom earnings collapse on the market's clearest non-cyclical."""
    line = [l for l in _block("AAPL").splitlines() if "min (trough)" in l][0]
    assert float(line.split("$")[1]) > 4.0


# --- Phase 3: the symmetric peak/trough rubric ----------------------------------------------

from api.cycle_data import (  # noqa: E402
    MID, NOT_CYCLICAL_POSITION, PEAK, TROUGH, evaluate_cycle_position,
)

_HEALTHY = dict(
    ttm_eps=5.0, fwd_eps=5.5, earn_growth_1yr=0.10, earn_cagr_3yr=0.09,
    operating_margin=0.20, operating_margin_median=0.20, pe=18.0, pe_median=18.0,
    rev_growth_1yr=0.08, eps_max=5.0, eps_midcycle=4.5,
)


def _score(**over):
    return evaluate_cycle_position(CYCLICAL, **{**_HEALTHY, **over})


def test_non_cyclical_never_gets_a_position():
    p = evaluate_cycle_position(NON_CYCLICAL, **_HEALTHY)
    assert p.position == NOT_CYCLICAL_POSITION
    assert not p.peak_met and not p.trough_met


def test_peak_needs_two_conditions():
    # near 5yr max alone is one condition
    assert _score(ttm_eps=5.0, eps_max=5.0).position == MID
    # add a margin at a cyclical high
    assert _score(ttm_eps=5.0, eps_max=5.0, operating_margin=0.28).position == PEAK


def test_trough_needs_three_conditions():
    depressed = dict(ttm_eps=1.0, eps_midcycle=4.5, eps_max=6.0)
    assert _score(**depressed).position == MID
    # + recovery forecast = 2, still MID
    assert _score(**depressed, fwd_eps=2.0).position == MID
    # + margin at a cyclical low = 3
    assert _score(**depressed, fwd_eps=2.0, operating_margin=0.10).position == TROUGH


def test_loss_maker_does_not_trip_two_conditions_for_free():
    """The mirrored 'P/E undefined on a loss' clause was auto-true for every loss-maker, which
    already satisfies the depressed-earnings condition — reproducing the cond1/cond4 degeneracy
    this phase repairs. Co-firing fell from 45.8% to 8.7% of cyclicals once it was removed."""
    p = _score(ttm_eps=-2.0, fwd_eps=-1.9, pe=None, operating_margin=0.20,
               earn_growth_1yr=-0.10, rev_growth_1yr=-0.09)
    assert len(p.trough_met) == 1, f"loss alone met {len(p.trough_met)}: {p.trough_met}"
    assert p.position == MID


def test_narrowing_loss_is_not_counted_as_a_recovery():
    """A loss-maker must be forecast to return to profit. Analysts forecast some improvement for
    ~74% of cyclicals, so 'any improvement' is a degenerate condition."""
    assert len(_score(ttm_eps=-2.0, fwd_eps=-0.3).trough_met) == 1   # still loss-making
    assert len(_score(ttm_eps=-2.0, fwd_eps=0.4).trough_met) == 2    # returns to profit


def test_repaired_peak_multiple_condition_uses_the_rolling_median():
    """The original compared current P/E to normalized_pe_5y, which is mechanically below
    current P/E whenever EPS is rising, so it co-fired with condition 1 on 99.7% of cases."""
    cheap = _score(pe=10.0, pe_median=20.0)
    assert any("below its own 5yr median" in c for c in cheap.peak_met)
    assert not any("below its own 5yr median" in c for c in _score(pe=19.0, pe_median=20.0).peak_met)


def test_negative_midcycle_is_flagged_and_does_not_crash():
    p = _score(ttm_eps=0.30, eps_midcycle=-0.56, eps_max=3.98)
    assert any("Mid-cycle earnings are negative" in n for n in p.notes)


def test_both_sides_firing_resolves_to_mid_with_a_note():
    p = evaluate_cycle_position(
        CYCLICAL, ttm_eps=1.0, fwd_eps=2.0, earn_growth_1yr=0.90, earn_cagr_3yr=0.10,
        operating_margin=0.10, operating_margin_median=0.20, pe=30.0, pe_median=18.0,
        rev_growth_1yr=0.10, eps_max=1.0, eps_midcycle=4.5,
    )
    if len(p.peak_met) >= 2 and len(p.trough_met) >= 3:
        assert p.position == MID
        assert any("contradictory" in n for n in p.notes)


def test_block_renders_the_position_and_its_evidence():
    clf = _block("CLF")
    assert "CYCLE POSITION: TROUGH" in clf
    assert "MET  -" in clf
    assert "required for TROUGH" in clf
    aapl = _block("AAPL")
    assert "CYCLE POSITION: NOT_CYCLICAL" in aapl
    assert "MET  -" not in aapl, "no conditions should be scored for a non-cyclical"
