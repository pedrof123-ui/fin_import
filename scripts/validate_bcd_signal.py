"""Phase 3 validation of the BCD-lite mispricing signal.

Tests:
  1. Standalone IC/ICIR of bcd_misp vs ret_1y (cross-sectional Spearman, NW-corrected)
  2. Sign consistency: fraction of annual periods where mean IC < 0
     (negative Misp = underpriced stocks → positive excess return)
  3. Mean-reversion speed: autocorrelation of bcd_misp vs pe_ratio at lags 1-24 months
  4. Punder regression: monthly punder vs SPY 12-month forward return
  5. Sector coverage: bcd_misp fill rate by sector

Pass gate (required before Phase 4 model retrain):
  - NW-ICIR absolute value > 0.30
  - Consistent negative IC in >= 60% of annual periods
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from historic_fundamentals.model import _newey_west_icir  # noqa: E402

HF_DB = ROOT / "data" / "historic_fundamentals.duckdb"
PRICES_DB = Path("/home/pedro/projects/trade_systems/data/prices.duckdb")
AV_DB = ROOT / "data" / "av_financials.duckdb"

NW_LAGS = 11  # for 12-month forward returns
MIN_STOCKS_PER_MONTH = 30


def load_data() -> pd.DataFrame:
    conn = duckdb.connect(str(HF_DB), read_only=True)
    df = conn.execute("""
        SELECT ticker, month_end_date, price, bcd_misp, pe_ratio, earn_growth_1yr
        FROM monthly_pe
        WHERE price > 0
        ORDER BY ticker, month_end_date
    """).df()
    conn.close()
    df["month_end_date"] = pd.to_datetime(df["month_end_date"])
    return df


def compute_forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Compute 12-month forward price return within each ticker."""
    df = df.sort_values(["ticker", "month_end_date"]).copy()
    df["price_fwd12"] = df.groupby("ticker")["price"].shift(-12)
    df["ret_1y"] = df["price_fwd12"] / df["price"] - 1.0
    return df


def compute_standalone_ic(df: pd.DataFrame) -> dict:
    """Cross-sectional Spearman IC per month between bcd_misp and ret_1y."""
    valid = df.dropna(subset=["bcd_misp", "ret_1y"])
    monthly_ic = []
    for date, grp in valid.groupby("month_end_date"):
        if len(grp) < MIN_STOCKS_PER_MONTH:
            continue
        ic, _ = stats.spearmanr(grp["bcd_misp"], grp["ret_1y"])
        if not np.isnan(ic):
            monthly_ic.append({"date": date, "ic": ic, "n": len(grp)})

    ic_df = pd.DataFrame(monthly_ic).set_index("date").sort_index()
    ic_arr = ic_df["ic"].values

    mean_ic = float(np.mean(ic_arr))
    std_ic = float(np.std(ic_arr, ddof=1))
    icir = mean_ic / std_ic if std_ic > 0 else np.nan
    icir_nw = _newey_west_icir(ic_arr, lags=NW_LAGS)
    t_stat = mean_ic / (std_ic / np.sqrt(len(ic_arr))) if std_ic > 0 else np.nan
    hit_rate = float((ic_arr < 0).mean())  # IC < 0 = underpriced stocks outperform

    # Annual sign consistency
    ic_df["year"] = ic_df.index.year
    annual_mean_ic = ic_df.groupby("year")["ic"].mean()
    sign_consistent_pct = float((annual_mean_ic < 0).mean())

    return {
        "n_months": len(ic_arr),
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "icir": icir,
        "icir_nw": icir_nw,
        "t_stat": t_stat,
        "hit_rate_negative": hit_rate,
        "sign_consistent_pct": sign_consistent_pct,
        "ic_df": ic_df,
        "annual_mean_ic": annual_mean_ic,
    }


def compute_autocorrelations(df: pd.DataFrame, lags: list[int]) -> pd.DataFrame:
    """Panel autocorrelation of bcd_misp and pe_ratio at given lags."""
    results = []
    for lag in lags:
        for col in ["bcd_misp", "pe_ratio"]:
            sub = df.dropna(subset=[col]).copy()
            sub["lagged"] = sub.groupby("ticker")[col].shift(lag)
            sub = sub.dropna(subset=["lagged"])
            if len(sub) < 1000:
                continue
            corr, _ = stats.spearmanr(sub[col], sub["lagged"])
            results.append({"feature": col, "lag": lag, "autocorr": corr, "n": len(sub)})

    return pd.DataFrame(results)


