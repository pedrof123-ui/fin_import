"""
Phase 3 smoke test: proves walk_forward_validate_quantile itself works
correctly on a small synthetic panel where the target multiple is deliberately
correlated with a feature (so the model should reliably beat a naive
sector-median baseline). Not a substitute for the real gate run on production
data (scripts/validate_ml_comps_valuation.py) — see
features/historic_fundamentals/ml_comps_valuation_plan.md Phase 3.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from historic_fundamentals.ml_comps_model import walk_forward_validate_quantile

_SECTORS = ["TECH", "INDUSTRIALS", "HEALTHCARE", "FINANCIALS"]
_N_TICKERS_PER_SECTOR = 20
_N_MONTHS = 84  # 7 years: 5y train + 2y test -> 1 fold


def _make_synthetic_panel(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    months = pd.date_range("2018-01-31", periods=_N_MONTHS, freq="ME")

    rows = []
    for sector in _SECTORS:
        sector_level = rng.normal(loc=3.0, scale=0.2)  # sector's baseline log-PE
        for i in range(_N_TICKERS_PER_SECTOR):
            ticker = f"{sector[:3]}{i:02d}"
            growth = rng.normal(loc=0.10, scale=0.05)
            quality = rng.normal(loc=0.0, scale=1.0)
            for m in months:
                noise = rng.normal(scale=0.15)
                # Target genuinely depends on growth/quality -> model should beat
                # a naive sector-median baseline that ignores company-specific info.
                log_pe = sector_level + 3.0 * growth + 0.3 * quality + noise
                rows.append({
                    "ticker": ticker,
                    "month_end_date": m,
                    "sector": sector,
                    "rev_growth_1yr": growth + rng.normal(scale=0.01),
                    "roic": quality + rng.normal(scale=0.05),
                    "target_log_pe": log_pe,
                    "pe_median": np.exp(sector_level),  # naive baseline: sector median only
                })
    return pd.DataFrame(rows)


def test_model_beats_naive_baseline_on_synthetic_data():
    df = _make_synthetic_panel()
    result = walk_forward_validate_quantile(
        df,
        feature_cols=["rev_growth_1yr", "roic"],
        target_col="target_log_pe",
        peer_col="pe_median",
        train_years=5,
        test_years=1,
        min_train_months=36,
    )
    agg = result["aggregate"]
    assert agg["n_folds"] >= 1
    assert agg["mean_rmse_log"] < agg["mean_baseline_rmse_log"]
    assert agg["fold_win_rate"] >= 0.5
