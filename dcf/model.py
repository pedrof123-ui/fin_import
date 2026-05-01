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


def _nwc_from_days(
    revenue: float,
    cogs: float,
    dso: float,
    dpo: float,
    dio: float,
) -> float:
    """
    NWC = receivables + inventory - payables
    receivables = revenue * DSO / 365
    payables    = cogs    * DPO / 365
    inventory   = cogs    * DIO / 365
    """
    receivables = revenue * dso / 365
    payables = cogs * dpo / 365
    inventory = cogs * dio / 365
    return receivables + inventory - payables


def _da_pct(income_df: pd.DataFrame, cashflow_df: pd.DataFrame | None = None) -> float:
    """
    Estimate D&A as % of revenue. Prefers CF statement since most companies
    report D&A there (as a non-cash add-back) rather than on the income statement.
    """
    rev = _col(income_df, "revenue").replace(0, np.nan)

    if cashflow_df is not None and not cashflow_df.empty:
        da_cf = _col(cashflow_df, "depreciation_amortization")
        if da_cf.abs().gt(0).any() and "period_end_date" in income_df.columns and "period_end_date" in cashflow_df.columns:
            merged = pd.merge(
                income_df[["period_end_date", "revenue"]],
                cashflow_df[["period_end_date", "depreciation_amortization"]],
                on="period_end_date",
                how="inner",
            )
            if not merged.empty:
                rev_m = merged["revenue"].replace(0, np.nan)
                da_m = merged["depreciation_amortization"].fillna(0).abs()
                ratio = (da_m / rev_m).dropna()
                ratio = ratio[ratio > 0]
                if not ratio.empty:
                    return float(ratio.mean())

    da = _col(income_df, "depreciation_amortization").abs()
    ratio = pd.Series((da / rev).values).dropna()
    ratio = ratio[ratio > 0]
    return float(ratio.mean()) if len(ratio) > 0 else 0.03


def _build_fcff_series(
    year_forecasts: list,
    last_actual_revenue: float,
    last_actual_cogs: float,
    tax_rate: float,
    da_pct: float,
    nwc_assumptions,
    wacc: float,
) -> list:
    from dcf.assumptions import FcffYear

    series = []
    prev_nwc = _nwc_from_days(
        last_actual_revenue,
        last_actual_cogs,
        nwc_assumptions.dso,
        nwc_assumptions.dpo,
        nwc_assumptions.dio,
    )

    for yf in year_forecasts:
        rev = yf.revenue
        rd = yf.rd_pct or 0.0
        ebit = rev * (1.0 - yf.cogs_pct - yf.sga_pct - rd)
        nopat = ebit * (1 - tax_rate)
        da = rev * da_pct
        capex = rev * yf.capex_pct_revenue
        cogs = rev * yf.cogs_pct
        nwc = _nwc_from_days(rev, cogs, nwc_assumptions.dso, nwc_assumptions.dpo, nwc_assumptions.dio)
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

    # Align balance sheet and cash flow by period_end_date so that differences
    # in row count between statements don't silently swap or drop values.
    def _date_index(df):
        return df.set_index("period_end_date") if "period_end_date" in df.columns else df

    bs_by_date = _date_index(bs)
    cf_by_date = _date_index(cf)

    rows = []
    for _, row in inc.iterrows():
        date = str(row.get("period_end_date", ""))[:10] if pd.notna(row.get("period_end_date")) else None
        label = f"FY {int(row['fiscal_year'])}" if pd.notna(row.get("fiscal_year")) else (date[:4] if date else "")

        bs_row = bs_by_date.loc[date] if date and date in bs_by_date.index else pd.Series(dtype=float)
        cf_row = cf_by_date.loc[date] if date and date in cf_by_date.index else pd.Series(dtype=float)

        # Prefer CF statement D&A since most companies report it there
        da_cf = _val(cf_row, "depreciation_amortization")
        da_inc = _val(row, "depreciation_amortization")
        da = da_cf if da_cf is not None else da_inc

        rows.append(
            HistoricalRow(
                period_label=label,
                period_end_date=date,
                revenue=_val(row, "revenue"),
                gross_profit=_val(row, "gross_profit"),
                operating_income=_val(row, "operating_income"),
                net_income=_val(row, "net_income"),
                depreciation_amortization=da,
                capital_expenditures=_val(cf_row, "capital_expenditures"),
                total_assets=_val(bs_row, "total_assets"),
                total_debt=_sum_debt(bs_row),
                cash_and_equivalents=_val(bs_row, "cash_and_equivalents"),
                diluted_eps=_val(row, "diluted_eps"),
                cost_of_revenue=_val(row, "cost_of_revenue"),
                selling_general_admin=_val(row, "selling_general_admin"),
                research_development=_val(row, "research_development"),
                interest_expense=_val(row, "interest_expense"),
            )
        )
    return rows


