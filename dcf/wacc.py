from datetime import date

import numpy as np
import pandas as pd


def _coerce(val) -> float:
    if val is None:
        return 0.0
    f = float(val)
    return 0.0 if np.isnan(f) else f


DEFAULT_MRP = 0.055  # 5.5% Damodaran estimate
DEFAULT_RF = 0.045   # fallback if fred.duckdb unavailable


def get_betas(ticker: str, as_of: date | None = None) -> tuple[float | None, float | None]:
    """Return (beta_5yr, beta_2yr) from stored weekly betas, as of `as_of` when given."""
    from features.beta.beta import get_beta as _get_beta, WINDOW_5YR, WINDOW_2YR
    return (
        _get_beta(ticker, as_of_date=as_of, window_days=WINDOW_5YR),
        _get_beta(ticker, as_of_date=as_of, window_days=WINDOW_2YR),
    )


def compute_effective_tax_rate(income_df: pd.DataFrame) -> float:
    """5-year average effective tax rate, clamped [15%, 40%]."""
    pretax = income_df["pretax_income"].replace(0, np.nan)
    tax = income_df["income_tax_expense"]
    rates = (tax / pretax).dropna()
    rates = rates[rates > 0]
    if rates.empty:
        return 0.21
    return float(np.clip(rates.mean(), 0.15, 0.40))


def compute_cost_of_debt(income_df: pd.DataFrame, balance_df: pd.DataFrame) -> float:
    """Estimate kd = avg_interest_expense / avg_total_debt. Clamped [2%, 15%]."""
    ie = income_df["interest_expense"].dropna().abs()
    debt = sum(
        balance_df[col].fillna(0)
        for col in ("short_term_debt", "current_portion_long_term_debt", "long_term_debt")
        if col in balance_df.columns
    )
    avg_debt = debt.mean() if hasattr(debt, "mean") else 0
    if ie.empty or avg_debt < 1e6:
        return 0.05
    return float(np.clip(ie.mean() / avg_debt, 0.02, 0.15))


def _relever_beta(beta_raw: float, tax_rate: float, de_hist: float, de_forecast: float) -> float:
    if de_hist <= 0:
        return beta_raw
    beta_u = beta_raw / (1 + (1 - tax_rate) * de_hist)
    return beta_u * (1 + (1 - tax_rate) * de_forecast)


def compute_wacc(
    ticker: str,
    income_df: pd.DataFrame,
    balance_df: pd.DataFrame,
    current_price: float,
    risk_free_rate: float,
    market_risk_premium: float = DEFAULT_MRP,
    beta_override: float | None = None,
    cost_of_debt_override: float | None = None,
    cost_of_debt_terminal_override: float | None = None,
    tax_rate_override: float | None = None,
    annual_income_df: pd.DataFrame | None = None,
    as_of: date | None = None,
) -> "WaccDetail":
    from dcf.assumptions import WaccDetail

    beta_5yr_stored, beta_2yr_stored = get_betas(ticker, as_of=as_of)
    beta_raw = beta_override if beta_override is not None else (beta_5yr_stored or 1.0)
    tax_rate = tax_rate_override if tax_rate_override is not None else compute_effective_tax_rate(income_df)

    # Annual income gives a full-year interest expense, yielding the correct annual kd.
    # Fall back to quarterly income only when annual data is unavailable.
    kd_income = annual_income_df if (annual_income_df is not None and not annual_income_df.empty) else income_df
    kd = cost_of_debt_override if cost_of_debt_override is not None else compute_cost_of_debt(kd_income, balance_df)

    # Terminal-value-only cost of debt: a real disclosed coupon on this company's
    # long-dated bonds, when available, instead of the embedded whole-book rate that
    # blends in cheap pre-rate-hike debt (see PLAN_DEBT_MATURITY.md). Not clamped like
    # `kd` above -- that clamp guards a noisy *estimate*; this is a reported rate.
    kd_terminal = cost_of_debt_terminal_override
    if kd_terminal is None:
        from debt_maturity.db import get_summary
        maturity_summary = get_summary(ticker)
        if maturity_summary is not None:
            kd_terminal = maturity_summary.get("weighted_avg_coupon_long_dated")

    latest = balance_df.iloc[-1] if not balance_df.empty else pd.Series(dtype=float)
    total_debt = (
        _coerce(latest.get("short_term_debt"))
        + _coerce(latest.get("current_portion_long_term_debt"))
        + _coerce(latest.get("long_term_debt"))
    )

    # Shares: prefer quarterly (most recent); fall back to annual; then derive from net_income/EPS.
    qshares = income_df["diluted_shares"].dropna() if "diluted_shares" in income_df.columns else pd.Series(dtype=float)
    diluted_shares = float(qshares.iloc[-1]) if not qshares.empty else 0.0
    if diluted_shares == 0 and annual_income_df is not None and not annual_income_df.empty:
        ashares = annual_income_df["diluted_shares"].dropna() if "diluted_shares" in annual_income_df.columns else pd.Series(dtype=float)
        if not ashares.empty:
            diluted_shares = float(ashares.iloc[0])  # annual sorted newest-first
    if diluted_shares == 0:
        # Derive from net_income / diluted_eps: quarterly first (iloc[-1] = newest, sorted ASC),
        # then annual (iloc[0] = newest, sorted DESC).
        for df, idx in [(income_df, -1), (annual_income_df, 0)]:
            if df is None or df.empty:
                continue
            try:
                ni = abs(float(df["net_income"].dropna().iloc[idx]))
                eps = abs(float(df["diluted_eps"].dropna().iloc[idx]))
                if ni > 0 and eps > 0:
                    diluted_shares = ni / eps
                    break
            except (IndexError, KeyError, ValueError):
                continue

    market_cap = current_price * diluted_shares

    de_hist = total_debt / market_cap if market_cap > 0 else 0
    beta_rel = _relever_beta(beta_raw, tax_rate, de_hist, de_hist)

    ke = risk_free_rate + beta_rel * market_risk_premium
    V = total_debt + market_cap
    D_w = total_debt / V if V > 0 else 0
    E_w = market_cap / V if V > 0 else 1.0
    wacc = ke * E_w + kd * (1 - tax_rate) * D_w
    wacc_terminal = ke * E_w + kd_terminal * (1 - tax_rate) * D_w if kd_terminal is not None else None

    return WaccDetail(
        beta_raw=beta_raw,
        beta_relevered=beta_rel,
        risk_free_rate=risk_free_rate,
        market_risk_premium=market_risk_premium,
        cost_of_equity=ke,
        cost_of_debt=kd,
        tax_rate=tax_rate,
        debt_weight=D_w,
        equity_weight=E_w,
        wacc=wacc,
        total_debt=total_debt,
        market_cap=market_cap,
        beta_2yr=beta_2yr_stored,
        cost_of_debt_terminal=kd_terminal,
        wacc_terminal=wacc_terminal,
    )
