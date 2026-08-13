#!/usr/bin/env python3
"""
Dormant factor test for analyst EPS-estimate dispersion (PLAN_DISPERSION.md Phase 6).

Background: Diether, Malloy & Scherbina (2002) and a 2024 Zhang et al. follow-up find that
wide analyst disagreement (dispersion) predicts weaker forward returns, via Miller (1977) —
short-sale constraints let optimists set the price. The Barron's article that prompted this
plan reports this for price-target dispersion; Alpha Vantage serves no per-analyst price
targets or historical estimate snapshots, so `eps_dispersion` (EPS high/low band from
EARNINGS_ESTIMATES, computed in historic_fundamentals/dispersion.py) is used as a proxy.

This script REFUSES TO RUN until estimates_dispersion (built by
scripts/build_dispersion_snapshots.py) has at least MIN_MONTHS_REQUIRED months of history.
As of 2026-08 there are ~3 months — this script is written now, while the reasoning is
fresh, to run untouched once ~3 years of weekly-refreshed snapshots have accumulated
(around 2029, given monthly granularity). Do not lower the threshold to make it run sooner;
see PLAN_DISPERSION.md for why a short archive cannot support a walk-forward test.

Mirrors the methodology used for every prior factor test in this repo (Greenblatt, CANSLIM,
Fibonacci — see scripts/test_greenblatt_factors.py): IC test first, then a quintile-spread
backtest, before touching the live composite.

Three controls are included from day one, because the article's own reported numbers do not
survive without them (see PLAN_DISPERSION.md's assessment of the source):
  - Coverage control: orthogonalize eps_dispersion against log(analyst count) before
    computing IC. (High-Low)/Avg is a range statistic whose expectation grows with analyst
    count even at constant true disagreement — if the raw IC survives but the
    coverage-residual IC doesn't, the signal is coverage, not disagreement.
  - Size/idio-vol control: orthogonalize against log(market cap) and trailing realized
    vol. The literature's effect concentrates in small, high-vol, hard-to-borrow names.
  - Long-only subsample: report the best-dispersion quintile alone, not just the
    long-short spread — most of the literature's alpha sits in the short leg, which is the
    leg borrow costs eat, and this platform's composite is long-only.

Nothing here writes to historic_fundamentals/baselines.py or scripts/score_live.py — those
stay untouched until a decision is made to promote the factor.

Usage:
    uv run scripts/test_dispersion_factor.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from historic_fundamentals.universe import UNIVERSE_DEFAULTS, filter_universe  # noqa: E402
from historic_fundamentals.baselines import (  # noqa: E402
    compute_forward_returns,
    compute_factor_ic,
    ic_summary,
    quintile_returns,
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
from historic_fundamentals.dispersion import compute_metrics  # noqa: E402
from scripts.run_backtest import _load_monthly_pe, _join_sector, _apply_guardrails  # noqa: E402

log = logging.getLogger(__name__)

MIN_MONTHS_REQUIRED = 36
TC_BPS = 10.0
PORTFOLIOS = {"top_n_25": 25}


def _profit_factor_and_expectancy(returns: pd.Series) -> tuple[float, float]:
    """Per the standing metrics rule (feedback_strategy_metrics): always report these
    alongside Sharpe/MaxDD/turnover, not Sharpe alone."""
    r = returns.dropna()
    wins = r[r > 0]
    losses = r[r <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else np.nan
    win_rate = len(wins) / len(r) if len(r) > 0 else np.nan
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.0
    r_exp = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if not np.isnan(win_rate) else np.nan
    return pf, r_exp


def _check_history(conn: duckdb.DuckDBPyConnection) -> tuple[int, object]:
    row = conn.execute("""
        SELECT COUNT(DISTINCT month_end_date), MIN(month_end_date)
        FROM estimates_dispersion WHERE horizon_slot = 'FY1'
    """).fetchone()
    return row[0] or 0, row[1]


def _orthogonalize(df: pd.DataFrame, factor_col: str, control_cols: list[str],
                    group_col: str = "month_end_date") -> pd.Series:
    """Per-month OLS residual of factor_col against control_cols (plus intercept).

    Isolates the part of factor_col not explained by the controls, so its IC can be
    re-tested on the residual alone.
    """
    out = pd.Series(index=df.index, dtype=float)
    for _, idx in df.groupby(group_col).groups.items():
        sub = df.loc[idx, [factor_col, *control_cols]].dropna()
        if len(sub) < 20:
            continue
        X = np.column_stack([np.ones(len(sub)), sub[control_cols].values])
        y = sub[factor_col].values
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        out.loc[sub.index] = y - X @ beta
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    conn = duckdb.connect(hf_db, read_only=True)
    n_months, earliest = _check_history(conn)

    if n_months < MIN_MONTHS_REQUIRED:
        remaining = MIN_MONTHS_REQUIRED - n_months
        log.info("estimates_dispersion has %d month(s) of FY1 history (earliest: %s).", n_months, earliest)
        log.info("Need at least %d months for a walk-forward test — %d more to go (~%.1f more years "
                  "at 1 month/run).", MIN_MONTHS_REQUIRED, remaining, remaining / 12)
        log.info("Refusing to run — see PLAN_DISPERSION.md Phase 6. Exiting cleanly.")
        conn.close()
        return

    log.info("Loading estimates_dispersion (%d months, from %s)...", n_months, earliest)
    disp = conn.execute("""
        SELECT ticker, month_end_date, eps_avg, eps_high, eps_low, eps_count
        FROM estimates_dispersion WHERE horizon_slot = 'FY1'
    """).df()
    conn.close()

    disp["month_end_date"] = pd.to_datetime(disp["month_end_date"])
    metrics = disp.apply(lambda r: compute_metrics(r.to_dict()), axis=1, result_type="expand")
    disp = pd.concat([disp, metrics[["eps_dispersion", "coverage"]]], axis=1)

    log.info("Loading monthly_pe universe...")
    raw = _load_monthly_pe(hf_db)
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]
    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)

    # Trailing realized-vol proxy (12m std of monthly returns) — a plain, self-contained
    # idio-vol control that doesn't depend on any pre-existing "vol" column in monthly_pe.
    universe = universe.sort_values(["ticker", "month_end_date"])
    universe["_ret_1m"] = universe.groupby("ticker")["price"].pct_change()
    universe["trailing_vol_12m"] = universe.groupby("ticker")["_ret_1m"].transform(
        lambda s: s.rolling(12, min_periods=6).std()
    )

    universe = compute_forward_returns(universe, {"ret_6m": 6, "ret_12m": 12})

    merged = universe.merge(
        disp[["ticker", "month_end_date", "eps_dispersion", "coverage"]],
        on=["ticker", "month_end_date"], how="inner",
    )
    log.info("Merged universe: %d ticker-months with a dispersion reading", len(merged))
    if merged.empty:
        log.warning("No overlap between estimates_dispersion and the monthly_pe universe — nothing to test.")
        return

    # ── 1. IC test — eps_dispersion vs incumbent value/quality factors ───────────
    print("\n" + "=" * 78)
    print("IC TEST — eps_dispersion vs incumbent factors")
    print("=" * 78)
    reference = {
        **{c: (c, _VALUE_SIGN[c]) for c in _VALUE_COLS},
        **{c: (c, _QUALITY_SIGN[c]) for c in _QUALITY_COLS},
    }
    for horizon_col in ("ret_6m", "ret_12m"):
        print(f"\n-- {horizon_col} --")
        # lower_is_better=True: high dispersion predicts LOW returns (the short leg in
        # the literature), matching this framework's existing sign convention for
        # "lower is better" factors (see _VALUE_SIGN/_QUALITY_SIGN above).
        summ = ic_summary(compute_factor_ic(merged, "eps_dispersion", horizon_col, lower_is_better=True))
        print(f"  eps_dispersion            mean_ic={summ['mean_ic']:+.4f}  icir_nw={summ['icir_nw']:6.3f}  "
              f"hit_rate={summ['hit_rate']:.1%}  n_months={summ['n_months']}")
        for name, (col, lower_is_better) in reference.items():
            if col not in merged.columns:
                continue
            summ_r = ic_summary(compute_factor_ic(merged, col, horizon_col, lower_is_better=lower_is_better))
            print(f"  {name:<25} mean_ic={summ_r['mean_ic']:+.4f}  icir_nw={summ_r['icir_nw']:6.3f}  (reference)")

    # ── 2. Quintile spread + long-only subsample ──────────────────────────────────
    print("\n" + "=" * 78)
    print("QUINTILE SPREAD — eps_dispersion, ret_12m (Q1 = lowest dispersion)")
    print("=" * 78)
    q = quintile_returns(merged, "eps_dispersion", "ret_12m", lower_is_better=True)
    print(q.to_string())
    if not q.empty and "mean_return" in q.columns:
        best, worst = q.iloc[0]["mean_return"], q.iloc[-1]["mean_return"]
        print(f"\n  Long-only (best/lowest-dispersion quintile) mean 12m return: {best:+.2%}")
        print(f"  Long-short spread (best - worst quintile):    {best - worst:+.2%}")

    # ── 3. Controls — does the IC survive coverage / size / idio-vol? ────────────
    print("\n" + "=" * 78)
    print("CONTROLS — orthogonalized IC (ret_12m)")
    print("=" * 78)
    merged["log_coverage"] = np.log(merged["coverage"].clip(lower=1))
    merged["log_market_cap"] = np.log(merged["market_cap"].clip(lower=1))

    merged["eps_dispersion_resid_coverage"] = _orthogonalize(merged, "eps_dispersion", ["log_coverage"])
    summ = ic_summary(compute_factor_ic(merged, "eps_dispersion_resid_coverage", "ret_12m", lower_is_better=True))
    print(f"  Coverage-orthogonalized:        mean_ic={summ['mean_ic']:+.4f}  n_months={summ['n_months']}")

    merged["eps_dispersion_resid_size_vol"] = _orthogonalize(
        merged, "eps_dispersion", ["log_market_cap", "trailing_vol_12m"]
    )
    summ = ic_summary(compute_factor_ic(merged, "eps_dispersion_resid_size_vol", "ret_12m", lower_is_better=True))
    print(f"  Size/idio-vol-orthogonalized:   mean_ic={summ['mean_ic']:+.4f}  n_months={summ['n_months']}")
    print("\n  If the raw IC above survives but these residual ICs don't, the signal is")
    print("  coverage/size/vol — not genuine analyst disagreement.")

    # ── 4. Composite A/B — live composite with vs without eps_dispersion ─────────
    print("\n" + "=" * 78)
    print("COMPOSITE A/B — live sector-neutral composite, with vs without eps_dispersion")
    print("=" * 78)
    sector_col = "sector" if "sector" in merged.columns else None
    spy_returns = load_spy_returns(prices_db_path=prices_db)

    base_cols = _VALUE_COLS + _QUALITY_COLS + [_MOMENTUM_COL]
    base_sign = {**_VALUE_SIGN, **_QUALITY_SIGN, _MOMENTUM_COL: False}
    aug_cols = base_cols + ["eps_dispersion"]
    aug_sign = {**base_sign, "eps_dispersion": True}

    for label, cols, sign_map in (
        ("baseline (no dispersion)", base_cols, base_sign),
        ("augmented (+ dispersion)", aug_cols, aug_sign),
    ):
        u = merged.copy()
        u["composite"] = composite_score(u, cols, sign_map, sector_col=sector_col)
        u = _apply_guardrails(u, "composite")
        bt = run_monthly_backtest(u, score_col="composite", tc_bps=TC_BPS, portfolios=PORTFOLIOS, sector_col=sector_col)
        bt_df = bt.get("top_n_25", pd.DataFrame())
        if bt_df.empty:
            print(f"  {label}: no data")
            continue
        ret_series = bt_df["net_return"]
        m = portfolio_metrics(ret_series, spy_returns=spy_returns)
        pf, r_exp = _profit_factor_and_expectancy(ret_series)
        turnover = bt_df["turnover"].mean()
        print(
            f"  {label:<28} CAGR {m.get('cagr', float('nan')):+7.2%}  "
            f"Sharpe {m.get('sharpe', float('nan')):6.3f}  "
            f"MaxDD {m.get('max_drawdown', float('nan')):+7.2%}  "
            f"ProfitFactor {pf:6.3f}  R-Exp {r_exp:+7.4f}  "
            f"Turnover {turnover:6.1%}  Months {m.get('n_months', 0)}"
        )

    print("\nNothing written to historic_fundamentals/baselines.py or scripts/score_live.py.")


if __name__ == "__main__":
    main()