def _build_proforma_rows(year_forecasts: list, fcff_series: list, tax_rate: float) -> list:
    from dcf.assumptions import HistoricalRow

    rows = []
    for yf, fc in zip(year_forecasts, fcff_series):
        rev = yf.revenue
        cogs = rev * yf.cogs_pct
        gross_profit = rev - cogs
        rd = yf.rd_pct or 0.0
        # Net income ≈ (EBIT - interest) * (1 - tax_rate) + other adjustments
        interest = rev * yf.interest_pct
        other = rev * yf.other_pct
        net_income = (fc.ebit - interest + other) * (1 - tax_rate)

        rows.append(
            HistoricalRow(
                period_label=f"Y+{yf.year}",
                revenue=rev,
                gross_profit=gross_profit,
                operating_income=fc.ebit,
                net_income=net_income,
                depreciation_amortization=fc.da,
                capital_expenditures=fc.capex,
                total_assets=None,
                total_debt=None,
                cash_and_equivalents=None,
                diluted_eps=None,
                cost_of_revenue=cogs,
                selling_general_admin=rev * yf.sga_pct,
                research_development=rev * rd if yf.rd_pct is not None else None,
                interest_expense=interest,
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
    from dcf.wacc import compute_wacc, compute_effective_tax_rate, DEFAULT_MRP, DEFAULT_RF
    from dcf.forecaster import forecast_assumptions, merge_overrides, compute_nwc_days

    quarterly = load_quarterly_financials(db, ticker)
    annual = load_annual_financials(db, ticker)

    price = load_current_price(ticker)
    rf = load_risk_free_rate()

    if overrides and overrides.risk_free_rate is not None:
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

    # Tax rate from last 5 annual periods: avoids pre-TCJA history and transition-year anomalies
    # that distort the average when all quarterly periods are included.
    annual_tax_rate = compute_effective_tax_rate(annual["income"].iloc[:5].reset_index(drop=True))

    wacc_detail = compute_wacc(
        ticker=ticker,
        income_df=quarterly["income"],
        balance_df=quarterly["balance"],
        current_price=effective_price,
        risk_free_rate=rf,
        market_risk_premium=mrp,
        beta_override=beta_override,
        cost_of_debt_override=overrides.cost_of_debt_override if overrides else None,
        tax_rate_override=overrides.tax_rate_override if overrides else annual_tax_rate,
    )

    year_forecasts = forecast_assumptions(quarterly, annual)
    year_forecasts = merge_overrides(year_forecasts, overrides)

    terminal_growth = DEFAULT_TERMINAL_GROWTH
    if overrides and overrides.terminal_growth_rate is not None:
        terminal_growth = overrides.terminal_growth_rate

    da_pct = _da_pct(annual["income"], annual["cashflow"])

    # NWC via DSO/DPO/DIO
    nwc_assumptions = compute_nwc_days(annual["balance"], annual["income"])
    if overrides:
        if overrides.dso is not None:
            nwc_assumptions.dso = overrides.dso
        if overrides.dpo is not None:
            nwc_assumptions.dpo = overrides.dpo
        if overrides.dio is not None:
            nwc_assumptions.dio = overrides.dio

    # Last actual annual revenue and COGS
    inc_a = annual["income"]
    if not inc_a.empty and inc_a["revenue"].notna().any():
        last_rev = float(inc_a["revenue"].dropna().iloc[0])  # newest first
    else:
        last_rev = float(quarterly["income"]["revenue"].dropna().iloc[-4:].sum())

    # Last actual COGS for initial NWC seed
    if not inc_a.empty and "cost_of_revenue" in inc_a.columns and inc_a["cost_of_revenue"].notna().any():
        last_cogs = float(inc_a["cost_of_revenue"].dropna().iloc[0])
    elif not inc_a.empty and "gross_profit" in inc_a.columns and inc_a["gross_profit"].notna().any():
        last_cogs = last_rev - float(inc_a["gross_profit"].dropna().iloc[0])
    else:
        last_cogs = last_rev * year_forecasts[0].cogs_pct

    fcff_series = _build_fcff_series(
        year_forecasts=year_forecasts,
        last_actual_revenue=last_rev,
        last_actual_cogs=last_cogs,
        tax_rate=wacc_detail.tax_rate,
        da_pct=da_pct,
        nwc_assumptions=nwc_assumptions,
        wacc=wacc_detail.wacc,
    )

    last_fcff = fcff_series[-1].fcff
    wacc = wacc_detail.wacc
    if wacc <= terminal_growth:
        terminal_growth = wacc - 0.01

    terminal_value = last_fcff * (1 + terminal_growth) / (wacc - terminal_growth)
    pv_tv = terminal_value / (1 + wacc) ** len(fcff_series)

    pv_fcff_sum = sum(f.pv_fcff for f in fcff_series)
    enterprise_value = pv_fcff_sum + pv_tv
    tv_pct_ev = pv_tv / enterprise_value if enterprise_value != 0 else 0.0

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

    shares_series = quarterly["income"]["diluted_shares"].dropna()
    shares = float(shares_series.iloc[-1]) if not shares_series.empty else 1.0

    intrinsic = equity_value / shares if shares > 0 else 0.0
    upside = (intrinsic - effective_price) / effective_price if effective_price > 0 else None

    sensitivity = _compute_sensitivity(
        fcff_series=fcff_series,
        base_wacc=wacc,
        terminal_growth=terminal_growth,
        last_fcff=last_fcff,
        net_debt=net_debt,
        shares=shares,
    )

    annual_display = {k: v.iloc[:5].reset_index(drop=True) for k, v in annual.items()}
    historical = _build_historical_rows(annual_display)
    proforma = _build_proforma_rows(year_forecasts, fcff_series, wacc_detail.tax_rate)

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
        terminal_fcff=float(last_fcff),
        terminal_value=float(terminal_value),
        tv_pct_enterprise_value=float(tv_pct_ev),
        nwc_assumptions=nwc_assumptions,
        historical=historical,
        proforma=proforma,
        sensitivity=sensitivity,
    )
