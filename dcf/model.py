import numpy as np
import pandas as pd


def _coerce(val) -> float:
    if val is None:
        return 0.0
    f = float(val)
    return 0.0 if np.isnan(f) else f


DEFAULT_TERMINAL_GROWTH = 0.03  # 3%

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



def _build_fcff_series(
    year_forecasts: list,
    last_actual_revenue: float,
    last_actual_cogs: float,
    tax_rate: float,
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
        other_opex = yf.other_opex_pct
        ebit = rev * (1.0 - yf.cogs_pct - yf.sga_pct - rd - other_opex)
        nopat = ebit * (1 - tax_rate)
        da = rev * yf.da_pct
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

        # Prefer CF statement D&A since most companies report it there.
        # Normalize to absolute value — providers vary on sign convention.
        da_raw = _val(cf_row, "depreciation_amortization") or _val(row, "depreciation_amortization")
        da = abs(da_raw) if da_raw is not None else None

        op_income = _val(row, "operating_income")
        if op_income is None:
            gp = _val(row, "gross_profit")
            if gp is not None:
                sga = _val(row, "selling_general_admin") or 0.0
                rd = _val(row, "research_development") or 0.0
                op_income = gp - abs(sga) - abs(rd)
        ebitda = (op_income + da) if op_income is not None and da is not None else op_income

        tax_raw = _val(row, "income_tax_expense")
        income_tax = abs(tax_raw) if tax_raw is not None else None

        rows.append(
            HistoricalRow(
                period_label=label,
                period_end_date=date,
                revenue=_val(row, "revenue"),
                gross_profit=_val(row, "gross_profit"),
                operating_income=op_income,
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
                ebitda=ebitda,
                income_tax_expense=income_tax,
                pretax_income=_val(row, "pretax_income"),
            )
        )
    return rows


def _build_proforma_rows(
    year_forecasts: list, fcff_series: list, tax_rate: float, last_annual_year: int, shares: float | None = None
) -> list:
    from dcf.assumptions import HistoricalRow

    rows = []
    for yf, fc in zip(year_forecasts, fcff_series):
        rev = yf.revenue
        if yf.reports_cogs:
            cogs = rev * yf.cogs_pct
            gross_profit = rev - cogs
        else:
            cogs = None
            gross_profit = None
        rd = yf.rd_pct or 0.0
        interest = rev * yf.interest_pct
        other = rev * yf.other_pct
        pretax = fc.ebit - interest + other
        income_tax = pretax * tax_rate
        net_income = pretax * (1 - tax_rate)
        ebitda = fc.ebit + fc.da
        diluted_eps = net_income / shares if shares and shares > 0 else None

        rows.append(
            HistoricalRow(
                period_label=f"FY {last_annual_year + yf.year}",
                revenue=rev,
                gross_profit=gross_profit,
                operating_income=fc.ebit,
                net_income=net_income,
                depreciation_amortization=fc.da,
                capital_expenditures=fc.capex,
                total_assets=None,
                total_debt=None,
                cash_and_equivalents=None,
                diluted_eps=diluted_eps,
                cost_of_revenue=cogs,
                selling_general_admin=rev * yf.sga_pct,
                research_development=rev * rd if yf.rd_pct is not None else None,
                interest_expense=interest,
                ebitda=ebitda,
                income_tax_expense=income_tax,
                pretax_income=pretax,
            )
        )
    return rows


def _build_y1_quarter_rows(
    quarterly: dict,
    annual: dict,
    year_forecast_y1: object,
    tax_rate: float,
    shares: float | None,
    y1_quarter_revenues: dict | None,
) -> tuple:
    """Build 4 quarterly HistoricalRows for Y1, mixing actuals and seasonality-based estimates.

    Returns (rows, y1_total_revenue).
    """
    from dcf.assumptions import HistoricalRow

    inc_q = quarterly["income"].copy().sort_values("period_end_date")
    cf_q = quarterly["cashflow"].copy().sort_values("period_end_date") if not quarterly["cashflow"].empty else pd.DataFrame()
    bs_q = quarterly["balance"].copy().sort_values("period_end_date") if not quarterly["balance"].empty else pd.DataFrame()

    last_annual_inc = annual["income"].iloc[0]
    last_annual_date_raw = last_annual_inc.get("period_end_date")
    if last_annual_date_raw is None or pd.isna(last_annual_date_raw):
        return [], float(year_forecast_y1.revenue)

    last_annual_date = pd.Timestamp(last_annual_date_raw)
    y1_end_date = last_annual_date + pd.DateOffset(years=1)
    prior_start_date = last_annual_date - pd.DateOffset(years=1)

    # Fiscal year used consistently for all Y1 quarter labels
    _fy_raw = last_annual_inc.get("fiscal_year")
    y1_fiscal_year = (int(_fy_raw) + 1) if _fy_raw is not None and pd.notna(_fy_raw) else (last_annual_date.year + 1)

    # Y1 actual quarterly rows (period after last annual, within one year)
    inc_q_dates = pd.to_datetime(inc_q["period_end_date"])
    y1_mask = (inc_q_dates > last_annual_date) & (inc_q_dates <= y1_end_date)
    y1_actuals_inc = inc_q[y1_mask.values].sort_values("period_end_date").reset_index(drop=True)
    n_actuals = len(y1_actuals_inc)

    # Prior-year quarterly rows for seasonality
    prior_mask = (inc_q_dates > prior_start_date) & (inc_q_dates <= last_annual_date)
    prior_q_inc = inc_q[prior_mask.values].sort_values("period_end_date").reset_index(drop=True)
    prior_annual_rev = _val(last_annual_inc, "revenue") or 0.0

    def _is_ytd(rows: pd.DataFrame, annual_rev: float = 0) -> bool:
        """True if revenues are YTD-cumulative, False if standalone quarterly.

        Uses sum-vs-annual ratio when annual_rev is known (most reliable):
          standalone 3 qtrs ≈ 0.75 × annual; YTD 3 qtrs ≈ 1.5 × annual.
        Falls back to requiring >30% step-wise increase when annual is unavailable.
        """
        revs = [_val(rows.iloc[i], "revenue") or 0.0 for i in range(min(len(rows), 4))]
        if len(revs) < 2:
            return False
        if annual_rev > 0:
            return sum(revs) / annual_rev > 1.1
        return all(revs[i] >= revs[i - 1] * 1.3 for i in range(1, len(revs)))

    annual_model_rev = float(year_forecast_y1.revenue)

    # Use per-dataset YTD flags; pass annual_rev for reliable standalone vs YTD detection
    ytd_prior = _is_ytd(prior_q_inc, prior_annual_rev)
    ytd_y1 = _is_ytd(y1_actuals_inc, annual_model_rev) if n_actuals > 1 else False

    def _standalone_revs(rows: pd.DataFrame, annual_rev: float, is_ytd: bool) -> list:
        revs = [_val(rows.iloc[i], "revenue") or 0.0 for i in range(len(rows))]
        if is_ytd:
            standalone = []
            for i, r in enumerate(revs):
                standalone.append(r - (revs[i - 1] if i > 0 else 0.0))
            if len(standalone) == 3:
                standalone.append(max(0.0, annual_rev - sum(standalone)))
            while len(standalone) < 4:
                remaining = max(1, 4 - len(standalone))
                leftover = max(0.0, annual_rev - sum(standalone))
                standalone.append(leftover / remaining)
        else:
            standalone = list(revs)
            while len(standalone) < 4:
                remaining = max(1, 4 - len(standalone))
                leftover = max(0.0, annual_rev - sum(standalone))
                standalone.append(leftover / remaining)
        return standalone[:4]

    prior_standalone = _standalone_revs(prior_q_inc, prior_annual_rev, ytd_prior)
    total_prior = sum(r for r in prior_standalone if r > 0)
    seasonality = [r / total_prior for r in prior_standalone] if total_prior > 0 else [0.25] * 4

    # Base estimated quarterly revenues from seasonality applied to annual model forecast
    quarterly_revs = [annual_model_rev * s for s in seasonality]

    # Apply user quarterly revenue overrides (only for estimated quarters)
    if y1_quarter_revenues:
        for qi, rev in y1_quarter_revenues.items():
            idx = int(qi) - 1
            if n_actuals <= idx < 4:
                quarterly_revs[idx] = float(rev)

    # Replace estimates with actuals where reported
    actual_revs = _standalone_revs(y1_actuals_inc, annual_model_rev, ytd_y1) if n_actuals > 0 else []
    for i in range(n_actuals):
        if i < len(actual_revs):
            quarterly_revs[i] = actual_revs[i]

    y1_total_rev = sum(quarterly_revs)

    # Y1 actual CF and BS rows
    cf_q_y1 = pd.DataFrame()
    bs_q_y1 = pd.DataFrame()
    if not cf_q.empty:
        cf_dates = pd.to_datetime(cf_q["period_end_date"])
        cf_q_y1 = cf_q[(cf_dates > last_annual_date) & (cf_dates <= y1_end_date)].sort_values("period_end_date").reset_index(drop=True)
    if not bs_q.empty:
        bs_dates = pd.to_datetime(bs_q["period_end_date"])
        bs_q_y1 = bs_q[(bs_dates > last_annual_date) & (bs_dates <= y1_end_date)].sort_values("period_end_date").reset_index(drop=True)

    # Estimated quarter dates: prior-year same quarter date + 1 year
    prior_q_dates = []
    for i in range(len(prior_q_inc)):
        d = prior_q_inc.iloc[i].get("period_end_date")
        if d is not None and pd.notna(d):
            try:
                prior_q_dates.append(pd.Timestamp(d))
            except Exception:
                pass

    def _est_date(q_idx: int) -> str | None:
        if q_idx < len(prior_q_dates):
            try:
                d = prior_q_dates[q_idx]
                return d.replace(year=d.year + 1).strftime("%Y-%m-%d")
            except Exception:
                pass
        if ytd_prior and q_idx == 3:
            return y1_end_date.strftime("%Y-%m-%d")
        return None

    rows = []
    for q_idx in range(4):
        q_num = q_idx + 1
        is_actual = q_idx < n_actuals
        rev = quarterly_revs[q_idx]

        if is_actual:
            inc_row = y1_actuals_inc.iloc[q_idx]
            prev_inc = y1_actuals_inc.iloc[q_idx - 1] if q_idx > 0 else None
            date = str(inc_row.get("period_end_date", ""))[:10]

            def _sa(field, row=inc_row, prev=prev_inc):
                v = _val(row, field)
                if v is None:
                    return None
                if ytd_y1 and prev is not None:
                    p = _val(prev, field)
                    if p is not None:
                        v -= p
                return v

            gross_profit = _sa("gross_profit")
            if gross_profit is None:
                cogs_sa = _sa("cost_of_revenue")
                if cogs_sa is not None:
                    gross_profit = rev - cogs_sa

            op_income = _sa("operating_income")
            net_income = _sa("net_income")
            tax_raw = _sa("income_tax_expense")
            income_tax = abs(tax_raw) if tax_raw is not None else None
            pretax = _sa("pretax_income")

            cf_row = cf_q_y1.iloc[q_idx] if q_idx < len(cf_q_y1) else pd.Series(dtype=float)
            prev_cf = cf_q_y1.iloc[q_idx - 1] if (q_idx > 0 and q_idx - 1 < len(cf_q_y1)) else None
            da_cf = _val(cf_row, "depreciation_amortization")
            if da_cf is not None and ytd_y1 and prev_cf is not None:
                p = _val(prev_cf, "depreciation_amortization")
                if p is not None:
                    da_cf -= p
            da_raw = da_cf if da_cf is not None else _sa("depreciation_amortization")
            da = abs(da_raw) if da_raw is not None else None
            ebitda = (op_income + da) if op_income is not None and da is not None else op_income

            capex_raw = _val(cf_row, "capital_expenditures")
            if capex_raw is not None and ytd_y1 and prev_cf is not None:
                p = _val(prev_cf, "capital_expenditures")
                if p is not None:
                    capex_raw -= p
            capex = capex_raw

            bs_row = bs_q_y1.iloc[q_idx] if q_idx < len(bs_q_y1) else pd.Series(dtype=float)
            total_assets = _val(bs_row, "total_assets")
            total_debt = _sum_debt(bs_row) if not bs_row.empty else None
            cash = _val(bs_row, "cash_and_equivalents")

            rows.append(HistoricalRow(
                period_label=f"Q{q_num} FY{y1_fiscal_year}",
                period_end_date=date,
                is_actual=True,
                revenue=rev,
                gross_profit=gross_profit,
                operating_income=op_income,
                net_income=net_income,
                depreciation_amortization=da,
                capital_expenditures=capex,
                total_assets=total_assets,
                total_debt=total_debt,
                cash_and_equivalents=cash,
                diluted_eps=_sa("diluted_eps"),
                cost_of_revenue=_sa("cost_of_revenue"),
                selling_general_admin=_sa("selling_general_admin"),
                research_development=_sa("research_development"),
                interest_expense=_sa("interest_expense"),
                ebitda=ebitda,
                income_tax_expense=income_tax,
                pretax_income=pretax,
            ))
        else:
            if year_forecast_y1.reports_cogs:
                cogs = rev * year_forecast_y1.cogs_pct
                gross_profit = rev - cogs
            else:
                cogs = None
                gross_profit = None
            rd = year_forecast_y1.rd_pct or 0.0
            sga = rev * year_forecast_y1.sga_pct
            rd_amt = rev * rd
            other_opex = year_forecast_y1.other_opex_pct
            ebit = rev * (1.0 - year_forecast_y1.cogs_pct - year_forecast_y1.sga_pct - rd - other_opex)
            interest = rev * year_forecast_y1.interest_pct
            other = rev * year_forecast_y1.other_pct
            pretax = ebit - interest + other
            income_tax_est = pretax * tax_rate
            net_income = pretax * (1 - tax_rate)
            da = rev * year_forecast_y1.da_pct
            ebitda = ebit + da
            capex = rev * year_forecast_y1.capex_pct_revenue
            diluted_eps = net_income / shares if shares and shares > 0 else None

            est_date = _est_date(q_idx)
            rows.append(HistoricalRow(
                period_label=f"Q{q_num} FY{y1_fiscal_year}",
                period_end_date=est_date,
                is_actual=False,
                revenue=rev,
                gross_profit=gross_profit,
                operating_income=ebit,
                net_income=net_income,
                depreciation_amortization=da,
                capital_expenditures=capex,
                total_assets=None,
                total_debt=None,
                cash_and_equivalents=None,
                diluted_eps=diluted_eps,
                cost_of_revenue=cogs,
                selling_general_admin=sga,
                research_development=rd_amt if year_forecast_y1.rd_pct is not None else None,
                interest_expense=interest,
                ebitda=ebitda,
                income_tax_expense=income_tax_est,
                pretax_income=pretax,
            ))

    return rows, y1_total_rev


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


def _median_revenue_growth(income_df: pd.DataFrame) -> float:
    """Median YoY revenue growth from historical annual data. Clamped [0%, 15%]."""
    rev = income_df["revenue"].dropna()
    if len(rev) < 2:
        return 0.03
    # income_df is newest→oldest; rates[i] = growth from period i+1 to period i
    rates = rev.values[:-1] / rev.values[1:] - 1
    return float(np.clip(np.nanmedian(rates), 0.0, 0.15))


def _median_ebit_margin(income_df: pd.DataFrame) -> float:
    """Median EBIT margin from all available annual data. Clamped [1%, 50%]."""
    rev = income_df["revenue"].replace(0, np.nan)
    ebit = income_df["operating_income"] if "operating_income" in income_df.columns else pd.Series(dtype=float)
    margins = (ebit / rev).dropna()
    margins = margins[np.isfinite(margins)]
    if margins.empty:
        return 0.10
    return float(np.clip(np.median(margins), 0.01, 0.50))


def run_dcf(
    ticker: str,
    db,
    overrides: "UserOverrides | None" = None,
) -> "DcfResult":
    from dcf.data import load_quarterly_financials, load_annual_financials
    quarterly = load_quarterly_financials(db, ticker)
    annual = load_annual_financials(db, ticker)
    return _run_dcf_core(ticker, annual, quarterly, overrides, estimates_conn=db.conn)


def run_dcf_av(
    ticker: str,
    overrides: "UserOverrides | None" = None,
) -> "DcfResult":
    import dataclasses
    from dcf.av_data import load_av_annual_financials, load_av_quarterly_financials
    quarterly = load_av_quarterly_financials(ticker)
    annual = load_av_annual_financials(ticker)
    if overrides is None or overrides.terminal_growth_rate is None:
        median_g = _median_revenue_growth(annual["income"])
        if overrides is None:
            from dcf.assumptions import UserOverrides
            overrides = UserOverrides(terminal_growth_rate=median_g)
        else:
            overrides = dataclasses.replace(overrides, terminal_growth_rate=median_g)

    if overrides.default_ebit_margin_pct is None:
        overrides = dataclasses.replace(
            overrides,
            default_ebit_margin_pct=_median_ebit_margin(annual["income"]),
        )
    return _run_dcf_core(ticker, annual, quarterly, overrides, estimates_conn=None)


def _run_dcf_core(
    ticker: str,
    annual: dict,
    quarterly: dict,
    overrides: "UserOverrides | None" = None,
    estimates_conn=None,
) -> "DcfResult":
    from dcf.assumptions import DcfResult
    from dcf.data import load_current_price, load_risk_free_rate
    from dcf.wacc import compute_wacc, compute_effective_tax_rate, DEFAULT_MRP, DEFAULT_RF
    from dcf.forecaster import forecast_assumptions, merge_overrides, compute_nwc_days, extend_growth_years

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
        tax_rate_override=overrides.tax_rate_override if (overrides and overrides.tax_rate_override is not None) else annual_tax_rate,
        annual_income_df=annual["income"],
    )

    warnings: list[str] = []

    _DCF_CRITICAL_FIELDS = {
        "income": ["revenue", "operating_income", "pretax_income", "income_tax_expense", "diluted_shares"],
        "balance": ["long_term_debt", "cash_and_equivalents"],
        "cashflow": ["depreciation_amortization", "capital_expenditures"],
    }
    for _stmt_key, _fields in _DCF_CRITICAL_FIELDS.items():
        _df = annual[_stmt_key] if _stmt_key != "balance" else quarterly["balance"]
        for _field in _fields:
            if _field in _df.columns and _df[_field].notna().any():
                continue
            warnings.append(
                f"Critical field '{_field}' ({_stmt_key}) is NULL for all periods — "
                f"DCF output may be unreliable. Re-import {ticker} to resolve."
            )

    if wacc_detail.market_cap == 0:
        warnings.append(
            "Market cap is zero — diluted shares not found in quarterly or annual income statements. "
            "Capital structure weights are unreliable; consider overriding cost of debt."
        )
    elif wacc_detail.debt_weight > 0.8:
        warnings.append(
            f"Debt weight is {wacc_detail.debt_weight:.0%} — verify that price and share count are correct."
        )
    if wacc_detail.wacc < 0.05:
        warnings.append(
            f"WACC of {wacc_detail.wacc * 100:.1f}% is below 5% — check capital structure inputs."
        )

    year_forecasts = forecast_assumptions(quarterly, annual)

    # Apply analyst estimates before user overrides (user overrides win)
    from dcf.estimates import fetch_and_cache, apply_to_forecasts, to_dataclass as _to_dc
    _inc_a = annual["income"]
    _last_a = _inc_a.iloc[0] if not _inc_a.empty else pd.Series(dtype=float)
    _last_rev_est = float(_inc_a["revenue"].dropna().iloc[0]) if not _inc_a.empty and _inc_a["revenue"].notna().any() else 0.0
    _last_year_est = int(_last_a.get("fiscal_year", 0)) if pd.notna(_last_a.get("fiscal_year", None)) else 0
    _last_date_est = str(_last_a.get("period_end_date", ""))[:10]
    raw_estimates = fetch_and_cache(ticker, estimates_conn) if estimates_conn is not None else []
    year_forecasts, _analyst_q_revs, _analyst_years = apply_to_forecasts(
        raw_estimates, year_forecasts, _last_rev_est, _last_year_est, _last_date_est, overrides
    )
    if _analyst_q_revs:
        _user_set_y1_growth = (
            overrides is not None
            and 1 in overrides.years
            and overrides.years[1].revenue_growth is not None
        )
        if not _user_set_y1_growth:
            _existing_q = (overrides.y1_quarter_revenues or {}) if overrides else {}
            _merged_q = {**_analyst_q_revs, **_existing_q}  # user per-quarter values win
            if overrides:
                overrides.y1_quarter_revenues = _merged_q
            else:
                from dcf.assumptions import UserOverrides as _UO
                overrides = _UO(y1_quarter_revenues=_merged_q)

    year_forecasts = merge_overrides(year_forecasts, overrides)

    terminal_growth = DEFAULT_TERMINAL_GROWTH
    if overrides and overrides.terminal_growth_rate is not None:
        terminal_growth = overrides.terminal_growth_rate

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

    # Early shares estimate (for quarterly row EPS; full computation happens later)
    _sq = quarterly["income"]["diluted_shares"].dropna()
    _early_shares = float(_sq.iloc[-1]) if not _sq.empty else None

    # Last annual fiscal year for period labels
    _last_annual_inc = annual["income"].iloc[0]
    last_annual_year = int(_last_annual_inc.get("fiscal_year", 0)) if pd.notna(_last_annual_inc.get("fiscal_year")) else 0

    # Build Y1 quarterly rows (actuals + seasonality estimates) and get revised Y1 revenue
    y1_q_overrides = overrides.y1_quarter_revenues if overrides else None
    y1_quarters, y1_revised_rev = _build_y1_quarter_rows(
        quarterly=quarterly,
        annual=annual,
        year_forecast_y1=year_forecasts[0],
        tax_rate=wacc_detail.tax_rate,
        shares=_early_shares,
        y1_quarter_revenues=y1_q_overrides,
    )

    # Update Y1 revenue to reflect actuals + estimates, and cascade to Y2-Y5.
    # Y1 is only overridden when it has no analyst annual estimate; when an analyst
    # estimate anchors Y1, preserve it and skip the cascade entirely.
    # For years with analyst estimates in the cascade, preserve the absolute analyst
    # revenue and only recalculate the implied growth rate; for other years, cascade normally.
    if y1_quarters and y1_revised_rev != year_forecasts[0].revenue and 1 not in _analyst_years:
        year_forecasts[0].revenue = y1_revised_rev
        year_forecasts[0].revenue_growth = (y1_revised_rev - last_rev) / last_rev if last_rev != 0 else 0.0
        prev = y1_revised_rev
        for yf in year_forecasts[1:]:
            if yf.year in _analyst_years:
                yf.revenue_growth = (yf.revenue - prev) / prev if prev else yf.revenue_growth
                prev = yf.revenue
            else:
                yf.revenue = prev * (1 + yf.revenue_growth)
                prev = yf.revenue

    # Y3-Y10: carry forward Y2 growth (applied after all Y1/Y2 are settled)
    year_forecasts = extend_growth_years(year_forecasts, overrides)

    # AV DCF: apply EBIT margin control (overrides other_opex_pct so that
    # EBIT = revenue × ebit_margin exactly). Per-year user value wins over default.
    _default_ebit_m = overrides.default_ebit_margin_pct if overrides else None
    if _default_ebit_m is not None or (
        overrides and any(yo.ebit_margin_pct is not None for yo in overrides.years.values())
    ):
        for yf in year_forecasts:
            yo = overrides.years.get(yf.year) if overrides else None
            ebit_m = yo.ebit_margin_pct if (yo and yo.ebit_margin_pct is not None) else _default_ebit_m
            if ebit_m is not None:
                yf.other_opex_pct = max(
                    0.0,
                    1.0 - yf.cogs_pct - yf.sga_pct - (yf.rd_pct or 0.0) - ebit_m,
                )

    fcff_series = _build_fcff_series(
        year_forecasts=year_forecasts,
        last_actual_revenue=last_rev,
        last_actual_cogs=last_cogs,
        tax_rate=wacc_detail.tax_rate,
        nwc_assumptions=nwc_assumptions,
        wacc=wacc_detail.wacc,
    )

    last_fcff = fcff_series[-1].fcff
    wacc = wacc_detail.wacc
    if wacc <= terminal_growth:
        clamped_tg = wacc - 0.01
        warnings.append(
            f"Terminal growth clamped from {terminal_growth * 100:.1f}% to {clamped_tg * 100:.1f}% "
            f"because WACC ({wacc * 100:.1f}%) must exceed terminal growth."
        )
        terminal_growth = clamped_tg

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
    if not shares_series.empty:
        shares = float(shares_series.iloc[-1])
    elif wacc_detail.market_cap > 0 and effective_price > 0:
        # Consistent with compute_wacc: derive from the already-computed market_cap.
        shares = wacc_detail.market_cap / effective_price
    else:
        shares = 1.0

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
    proforma = _build_proforma_rows(year_forecasts, fcff_series, wacc_detail.tax_rate, last_annual_year, shares)

    _today = str(pd.Timestamp.today().date())
    analyst_estimates = _to_dc([e for e in raw_estimates if e.get("date", "") >= _today])

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
        warnings=warnings,
        y1_quarters=y1_quarters,
        analyst_estimates=analyst_estimates,
    )
