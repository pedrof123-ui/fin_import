"""Tests for debt_maturity/summary.py (PLAN_DEBT_MATURITY.md Phase 2.3)."""

import pytest

from debt_maturity.summary import compute_summary


def _tranche(source_concept, amount, maturity_year=None, coupon_rate=None):
    return {
        "source_concept": source_concept,
        "amount": amount,
        "maturity_year": maturity_year,
        "coupon_rate": coupon_rate,
    }


def test_weighting_math_ladder_and_coupon_split():
    tranches = [
        _tranche("maturities_ladder", 100.0, 2026),
        _tranche("maturities_ladder", 300.0, 2028),
        _tranche("maturities_ladder", 600.0, None),  # Thereafter, excluded from the average
        _tranche("debt_instruments", 100.0, 2026, 0.03),  # near-term (within 5y of FY2025)
        _tranche("debt_instruments", 300.0, 2028, 0.05),  # near-term
        _tranche("debt_instruments", 600.0, 2040, 0.07),  # long-dated
    ]
    s = compute_summary(tranches, fiscal_year=2025)

    # (100*(2026-2025) + 300*(2028-2025)) / (100+300) = (100 + 900) / 400 = 2.5
    assert s["weighted_avg_years_to_maturity"] == pytest.approx(2.5)
    assert s["total_debt_covered"] == 1000.0  # ladder total, thereafter included
    assert s["pct_maturity_dated"] == pytest.approx(0.4)  # 400 of 1000 has a known year

    # near-term: (100*0.03 + 300*0.05) / 400 = 0.045
    assert s["weighted_avg_coupon_near_term"] == pytest.approx(0.045)
    # long-dated: only the 2040 tranche
    assert s["weighted_avg_coupon_long_dated"] == pytest.approx(0.07)


def test_falls_back_to_debt_instruments_when_no_ladder():
    tranches = [_tranche("debt_instruments", 100.0, 2030, 0.04)]
    s = compute_summary(tranches, fiscal_year=2025)
    assert s["weighted_avg_years_to_maturity"] == pytest.approx(5.0)
    assert s["total_debt_covered"] == 100.0


def test_ladder_only_has_no_coupon_split():
    """No debt_instruments tranches at all -- the coupon split is None, not zero or an
    error, which is the shape Phase 3 falls back on for a ticker with only the aggregate
    ladder tagged."""
    tranches = [_tranche("maturities_ladder", 500.0, 2027)]
    s = compute_summary(tranches, fiscal_year=2025)
    assert s["weighted_avg_coupon_near_term"] is None
    assert s["weighted_avg_coupon_long_dated"] is None
    assert s["weighted_avg_years_to_maturity"] == pytest.approx(2.0)


def test_no_tranches_at_all_is_fully_null():
    s = compute_summary([], fiscal_year=2025)
    assert s == {
        "fiscal_year": 2025,
        "weighted_avg_years_to_maturity": None,
        "pct_maturity_dated": None,
        "weighted_avg_coupon_near_term": None,
        "weighted_avg_coupon_long_dated": None,
        "total_debt_covered": None,
        "total_debt_reported": None,
    }


def test_large_undated_bucket_flagged_via_pct_maturity_dated():
    """A big "Thereafter" bucket is correctly excluded from the weighted-average years
    calc (no year to weight it by) but that silently understates the number unless a
    consumer can see how much of the total it rests on -- this is that visibility."""
    tranches = [
        _tranche("maturities_ladder", 100.0, 2026),
        _tranche("maturities_ladder", 900.0, None),  # Thereafter dwarfs the dated portion
    ]
    s = compute_summary(tranches, fiscal_year=2025)
    assert s["weighted_avg_years_to_maturity"] == pytest.approx(1.0)  # from the 100 alone
    assert s["pct_maturity_dated"] == pytest.approx(0.1)  # ...which is only 10% of the total
    assert s["total_debt_covered"] == 1000.0


def test_single_tranche_edge_case():
    tranches = [_tranche("debt_instruments", 250.0, 2026, 0.06)]
    s = compute_summary(tranches, fiscal_year=2024)
    assert s["weighted_avg_years_to_maturity"] == pytest.approx(2.0)
    assert s["weighted_avg_coupon_near_term"] == pytest.approx(0.06)
    assert s["weighted_avg_coupon_long_dated"] is None
    assert s["total_debt_covered"] == 250.0


def test_thereafter_tranche_with_coupon_counts_as_long_dated():
    """A debt_instruments row can carry maturity_year=None too (rare, but possible if a
    filer uses a bare "Thereafter" bucket in that table) -- it must be classified
    long-dated, never silently dropped."""
    tranches = [_tranche("debt_instruments", 400.0, None, 0.08)]
    s = compute_summary(tranches, fiscal_year=2025)
    assert s["weighted_avg_coupon_long_dated"] == pytest.approx(0.08)
    assert s["weighted_avg_coupon_near_term"] is None


def test_source_selection_prefers_larger_total_coverage():
    """A truncated ladder (Southern Co.'s real case: a 5-year-only schedule with no
    Thereafter residual) covers less debt than the per-tranche table once summed --
    the fuller source should win even though the ladder is normally preferred."""
    tranches = [
        _tranche("maturities_ladder", 200.0, 2026),  # ladder total: 200 (truncated/partial)
        _tranche("debt_instruments", 200.0, 2026, 0.03),
        _tranche("debt_instruments", 800.0, 2040, 0.05),  # instruments total: 1000 (fuller)
    ]
    s = compute_summary(tranches, fiscal_year=2025)
    assert s["total_debt_covered"] == 1000.0
    assert s["weighted_avg_coupon_long_dated"] == pytest.approx(0.05)


def test_source_selection_ties_prefer_the_ladder():
    """Equal total coverage -- the ladder wins the tie since it's normally the finer-
    grained source. Uses different maturity years for each so the winner is observable
    in weighted_avg_years_to_maturity, not just the (identical either way) total."""
    tranches = [
        _tranche("maturities_ladder", 500.0, 2026),
        _tranche("debt_instruments", 500.0, 2030, 0.04),
    ]
    s = compute_summary(tranches, fiscal_year=2025)
    assert s["weighted_avg_years_to_maturity"] == pytest.approx(1.0)  # 2026-2025, not 2030-2025


def test_total_debt_reported_passthrough_for_coverage_check():
    s = compute_summary([_tranche("maturities_ladder", 100.0, 2026)], fiscal_year=2025,
                         total_debt_reported=1000.0)
    assert s["total_debt_reported"] == 1000.0
    assert s["total_debt_covered"] == 100.0  # caller compares these for a coverage sanity check
