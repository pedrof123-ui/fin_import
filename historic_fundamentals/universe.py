"""
Investable universe filters for the fundamentals-alpha model.

Public API
----------
filter_universe(df, ...)         Apply investable universe filters to a monthly_pe DataFrame.
report_universe_counts(df, ...)  Monthly universe counts after filtering.
sensitivity_analysis(df, ...)    Market-cap sensitivity across configurable thresholds.

UNIVERSE_DEFAULTS                Dict of default filter thresholds.

Notebook integration note
-------------------------
In Cell 2b of notebooks/fundamentals_alpha.ipynb, replace the inline filter:

    MARKET_CAP_MIN = 300e6
    raw['market_cap'] = raw['shares'] * raw['price']
    raw = raw[raw['market_cap'] >= MARKET_CAP_MIN].copy()

with:

    from historic_fundamentals.universe import filter_universe, UNIVERSE_DEFAULTS
    raw['market_cap'] = raw['shares'] * raw['price']
    raw = filter_universe(raw, **UNIVERSE_DEFAULTS)
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

UNIVERSE_DEFAULTS: dict = {
    "min_market_cap": 1_000_000_000,
    "min_price": 5.0,
    "require_sector": True,
    "excluded_sectors": ["REAL ESTATE", "FINANCIAL SERVICES"],
}


def filter_universe(
    df: pd.DataFrame,
    min_market_cap: float = 1_000_000_000,
    min_price: float = 5.0,
    require_sector: bool = True,
    excluded_sectors: Optional[list[str]] = None,
    min_avg_dollar_volume: Optional[float] = None,
) -> pd.DataFrame:
    """
    Apply investable universe filters to a monthly_pe-derived DataFrame.

    Filters applied (in order):
    1. market_cap >= min_market_cap  (computed as shares * price if not present;
       NaN market_cap fails the filter — it does not bypass it)
    2. price >= min_price            (NaN fails the filter)
    3. require_sector: drop rows where sector is NaN or empty string
    4. excluded_sectors: drop rows whose sector matches any entry (case-insensitive)

    min_avg_dollar_volume is reserved for future use when volume data is available.

    Parameters
    ----------
    df : pd.DataFrame
        Monthly universe DataFrame. Must contain 'price' and either 'market_cap'
        or both 'shares' and 'price'.
    min_market_cap : float
        Minimum market cap in dollars. Default 1_000_000_000 ($1B).
    min_price : float
        Minimum share price. Default 5.0.
    require_sector : bool
        Drop rows where sector is NaN or empty. Default True.
    excluded_sectors : list of str or None
        Sectors to exclude entirely. Matched case-insensitively.
        Default None (no exclusion). UNIVERSE_DEFAULTS excludes
        REAL ESTATE and FINANCIAL SERVICES.
    min_avg_dollar_volume : float or None
        Reserved. Not implemented — no volume data available yet.

    Returns
    -------
    pd.DataFrame
        Filtered copy of df. Logs row counts at each step.
    """
    if min_avg_dollar_volume is not None:
        logger.warning(
            "min_avg_dollar_volume filter is not yet implemented (no volume data). "
            "Parameter ignored."
        )

    out = df.copy()
    n_start = len(out)
    logger.info("filter_universe: starting with %d rows", n_start)

    # ── Step 1: market_cap filter ─────────────────────────────────────────────
    if "market_cap" not in out.columns:
        if "shares" in out.columns and "price" in out.columns:
            out["market_cap"] = out["shares"] * out["price"]
        else:
            raise ValueError(
                "DataFrame must contain 'market_cap' or both 'shares' and 'price'."
            )

    # NaN market_cap fails the filter — use fillna(0) semantics via notna + >=
    mask_mc = out["market_cap"].notna() & (out["market_cap"] >= min_market_cap)
    out = out[mask_mc].copy()
    n_after_mc = len(out)
    logger.info(
        "filter_universe: market_cap >= %.0f  removed %d rows → %d remain",
        min_market_cap,
        n_start - n_after_mc,
        n_after_mc,
    )

    # ── Step 2: price filter ──────────────────────────────────────────────────
    mask_price = out["price"].notna() & (out["price"] >= min_price)
    out = out[mask_price].copy()
    n_after_price = len(out)
    logger.info(
        "filter_universe: price >= %.2f  removed %d rows → %d remain",
        min_price,
        n_after_mc - n_after_price,
        n_after_price,
    )

    # ── Step 3: sector filter ─────────────────────────────────────────────────
    if require_sector:
        if "sector" in out.columns:
            mask_sector = out["sector"].notna() & (out["sector"].astype(str).str.strip() != "")
            out = out[mask_sector].copy()
            n_after_sector = len(out)
            logger.info(
                "filter_universe: require_sector=True  removed %d rows → %d remain",
                n_after_price - n_after_sector,
                n_after_sector,
            )
        else:
            logger.warning(
                "filter_universe: require_sector=True but 'sector' column not found — skipping sector filter"
            )

    # ── Step 4: excluded sectors ──────────────────────────────────────────────
    if excluded_sectors and "sector" in out.columns:
        excluded_upper = [s.upper() for s in excluded_sectors]
        mask_excl = out["sector"].str.upper().isin(excluded_upper)
        n_before_excl = len(out)
        out = out[~mask_excl].copy()
        logger.info(
            "filter_universe: excluded_sectors %s  removed %d rows → %d remain",
            excluded_sectors,
            n_before_excl - len(out),
            len(out),
        )

    logger.info(
        "filter_universe: complete. %d rows removed total (%d → %d)",
        n_start - len(out),
        n_start,
        len(out),
    )
    return out


def report_universe_counts(
    df: pd.DataFrame,
    freq: str = "ME",
) -> pd.DataFrame:
    """
    Return a DataFrame with monthly universe counts after filtering.

    Parameters
    ----------
    df : pd.DataFrame
        Filtered monthly universe DataFrame. Must contain 'month_end_date'
        and 'ticker' columns. 'sector' column is used for sector_count if present.
    freq : str
        Pandas offset alias used to group dates. Default 'ME' (month-end).

    Returns
    -------
    pd.DataFrame
        One row per month with columns:
        month_end_date, ticker_count, sector_count
    """
    if "month_end_date" not in df.columns:
        raise ValueError("DataFrame must contain 'month_end_date' column.")
    if "ticker" not in df.columns:
        raise ValueError("DataFrame must contain 'ticker' column.")

    dates = pd.to_datetime(df["month_end_date"])
    # to_period() uses Period frequency aliases — "M" not "ME"
    period_freq = "M" if freq in ("ME", "M") else freq
    period_key = dates.dt.to_period(period_freq)

    groups = []
    for period, grp in df.groupby(period_key):
        month_end = period.to_timestamp("M")
        ticker_count = grp["ticker"].nunique()
        sector_count = grp["sector"].nunique() if "sector" in grp.columns else 0
        groups.append({
            "month_end_date": month_end,
            "ticker_count": ticker_count,
            "sector_count": sector_count,
        })

    result = pd.DataFrame(groups, columns=["month_end_date", "ticker_count", "sector_count"])
    result = result.sort_values("month_end_date").reset_index(drop=True)
    return result


def sensitivity_analysis(
    df: pd.DataFrame,
    thresholds: Optional[list[float]] = None,
    min_price: float = 5.0,
) -> pd.DataFrame:
    """
    Run market-cap sensitivity across given thresholds.

    For each threshold the full filter_universe() is applied with that
    min_market_cap value and the supplied min_price. Sector filter is
    disabled so that results vary only by market-cap threshold.

    Parameters
    ----------
    df : pd.DataFrame
        Unfiltered monthly universe DataFrame. Must contain 'market_cap' or
        both 'shares' and 'price', plus 'month_end_date' and 'ticker'.
    thresholds : list of float or None
        Market-cap thresholds to test. Default [300e6, 1e9, 5e9].
    min_price : float
        Price filter applied at every threshold. Default 5.0.

    Returns
    -------
    pd.DataFrame
        One row per threshold with columns:
        threshold_b, total_rows, unique_tickers,
        months_with_data, avg_monthly_universe_size
    """
    if thresholds is None:
        thresholds = [300e6, 1e9, 5e9]

    rows = []
    for thr in thresholds:
        filtered = filter_universe(
            df,
            min_market_cap=thr,
            min_price=min_price,
            require_sector=False,
        )
        if filtered.empty or "month_end_date" not in filtered.columns or "ticker" not in filtered.columns:
            rows.append({
                "threshold_b": thr / 1e9,
                "total_rows": 0,
                "unique_tickers": 0,
                "months_with_data": 0,
                "avg_monthly_universe_size": 0.0,
            })
            continue

        counts = report_universe_counts(filtered)
        rows.append({
            "threshold_b": thr / 1e9,
            "total_rows": len(filtered),
            "unique_tickers": filtered["ticker"].nunique(),
            "months_with_data": len(counts),
            "avg_monthly_universe_size": counts["ticker_count"].mean(),
        })

    return pd.DataFrame(rows, columns=[
        "threshold_b", "total_rows", "unique_tickers",
        "months_with_data", "avg_monthly_universe_size",
    ])
