"""
Rolls up debt_tranches rows into the weighted-average numbers dcf/wacc.py's Phase 3
terminal-value split actually consumes (PLAN_DEBT_MATURITY.md Phase 2.2).
"""

from typing import Optional

DEFAULT_FORECAST_HORIZON = 5


def compute_summary(
    tranches: list[dict],
    fiscal_year: int,
    total_debt_reported: Optional[float] = None,
    forecast_horizon: int = DEFAULT_FORECAST_HORIZON,
) -> dict:
    """
    weighted_avg_years_to_maturity is computed from whichever of the two concepts covers
    more total dollars, as a proxy for completeness. Usually that's the maturities ladder
    -- it's an explicit schedule reconciling to a "Total" line, finer-grained than a
    per-tranche table that sometimes buckets decades of debt into one row (Apple: $86.8B
    spanning 2025-2062 in a single row, whose midpoint-year approximation would badly skew
    this metric). But the ladder isn't always the fuller picture: Southern Company's ladder
    is a 5-year-only schedule with no "Thereafter" residual, covering barely 30% of its
    real total debt once the per-tranche table's multi-subsidiary breakdown is summed --
    there, using the ladder would badly understate both total_debt_covered and years to
    maturity. The coupon split has no such choice: only the per-tranche table carries a
    rate at all.

    Returns a dict with fiscal_year always set and every other field None when the
    corresponding tranches don't exist -- the null-safe shape Phase 3/4 fall back on.
    """
    ladder = [t for t in tranches if t.get("source_concept") == "maturities_ladder"]
    instruments = [t for t in tranches if t.get("source_concept") == "debt_instruments"]

    ladder_total = sum(t["amount"] for t in ladder)
    instruments_total = sum(t["amount"] for t in instruments)
    maturity_source = ladder if (ladder and ladder_total >= instruments_total) else instruments
    dated = [t for t in maturity_source if t.get("maturity_year") is not None and t.get("amount")]
    dated_weight = sum(t["amount"] for t in dated)
    weighted_avg_years_to_maturity = (
        sum(t["amount"] * (t["maturity_year"] - fiscal_year) for t in dated) / dated_weight
        if dated_weight > 0 else None
    )
    total_debt_covered = sum(t["amount"] for t in maturity_source) if maturity_source else None
    # A "Thereafter"/undated bucket is common and often large (Apple: 54% of its ladder
    # total) -- it's correctly excluded from the weighted average above (there's no year to
    # weight it by), but that silently biases the average low unless a consumer knows how
    # much of the total it actually rests on. Surfaced explicitly rather than hidden.
    pct_maturity_dated = dated_weight / total_debt_covered if total_debt_covered else None

    threshold_year = fiscal_year + forecast_horizon
    coupon_bearing = [t for t in instruments if t.get("coupon_rate") is not None and t.get("amount")]
    near_term = [t for t in coupon_bearing
                 if t["maturity_year"] is not None and t["maturity_year"] <= threshold_year]
    long_dated = [t for t in coupon_bearing
                  if t["maturity_year"] is None or t["maturity_year"] > threshold_year]

    def _weighted_avg_coupon(rows: list[dict]) -> Optional[float]:
        weight = sum(r["amount"] for r in rows)
        return sum(r["amount"] * r["coupon_rate"] for r in rows) / weight if weight > 0 else None

    return {
        "fiscal_year": fiscal_year,
        "weighted_avg_years_to_maturity": weighted_avg_years_to_maturity,
        "pct_maturity_dated": pct_maturity_dated,
        "weighted_avg_coupon_near_term": _weighted_avg_coupon(near_term),
        "weighted_avg_coupon_long_dated": _weighted_avg_coupon(long_dated),
        "total_debt_covered": total_debt_covered,
        "total_debt_reported": total_debt_reported,
    }
