import numpy as np
import pandas as pd


def _coerce(val) -> float:
    if val is None:
        return 0.0
    f = float(val)
    return 0.0 if np.isnan(f) else f

DEFAULT_TERMINAL_GROWTH = 0.025  # 2.5%

# WACC sensitivity grid offsets (±)
_WACC_OFFSETS = [-0.02, -0.01, 0.0, 0.01, 0.02]
_TG_OFFSETS = [-0.01, -0.005, 0.0, 0.005, 0.01]


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    return df[name].fillna(0) if name in df.columns else pd.Series(0.0, index=df.index)


def _nwc_pct(balance_df: pd.DataFrame, income_df: pd.DataFrame) -> float:
    """Estimate operating NWC as % of revenue from quarterly history."""
    nwc = (
        _col(balance_df, "total_current_assets")
        - _col(balance_df, "cash_and_equivalents")
        - _col(balance_df, "short_term_investments")
        - _col(balance_df, "total_current_liabilities")
        + _col(balance_df, "short_term_debt")
        + _col(balance_df, "current_portion_long_term_debt")
    )
    rev = _col(income_df, "revenue").replace(0, np.nan)
    ratio = pd.Series((nwc / rev).values).dropna()
    return float(ratio.mean()) if len(ratio) > 0 else 0.05


def _da_pct(income_df: pd.DataFrame) -> float:
    """Estimate D&A as % of revenue from history."""
    da = _col(income_df, "depreciation_amortization")
    rev = _col(income_df, "revenue").replace(0, np.nan)
    ratio = pd.Series((da / rev).values).dropna()
    ratio = ratio[ratio >= 0]
    return float(ratio.mean()) if len(ratio) > 0 else 0.03


def _build_fcff_series(
    year_forecasts: list,
    last_actual_revenue: float,
    tax_rate: float,
    da_pct: float,
    nwc_pct: float,
    wacc: float,
) -> list:
    from dcf.assumptions import FcffYear

    series = []
    prev_nwc = last_actual_revenue * nwc_pct
    prev_rev = last_actual_revenue

    for yf in year_forecasts:
        rev = yf.revenue
        ebit = rev * yf.operating_margin
        nopat = ebit * (1 - tax_rate)
        da = rev * da_pct
        capex = rev * yf.capex_pct_revenue
        nwc = rev * nwc_pct
        delta_nwc = nwc - prev_nwc
        fcff = nopat + da - capex - delta_nwc

        t = yf.year
        df = 1 / (1 + wacc) ** t
        pv = fcff * df

        series.append(
            FcffYear(
                year=t,
                revenue=rev,
                ebit=ebit,
                nopat=nopat,
                da=da,
                capex=capex,
                delta_nwc=delta_nwc,
                fcff=fcff,
                discount_factor=df,
                pv_fcff=pv,
            )
        )
        prev_nwc = nwc
        prev_rev = rev

    return series


def _compute_sensitivity(
    fcff_series: list,
    base_wacc: float,
    terminal_growth: float,
    last_fcff: float,
    net_debt: float,
    shares: float,
) -> list:
    from dcf.assumptions import SensitivityCell

    cells = []
    for w_off in _WACC_OFFSETS:
        for tg_off in _TG_OFFSETS:
            w = base_wacc + w_off
            tg = terminal_growth + tg_off
            if w <= tg:
                cells.append(SensitivityCell(wacc=w, terminal_growth=tg, intrinsic_value=float("nan")))
                continue

            # Recompute PV of FCFF at new WACC
            pv_sum = sum(f.fcff / (1 + w) ** f.year for f in fcff_series)
            tv = last_fcff * (1 + tg) / (w - tg)
            pv_tv = tv / (1 + w) ** len(fcff_series)
            ev = pv_sum + pv_tv
            equity = ev - net_debt
            iv = equity / shares if shares > 0 else 0
            cells.append(SensitivityCell(wacc=w, terminal_growth=tg, intrinsic_value=float(iv)))

    return cells


def _build_historical_rows(annual: dict[str, pd.DataFrame]) -> list:
    from dcf.assumptions import HistoricalRow

    inc = annual["income"].copy()
    bs = annual["balance"].copy()
    cf = annual["cashflow"].copy()

    rows = []
    for i, row in inc.iterrows():
        label = f"FY {int(row['fiscal_year'])}" if pd.notna(row.get("fiscal_year")) else str(row["period_end_date"])[:4]
        bs_row = bs.loc[i] if i in bs.index else pd.Series(dtype=float)
        cf_row = cf.loc[i] if i in cf.index else pd.Series(dtype=float)

        rows.append(
            HistoricalRow(
                period_label=label,
                revenue=_val(row, "revenue"),
                gross_profit=_val(row, "gross_profit"),
                operating_income=_val(row, "operating_income"),
                net_income=_val(row, "net_income"),
                depreciation_amortization=_val(row, "depreciation_amortization"),
                capital_expenditures=_val(cf_row, "capital_expenditures"),
                total_assets=_val(bs_row, "total_assets"),
                total_debt=_sum_debt(bs_row),
                cash_and_equivalents=_val(bs_row, "cash_and_equivalents"),
                diluted_eps=_val(row, "diluted_eps"),
            )
        )
    return rows


def _build_proforma_rows(year_forecasts: list, fcff_series: list) -> list:
    from dcf.assumptions import HistoricalRow

    rows = []
    for yf, fc in zip(year_forecasts, fcff_series):
        rows.append(
            HistoricalRow(
                period_label=f"Y+{yf.year}",
                revenue=yf.revenue,
                gross_profit=yf.revenue * yf.gross_margin,
                operating_income=fc.ebit,
                net_income=fc.nopat,  # approximation (post-tax operating)
                depreciation_amortization=fc.da,
                capital_expenditures=fc.capex,
                total_assets=None,
                total_debt=None,
                cash_and_equivalents=None,
                diluted_eps=None,
            )
        )
    return rows