def compute_punder_regression() -> dict:
    """Regress SPY 12-month forward return on monthly punder."""
    # Load punder
    conn = duckdb.connect(str(HF_DB), read_only=True)
    punder_df = conn.execute(
        "SELECT month_end_date, punder FROM market_signals ORDER BY month_end_date"
    ).df()
    conn.close()
    punder_df["month_end_date"] = pd.to_datetime(punder_df["month_end_date"])
    punder_df = punder_df.set_index("month_end_date").sort_index()

    # Load SPY monthly closes from etf_prices
    prices_conn = duckdb.connect(str(PRICES_DB), read_only=True)
    spy = prices_conn.execute(
        "SELECT date, close FROM etf_prices WHERE ticker = 'SPY' ORDER BY date"
    ).df()
    prices_conn.close()
    spy["date"] = pd.to_datetime(spy["date"])

    # Resample to month-end
    spy = spy.set_index("date").resample("ME")["close"].last().rename("spy_close")
    spy.index = spy.index.to_period("M").to_timestamp("M")

    # 12-month forward return for SPY
    spy_fwd12 = spy.shift(-12) / spy - 1.0
    spy_fwd12.name = "spy_ret_12m"

    # Align with punder
    merged = punder_df.join(spy_fwd12, how="inner").dropna()
    if len(merged) < 30:
        return {"error": f"Too few aligned months: {len(merged)}"}

    slope, intercept, r, p_value, se = stats.linregress(merged["punder"], merged["spy_ret_12m"])
    r_squared = r ** 2

    return {
        "n_months": len(merged),
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_squared,
        "p_value": p_value,
        "merged": merged,
    }


