#!/usr/bin/env python3
"""
Mandelbrot fat-tails check: does Gaussian VaR understate real tail/drawdown
risk for (a) daily SPY returns and (b) the live composite's monthly strategy
returns (gr_top_n_25 baseline, sector-neutral guardrailed composite)?

Not a new trading signal -- this tests whether the *risk model* used to size
positions should assume normality or not. Two return series:

    1. SPY daily returns (trade_systems prices.duckdb) -- long sample (~9000+
       observations), the textbook case for demonstrating excess kurtosis.
    2. composite_baseline monthly net returns (same construction as
       scripts/test_fibonacci_walkforward.py) -- the actual live process,
       smaller sample (~400 months), asks the same question of the thing this
       project would actually size capital against.

For each series:
    - Skewness, excess kurtosis, Jarque-Bera normality test.
    - Gaussian VaR/CVaR at 95%/99% (parametric, assumes iid normal).
    - Historical (empirical) VaR/CVaR at 95%/99% (just the sample quantile/tail
      mean -- no distributional assumption).
    - Block-bootstrap resampled paths (preserves serial correlation/vol
      clustering) -> distribution of realized max drawdown across resamples.
    - Moment-matched Gaussian iid simulation (same mean/vol, no fat tails) ->
      distribution of max drawdown under the Gaussian assumption.
    - The gap between the two max-drawdown distributions is the concrete case
      for sizing off empirical/bootstrapped drawdowns instead of a Gaussian
      VaR/CVaR formula.

Usage:
    uv run scripts/analyze_fat_tails.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from scipy import stats

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
from historic_fundamentals.backtest import run_monthly_backtest  # noqa: E402
from scripts.run_backtest import _load_monthly_pe, _join_sector, _apply_guardrails  # noqa: E402

log = logging.getLogger(__name__)

N_BOOTSTRAP = 5000
RNG_SEED = 42


def _composite(df: pd.DataFrame) -> pd.Series:
    value_cols = [c for c in _VALUE_COLS if c in df.columns and df[c].notna().any()]
    value_sign = {c: _VALUE_SIGN[c] for c in value_cols}
    quality_cols = [c for c in _QUALITY_COLS if c in df.columns and df[c].notna().any()]
    quality_sign = {c: _QUALITY_SIGN[c] for c in quality_cols}
    has_momentum = _MOMENTUM_COL in df.columns and df[_MOMENTUM_COL].notna().any()
    cols = value_cols + quality_cols + ([_MOMENTUM_COL] if has_momentum else [])
    sign_map = {**value_sign, **quality_sign, **({_MOMENTUM_COL: False} if has_momentum else {})}
    return composite_score(df, cols, sign_map, sector_neutral=True)


def _load_spy_daily(prices_db_path: str) -> pd.Series:
    import duckdb
    conn = duckdb.connect(prices_db_path, read_only=True)
    df = conn.execute(
        "SELECT date, adj_close FROM etf_prices WHERE ticker = 'SPY' ORDER BY date"
    ).df()
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["adj_close"].pct_change().dropna()
    return s


def _load_composite_baseline_monthly(hf_db: str, av_db: str) -> pd.Series:
    raw = _load_monthly_pe(hf_db)
    raw = _join_sector(raw, av_db)
    raw["market_cap"] = raw["shares"] * raw["price"]
    universe = filter_universe(raw, **UNIVERSE_DEFAULTS)
    universe["composite_baseline"] = _composite(universe)
    gr = _apply_guardrails(universe, "composite_baseline")
    bt = run_monthly_backtest(
        gr, score_col="composite_baseline", tc_bps=10.0, portfolios={"top_n_25": 25},
        sector_col="sector", max_sector_pct=0.25,
    )
    return bt["top_n_25"]["net_return"].dropna()


# ── Risk metrics ──────────────────────────────────────────────────────────────

def _gaussian_var_cvar(returns: np.ndarray, alpha: float) -> tuple[float, float]:
    mu, sigma = returns.mean(), returns.std(ddof=1)
    z = stats.norm.ppf(1 - alpha)
    var = -(mu + z * sigma)
    # Gaussian CVaR (expected shortfall) closed form
    cvar = -(mu - sigma * stats.norm.pdf(z) / (1 - alpha))
    return var, cvar


def _historical_var_cvar(returns: np.ndarray, alpha: float) -> tuple[float, float]:
    q = np.percentile(returns, (1 - alpha) * 100)
    var = -q
    tail = returns[returns <= q]
    cvar = -tail.mean() if len(tail) > 0 else np.nan
    return var, cvar


def _max_drawdown(path_returns: np.ndarray) -> float:
    cum = np.cumprod(1 + path_returns)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return float(dd.min())


def _block_bootstrap_maxdd(returns: np.ndarray, n_boot: int, block_size: int, rng: np.random.Generator) -> np.ndarray:
    n = len(returns)
    n_blocks = int(np.ceil(n / block_size))
    out = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        path = np.concatenate([returns[s:s + block_size] for s in starts])[:n]
        out[i] = _max_drawdown(path)
    return out


def _gaussian_iid_maxdd(mu: float, sigma: float, n: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    out = np.empty(n_boot)
    for i in range(n_boot):
        path = rng.normal(mu, sigma, size=n)
        out[i] = _max_drawdown(path)
    return out


def _analyze(label: str, returns: pd.Series, block_size: int, periods_per_year: int) -> None:
    r = returns.dropna().values
    n = len(r)
    mu, sigma = r.mean(), r.std(ddof=1)
    skew = stats.skew(r)
    kurt = stats.kurtosis(r)  # excess kurtosis (Gaussian = 0)
    jb_stat, jb_p = stats.jarque_bera(r)

    print(f"\n{'=' * 84}\n{label}  (n={n}, {periods_per_year} periods/yr)\n{'=' * 84}")
    print(f"  mean={mu:+.5f}  std={sigma:.5f}  ann.vol={sigma * np.sqrt(periods_per_year):.2%}")
    print(f"  skew={skew:+.3f}  excess kurtosis={kurt:+.3f}  Jarque-Bera p={jb_p:.2e}"
          f"  {'(REJECTS normality)' if jb_p < 0.01 else '(fails to reject normality)'}")

    print(f"\n  {'':20}{'VaR 95%':>10}{'CVaR 95%':>10}{'VaR 99%':>10}{'CVaR 99%':>10}")
    for name, fn in [("Gaussian (parametric)", _gaussian_var_cvar), ("Historical (empirical)", _historical_var_cvar)]:
        v95, c95 = fn(r, 0.95)
        v99, c99 = fn(r, 0.99)
        print(f"  {name:20}{v95:>10.2%}{c95:>10.2%}{v99:>10.2%}{c99:>10.2%}")

    rng = np.random.default_rng(RNG_SEED)
    boot_dd = _block_bootstrap_maxdd(r, N_BOOTSTRAP, block_size, rng)
    gauss_dd = _gaussian_iid_maxdd(mu, sigma, n, N_BOOTSTRAP, rng)
    actual_dd = _max_drawdown(r)

    print(f"\n  Max-drawdown distribution over a {n}-period path ({N_BOOTSTRAP} resamples):")
    print(f"  {'':28}{'p50':>9}{'p75':>9}{'p90':>9}{'p95':>9}{'p99':>9}")
    for name, dd in [("Block bootstrap (empirical)", boot_dd), ("Gaussian iid (moment-matched)", gauss_dd)]:
        pcts = np.percentile(dd, [50, 75, 90, 95, 99])
        print(f"  {name:28}" + "".join(f"{p:>9.1%}" for p in pcts))
    print(f"  Actual realized max drawdown over the full sample: {actual_dd:+.2%}")

    p95_boot = np.percentile(boot_dd, 95)
    p95_gauss = np.percentile(gauss_dd, 95)
    gap = p95_boot - p95_gauss
    print(f"\n  Gaussian understates the 95th-percentile max drawdown by "
          f"{abs(gap):.1%} of NAV ({p95_gauss:.1%} assumed vs {p95_boot:.1%} empirical)"
          if gap < 0 else
          f"\n  Gaussian 95th-percentile max drawdown is within {abs(gap):.1%} of the empirical estimate.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hf_db = os.getenv("HF_DB_PATH", str(ROOT / "data" / "historic_fundamentals.duckdb"))
    av_db = os.getenv("AV_DB_PATH", str(ROOT / "data" / "av_financials.duckdb"))
    prices_db = os.getenv("PRICES_DB_PATH", str(ROOT / "data" / "prices.duckdb"))

    log.info("Loading SPY daily returns ...")
    spy_daily = _load_spy_daily(prices_db)
    log.info("Loaded %d daily SPY returns (%s to %s)", len(spy_daily), spy_daily.index.min().date(), spy_daily.index.max().date())

    log.info("Building composite_baseline monthly returns (gr_top_n_25) ...")
    composite_monthly = _load_composite_baseline_monthly(hf_db, av_db)
    log.info("Loaded %d monthly composite returns (%s to %s)",
              len(composite_monthly), composite_monthly.index.min().date(), composite_monthly.index.max().date())

    _analyze("SPY DAILY RETURNS", spy_daily, block_size=20, periods_per_year=252)
    _analyze("COMPOSITE_BASELINE MONTHLY RETURNS (gr_top_n_25, live process)", composite_monthly, block_size=6, periods_per_year=12)

    print("\nDone.")


if __name__ == "__main__":
    main()