def _val(row, col: str) -> float | None:
    v = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return float(v)


def _sum_debt(bs_row) -> float | None:
    parts = [
        bs_row.get("short_term_debt"),
        bs_row.get("current_portion_long_term_debt"),
        bs_row.get("long_term_debt"),
    ]
    vals = [_coerce(p) for p in parts]
    total = sum(vals)
    return total if any(p is not None for p in parts) else None


def run_dcf(
    ticker: str,
    db,
    overrides: "UserOverrides | None" = None,
) -> "DcfResult":
    from dcf.assumptions import DcfResult
    from dcf.data import load_quarterly_financials, load_annual_financials, load_current_price, load_risk_free_rate
    from dcf.wacc import compute_wacc, DEFAULT_MRP, DEFAULT_RF
    from dcf.forecaster import forecast_assumptions, merge_overrides

    quarterly = load_quarterly_financials(db, ticker)
    annual = load_annual_financials(db, ticker)

    price = load_current_price(ticker)
    rf = load_risk_free_rate()

    # Apply global overrides
    if overrides:
        if overrides.risk_free_rate is not None:
            rf = overrides.risk_free_rate
    if rf is None:
        rf = DEFAULT_RF

    mrp = DEFAULT_MRP
    beta_override = None
    if overrides:
        if overrides.market_risk_premium is not None:
            mrp = overrides.market_risk_premium
        if overrides.beta is not None:
            beta_override = overrides.beta

    effective_price = price or 0.0

    wacc_detail = compute_wacc(
        ticker=ticker,
        income_df=quarterly["income"],
        balance_df=quarterly["balance"],
        current_price=effective_price,
        risk_free_rate=rf,
        market_risk_premium=mrp,
        beta_override=beta_override,
    )

    # Forecast base case then apply overrides
    year_forecasts = forecast_assumptions(quarterly, annual)
    year_forecasts = merge_overrides(year_forecasts, overrides)

    # Terminal growth rate
    terminal_growth = DEFAULT_TERMINAL_GROWTH
    if overrides and overrides.terminal_growth_rate is not None:
        terminal_growth = overrides.terminal_growth_rate

    # Historical ratios for FCFF calculation
    da_pct = _da_pct(quarterly["income"])
    nwc_pct_val = _nwc_pct(quarterly["balance"], quarterly["income"])

    # Last actual annual revenue
    inc_a = annual["income"]
    if not inc_a.empty and inc_a["revenue"].notna().any():
        last_rev = float(inc_a["revenue"].dropna().iloc[0])  # newest first
    else:
        last_rev = float(quarterly["income"]["revenue"].dropna().iloc[-4:].sum())

    fcff_series = _build_fcff_series(
        year_forecasts=year_forecasts,
        last_actual_revenue=last_rev,
        tax_rate=wacc_detail.tax_rate,
        da_pct=da_pct,
        nwc_pct=nwc_pct_val,
        wacc=wacc_detail.wacc,
    )

    # Terminal value (Gordon Growth on last year FCFF)
    last_fcff = fcff_series[-1].fcff
    wacc = wacc_detail.wacc
    if wacc <= terminal_growth:
        terminal_growth = wacc - 0.01  # prevent division by zero

    tv = last_fcff * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_tv = tv / (1 + wacc) ** len(fcff_series)

    pv_fcff_sum = sum(f.pv_fcff for f in fcff_series)
    enterprise_value = pv_fcff_sum + pv_tv

    # Net debt
    latest_bs = quarterly["balance"].iloc[-1]
    total_debt = (
        _coerce(latest_bs.get("short_term_debt"))
        + _coerce(latest_bs.get("current_portion_long_term_debt"))
        + _coerce(latest_bs.get("long_term_debt"))
    )
    cash = _coerce(latest_bs.get("cash_and_equivalents"))
    net_debt = total_debt - cash

    equity_value = enterprise_value - net_debt

    # Shares outstanding
    shares_series = quarterly["income"]["diluted_shares"].dropna()
    shares = float(shares_series.iloc[-1]) if not shares_series.empty else 1.0

    intrinsic = equity_value / shares if shares > 0 else 0.0
    upside = (intrinsic - effective_price) / effective_price if effective_price > 0 else None

    # Sensitivity grid
    sensitivity = _compute_sensitivity(
        fcff_series=fcff_series,
        base_wacc=wacc,
        terminal_growth=terminal_growth,
        last_fcff=last_fcff,
        net_debt=net_debt,
        shares=shares,
    )

    # Historical and proforma display rows
    historical = _build_historical_rows(annual)
    proforma = _build_proforma_rows(year_forecasts, fcff_series)

    return DcfResult(
        ticker=ticker,
        intrinsic_value_per_share=float(intrinsic),
        current_price=price,
        upside_pct=float(upside) if upside is not None else None,
        wacc_detail=wacc_detail,
        terminal_growth_rate=terminal_growth,
        net_debt=net_debt,
        diluted_shares=shares,
        enterprise_value=float(enterprise_value),
        equity_value=float(equity_value),
        year_forecasts=year_forecasts,
        fcff_series=fcff_series,
        pv_terminal_value=float(pv_tv),
        historical=historical,
        proforma=proforma,
        sensitivity=sensitivity,
    )