def compute_sector_coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Fill rate of bcd_misp by sector."""
    try:
        conn = duckdb.connect(str(AV_DB), read_only=True)
        # one row per refresh in company_overview — keep the latest, else the merge fans out
        sectors = conn.execute("""SELECT ticker, sector FROM company_overview WHERE sector IS NOT NULL
            QUALIFY fetch_date = MAX(fetch_date) OVER (PARTITION BY ticker)""").df()
        conn.close()
        df = df.merge(sectors, on="ticker", how="left")
    except Exception:
        return pd.DataFrame()

    coverage = df.groupby("sector").apply(
        lambda g: pd.Series({
            "rows": len(g),
            "bcd_non_null": g["bcd_misp"].notna().sum(),
            "pct": 100.0 * g["bcd_misp"].notna().mean(),
        })
    ).sort_values("pct")
    return coverage


def main() -> None:
    print("Loading data...")
    df = load_data()
    df = compute_forward_returns(df)
    print(f"  {len(df):,} rows, {df['ticker'].nunique()} tickers, "
          f"{df['month_end_date'].min().date()} to {df['month_end_date'].max().date()}")

    # ── Test 1: Standalone IC/ICIR ──────────────────────────────────────────
    print("\n=== Test 1: Standalone IC/ICIR (bcd_misp vs ret_1y) ===")
    ic_result = compute_standalone_ic(df)
    print(f"  Months with data:       {ic_result['n_months']}")
    print(f"  Mean IC:                {ic_result['mean_ic']:.4f}")
    print(f"  Std IC:                 {ic_result['std_ic']:.4f}")
    print(f"  ICIR (raw):             {ic_result['icir']:.4f}")
    print(f"  NW-ICIR (lag=11):       {ic_result['icir_nw']:.4f}")
    print(f"  t-stat:                 {ic_result['t_stat']:.4f}")
    print(f"  IC<0 hit rate:          {ic_result['hit_rate_negative']:.1%}")
    print(f"  Annual sign consistency:{ic_result['sign_consistent_pct']:.1%}")

    nw_icir = ic_result["icir_nw"]
    sign_pct = ic_result["sign_consistent_pct"]
    gate_icir = abs(nw_icir) > 0.30
    gate_sign = sign_pct >= 0.60
    print(f"\n  Gate NW-ICIR > 0.30:    {'PASS' if gate_icir else 'FAIL'} ({abs(nw_icir):.3f})")
    print(f"  Gate sign >= 60%:       {'PASS' if gate_sign else 'FAIL'} ({sign_pct:.1%})")

    print("\n  Annual mean IC by year:")
    for yr, ic_val in ic_result["annual_mean_ic"].items():
        flag = "(-)" if ic_val < 0 else "(+)"
        print(f"    {yr}: {ic_val:+.4f} {flag}")

    # ── Test 2: Mean-reversion speed ─────────────────────────────────────────
    print("\n=== Test 2: Mean-reversion autocorrelation ===")
    lags = [1, 6, 12, 18, 24]
    autocorr_df = compute_autocorrelations(df, lags)
    if not autocorr_df.empty:
        print(f"  {'Lag':>4}  {'bcd_misp':>10}  {'pe_ratio':>10}  {'faster?':>8}")
        print(f"  {'-'*4}  {'-'*10}  {'-'*10}  {'-'*8}")
        for lag in lags:
            bcd = autocorr_df.query("feature=='bcd_misp' and lag==@lag")["autocorr"].values
            pe = autocorr_df.query("feature=='pe_ratio' and lag==@lag")["autocorr"].values
            bcd_v = bcd[0] if len(bcd) else float("nan")
            pe_v = pe[0] if len(pe) else float("nan")
            faster = "YES" if (not np.isnan(bcd_v) and not np.isnan(pe_v) and abs(bcd_v) < abs(pe_v)) else "no"
            print(f"  {lag:>4}  {bcd_v:>10.4f}  {pe_v:>10.4f}  {faster:>8}")

        lag12_bcd = autocorr_df.query("feature=='bcd_misp' and lag==12")["autocorr"].values
        lag12_pe = autocorr_df.query("feature=='pe_ratio' and lag==12")["autocorr"].values
        if len(lag12_bcd) and len(lag12_pe):
            gate_revert = abs(lag12_bcd[0]) < abs(lag12_pe[0])
            print(f"\n  Gate lag-12 bcd_misp < pe_ratio: {'PASS' if gate_revert else 'FAIL'}")

    # ── Test 3: Punder regression ─────────────────────────────────────────────
    print("\n=== Test 3: Punder vs SPY 12-month forward return ===")
    punder_result = compute_punder_regression()
    if "error" in punder_result:
        print(f"  ERROR: {punder_result['error']}")
    else:
        print(f"  N months:    {punder_result['n_months']}")
        print(f"  Slope:       {punder_result['slope']:.4f}")
        print(f"  R²:          {punder_result['r_squared']:.4f}")
        print(f"  p-value:     {punder_result['p_value']:.4f}")
        gate_punder = punder_result["slope"] > 0 and punder_result["p_value"] < 0.10
        print(f"\n  Gate slope>0 & p<0.10:  {'PASS' if gate_punder else 'FAIL'}")

    # ── Test 4: Sector coverage ───────────────────────────────────────────────
    print("\n=== Test 4: Sector coverage ===")
    coverage = compute_sector_coverage(df)
    if not coverage.empty:
        print(f"  {'Sector':<35}  {'Pct':>6}  {'Rows':>7}")
        print(f"  {'-'*35}  {'-'*6}  {'-'*7}")
        for sector, row in coverage.iterrows():
            flag = " <-- low" if row["pct"] < 40 else ""
            print(f"  {str(sector):<35}  {row['pct']:>5.1f}%  {int(row['rows']):>7}{flag}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n=== Phase 3 Gate Summary ===")
    print(f"  NW-ICIR > 0.30:          {'PASS' if gate_icir else 'FAIL'} ({abs(nw_icir):.3f})")
    print(f"  Sign consistency >= 60%:  {'PASS' if gate_sign else 'FAIL'} ({sign_pct:.1%})")
    if not autocorr_df.empty and len(lag12_bcd) and len(lag12_pe):
        print(f"  Lag-12 autocorr faster:  {'PASS' if gate_revert else 'FAIL'}")
    if "error" not in punder_result:
        print(f"  Punder regression:       {'PASS' if gate_punder else 'FAIL'}")

    if gate_icir and gate_sign:
        print("\n  --> Phase 4 gate MET. Proceed to model retrain with explicit decision.")
    else:
        print("\n  --> Phase 4 gate NOT met. Investigate signal before retraining.")


if __name__ == "__main__":
    main()
