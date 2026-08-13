"""
Analyst estimate dispersion and staleness metrics, computed from earnings_estimates rows.

Background: Diether, Malloy & Scherbina (2002) and a 2024 Zhang et al. follow-up find that
wide disagreement among analysts (dispersion) predicts weaker forward returns — see
PLAN_DISPERSION.md for the full writeup. Alpha Vantage doesn't serve per-analyst price
targets, so these metrics use the EPS high/low/avg band from EARNINGS_ESTIMATES as a proxy.

Pure functions, no I/O — reused by the API layer, the monthly snapshot builder
(scripts/build_dispersion_snapshots.py), and the eventual factor test
(scripts/test_dispersion_factor.py).
"""

from __future__ import annotations

from datetime import date
from typing import Any

# Consensus EPS below this (in absolute value) makes (high - low) / eps_avg explode or flip
# sign, so eps_dispersion is left null rather than reporting a degenerate ratio.
MIN_EPS_ABS = 0.10

# Minimum analyst count required to trust a dispersion reading enough to include it in a
# percentile population. Below this, a "spread" from 2-3 analysts is mostly noise.
MIN_COVERAGE_FOR_PCTILE = 5

# Cross-sectional percentile needs a large enough population for the rank to mean anything.
MIN_POPULATION_FOR_PCTILE = 50


def _ratio(high: Any, low: Any, denom: Any, *, floor: float, floor_inclusive: bool = True) -> float | None:
    """(high - low) / denom, null if any input is missing or denom fails the floor check.

    A single lower-bound comparison against `denom` (rather than `abs(denom)`) excludes both
    near-zero AND negative denominators in one guard — a negative consensus (EPS loss, or
    revenue that should never be negative) makes the ratio flip sign or explode just as
    badly as a near-zero one does. `floor_inclusive=True` allows denom == floor through
    (used for the EPS floor, where 0.10 itself is a valid consensus); False requires denom
    strictly greater than floor (used for revenue, where 0 itself is not a valid divisor).
    """
    if high is None or low is None or denom is None:
        return None
    denom = float(denom)
    if (denom < floor) if floor_inclusive else (denom <= floor):
        return None
    return (float(high) - float(low)) / denom


def compute_metrics(row: dict) -> dict:
    """Compute dispersion/staleness metrics for one earnings_estimates row.

    `row` is expected to carry (a subset of) the earnings_estimates columns:
    eps_avg, eps_high, eps_low, eps_count, eps_avg_30d, eps_rev_up_30d, eps_rev_down_30d,
    rev_avg, rev_high, rev_low. Missing keys are treated as None. Never raises — an
    unavailable input just makes that one output metric None.
    """
    eps_avg = row.get("eps_avg")
    eps_high = row.get("eps_high")
    eps_low = row.get("eps_low")
    eps_avg_30d = row.get("eps_avg_30d")
    rev_avg = row.get("rev_avg")
    rev_high = row.get("rev_high")
    rev_low = row.get("rev_low")
    rev_up = row.get("eps_rev_up_30d")
    rev_down = row.get("eps_rev_down_30d")

    eps_dispersion = _ratio(eps_high, eps_low, eps_avg, floor=MIN_EPS_ABS, floor_inclusive=True)
    rev_dispersion = _ratio(rev_high, rev_low, rev_avg, floor=0.0, floor_inclusive=False)

    if rev_up is None and rev_down is None:
        net_revisions_30d = None
    else:
        net_revisions_30d = (rev_up or 0) - (rev_down or 0)

    if eps_avg is None or eps_avg_30d is None or float(eps_avg_30d) == 0:
        eps_drift_30d = None
    else:
        eps_drift_30d = (float(eps_avg) - float(eps_avg_30d)) / abs(float(eps_avg_30d))

    return {
        "eps_dispersion": eps_dispersion,
        "coverage": row.get("eps_count"),
        "net_revisions_30d": net_revisions_30d,
        "eps_drift_30d": eps_drift_30d,
        "rev_dispersion": rev_dispersion,
    }


def select_horizons(rows: list[dict]) -> dict:
    """Pick the FY1 and Q1 rows from a ticker's latest-snapshot estimate rows.

    FY1 = the 'fiscal year' row with the smallest fiscal_date strictly after today.
    Q1  = the 'fiscal quarter' row with the smallest fiscal_date strictly after today.
    Returns {"fy1": row | None, "q1": row | None}.
    """
    today = date.today()
    fy1 = None
    q1 = None
    for r in rows:
        fiscal_date = r.get("fiscal_date")
        if fiscal_date is None or fiscal_date <= today:
            continue
        horizon = r.get("horizon")
        if horizon == "fiscal year":
            if fy1 is None or fiscal_date < fy1["fiscal_date"]:
                fy1 = r
        elif horizon == "fiscal quarter":
            if q1 is None or fiscal_date < q1["fiscal_date"]:
                q1 = r
    return {"fy1": fy1, "q1": q1}


def percentile(value: float | None, population: list[float | None]) -> float | None:
    """Cross-sectional percentile rank of `value` within `population`, in [0, 1].

    None if `value` is None or fewer than MIN_POPULATION_FOR_PCTILE non-null values exist
    in `population` (including `value` itself, if present in the list).
    """
    if value is None:
        return None
    valid = [float(v) for v in population if v is not None]
    if len(valid) < MIN_POPULATION_FOR_PCTILE:
        return None
    value = float(value)
    n_le = sum(1 for v in valid if v <= value)
    return n_le / len(valid)
