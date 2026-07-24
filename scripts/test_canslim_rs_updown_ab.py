#!/usr/bin/env python3
"""
Follow-up to docs/canslim_factors_test.md: the full 7-factor CANSLIM bundle
lost to the live composite on every metric (test_canslim_augmented_ab.py),
but two of the seven sub-factors -- rs_rating (L) and up_down_vol_ratio (S)
-- showed genuine standalone IC in the Phase 6 test while q_earn_accel (C)
and vol_surge_ratio (S) showed none. This isolates just the two "good"
factors to check whether they were actually helping and got outweighed by
the two noise factors, or whether they don't help either once isolated.

rs_rating correlates ~0.72 (mean within-month Spearman) with the composite's
existing momentum_12_1 -- moderate overlap, not a near-duplicate, so still
worth testing empirically rather than assuming redundancy.

Otherwise identical to scripts/test_canslim_augmented_ab.py: live
sector-neutral guardrailed composite WITH vs WITHOUT the 2 factors added,
identical universe/dates, single full-period run.

Usage:
    uv run scripts/test_canslim_rs_updown_ab.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe  # noqa: E402
from historic_fundamentals.baselines import (  # noqa: E402
    composite_score,
    _VALUE_COLS,
    _VALUE_SIGN,
    _QUALITY_COLS,
    _QUALITY_SIGN,
    _MOMENTUM_COL,
)
from historic_fundamentals.backtest import (  # noqa: E402
    run_monthly_backtest,
    portfolio_metrics,
    load_spy_returns,
)
from scripts.run_backtest import _load_monthly_pe, _join_sector, _apply_guardrails  # noqa: E402

log = logging.getLogger(__name__)

EXTRA_COLS = ["rs_rating", "up_down_vol_ratio"]


def _print_metrics(label: str, m: dict) -> None:
    if not m or not m.get("n_months"):
        print(f"  {label}: no data")
        return
    print(
        f"  {label:<45} CAGR {m.get('cagr', float('nan')):+7.2%}  "
        f"Sharpe {m.get('sharpe', float('nan')):6.3f}  "
        f"MaxDD {m.get('max_drawdown', float('nan')):+7.2%}  "
        f"WinRate {m.get('monthly_win_rate', float('nan')):6.1%}  "
        f"Months {m.get('n_months', 0)}"
    )


def _composite(df, extra_cols=None):
    value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
    value_sign = {c: _VALUE_SIGN[c] for c in value_cols}
    quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
    quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}
    if extra_cols:
        for c in extra_cols:
            if c in df.columns and df[c].notna().any() and c not in quality_cols:
                quality_cols.append(c)
                quality_sign[c] = False
    has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()
    cols = value_cols + quality_cols + ([_MOMENTUM_COL] if has_momentum else [])
    sign_map = {**value_sign, **quality_sign, **({_MOMENTUM_COL: False} if has_momentum else {})}
    log.info("Composite factors (%d): %s", len(cols), cols)
    return composite_score(df, cols, sign_map, sector_neutral=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    log.info("Loading monthly_pe ...")
    raw = _load_monthly_pe(hf_db)
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]
    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    log.info("Universe: %d rows, %d tickers", len(universe), universe["ticker"].nunique())

    spy_returns = None
    if Path(prices_db).exists():
        try:
            spy_returns = load_spy_returns(prices_db_path=prices_db)
        except Exception as exc:
            log.warning("Could not load SPY returns: %s", exc)

    print("\n" + "=" * 78)
    print("AUGMENTED COMPOSITE A/B — live composite WITH vs WITHOUT rs_rating + up_down_vol_ratio")
    print("=" * 78)

    universe["composite_baseline"] = _composite(universe)
    universe["composite_augmented"] = _composite(universe, extra_cols=EXTRA_COLS)

    for score_col, label in [
        ("composite_baseline", "baseline (current live factors)"),
        ("composite_augmented", "augmented (+rs_rating +up_down_vol_ratio)"),
    ]:
        gr = _apply_guardrails(universe, score_col)
        results = run_monthly_backtest(
            gr, score_col=score_col, tc_bps=10.0,
            portfolios={"top_n_25": 25},
            sector_col="sector" if "sector" in gr.columns else None,
            max_sector_pct=0.25,
        )
        print()
        for port_name, bt_df in results.items():
            m = portfolio_metrics(bt_df["net_return"], spy_returns) if not bt_df.empty else {}
            _print_metrics(f"{label} / {port_name}", m)

    print("\nDone.")


if __name__ == "__main__":
    main()
