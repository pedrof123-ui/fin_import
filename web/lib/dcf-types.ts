export interface EarningsEstimate {
  date: string;
  horizon: string; // "fiscal year" | "fiscal quarter"
  eps_estimate_avg: number | null;
  eps_estimate_high: number | null;
  eps_estimate_low: number | null;
  eps_analyst_count: number | null;
  revenue_estimate_avg: number | null;
  revenue_estimate_high: number | null;
  revenue_estimate_low: number | null;
  revenue_analyst_count: number | null;
}

export interface WaccDetail {
  beta_raw: number;
  beta_relevered: number;
  beta_2yr: number | null;
  risk_free_rate: number;
  market_risk_premium: number;
  cost_of_equity: number;
  cost_of_debt: number;
  tax_rate: number;
  debt_weight: number;
  equity_weight: number;
  wacc: number;
  total_debt: number;
  market_cap: number;
}

export interface YearForecast {
  year: number;
  revenue: number;
  revenue_growth: number;
  cogs_pct: number;
  sga_pct: number;
  rd_pct: number | null;
  interest_pct: number;
  other_pct: number;
  capex_pct_revenue: number;
  da_pct: number;
}

export interface FcffYear {
  year: number;
  revenue: number;
  ebit: number;
  nopat: number;
  da: number;
  capex: number;
  delta_nwc: number;
  fcff: number;
  discount_factor: number;
  pv_fcff: number;
}

export interface SensitivityCell {
  wacc: number;
  terminal_growth: number;
  intrinsic_value: number | null;
}

export interface NwcAssumptions {
  dso: number;
  dpo: number;
  dio: number;
}

export interface HistoricalRow {
  period_label: string;
  revenue: number | null;
  gross_profit: number | null;
  operating_income: number | null;
  net_income: number | null;
  depreciation_amortization: number | null;
  capital_expenditures: number | null;
  total_assets: number | null;
  total_debt: number | null;
  cash_and_equivalents: number | null;
  diluted_eps: number | null;
  cost_of_revenue: number | null;
  selling_general_admin: number | null;
  research_development: number | null;
  interest_expense: number | null;
  period_end_date: string | null;
  ebitda: number | null;
  income_tax_expense: number | null;
  pretax_income: number | null;
  is_actual: boolean;
}

export interface DcfData {
  ticker: string;
  intrinsic_value_per_share: number;
  current_price: number | null;
  upside_pct: number | null;
  wacc_detail: WaccDetail;
  terminal_growth_rate: number;
  net_debt: number;
  diluted_shares: number;
  enterprise_value: number;
  equity_value: number;
  year_forecasts: YearForecast[];
  fcff_series: FcffYear[];
  pv_terminal_value: number;
  terminal_fcff: number;
  terminal_value: number;
  tv_pct_enterprise_value: number;
  nwc_assumptions: NwcAssumptions;
  historical: HistoricalRow[];
  proforma: HistoricalRow[];
  y1_quarters: HistoricalRow[];
  sensitivity: SensitivityCell[];

  warnings: string[];
  analyst_estimates: EarningsEstimate[];
}

// Editable per-year override state.
// rev_growth, gross_margin, capex_pct are percentages (e.g. "15.0%").
// sga, rd, da are absolute dollar amounts in billions (e.g. "12.34B").
export interface YearRowState {
  rev_growth:   string;  // revenue growth % (e.g. "15.0%")
  gross_margin: string;  // gross margin % — sets cogs_pct = 1 - gross_margin (e.g. "60.0%")
  sga: string;           // SG&A in $B (standard mode)
  rd: string;            // R&D in $B (standard mode)
  da: string;            // D&A in $B
  capex_pct: string;     // capex as % of revenue (e.g. "3.5%")
  ebit_margin: string;   // EBIT margin % — AV DCF mode (e.g. "12.5%")
}

export interface YearOverrideBody {
  revenue?: number;        // absolute dollars
  revenue_growth?: number; // kept for back-compat but revenue takes priority
  cogs_pct?: number;
  sga_pct?: number;
  rd_pct?: number;
  interest_pct?: number;
  other_pct?: number;
  capex_pct_revenue?: number;
  da_pct?: number;
  ebit_margin_pct?: number; // AV DCF: direct EBIT margin control
}

export interface RunRequest {
  years: Record<string, YearOverrideBody>;
  terminal_growth_rate?: number;
  risk_free_rate?: number;
  market_risk_premium?: number;
  beta?: number;
  dso?: number;
  dpo?: number;
  dio?: number;
  cost_of_debt?: number;
  tax_rate?: number;
  y1_quarter_revenues?: Record<string, number>;  // keys "1"-"4", values in dollars
}

export interface MonthlyDataPoint {
  date: string;
  price: number | null;
  pe_ratio: number | null;
  pe_rolling_5yr_median: number | null;
  pfcf_ratio: number | null;
  pfcf_rolling_5yr_median: number | null;
  ev_ebitda: number | null;
  ev_ebitda_rolling_5yr_median: number | null;
  ps_ratio: number | null;
  ps_rolling_5yr_median: number | null;
  roa: number | null;
  roe: number | null;
  roic: number | null;
  ttm_gross_margin: number | null;
  ttm_operating_margin: number | null;
  ttm_fcf_margin: number | null;
}

export interface FundamentalsEstimate {
  date: string;
  horizon: string;
  eps_avg: number | null;
  eps_high: number | null;
  eps_low: number | null;
  eps_count: number | null;
  rev_avg: number | null;
  rev_high: number | null;
  rev_low: number | null;
  rev_count: number | null;
}

export interface FundamentalsData {
  ticker: string;
  company_name: string | null;
  sector: string | null;
  industry: string | null;
  market_cap_b: number | null;
  current_price: number | null;
  analyst_target_price: number | null;
  analyst_strong_buy: number | null;
  analyst_buy: number | null;
  analyst_hold: number | null;
  analyst_sell: number | null;
  analyst_strong_sell: number | null;
  overview_updated_at: string | null;

  // Valuation multiples
  current_pe: number | null;
  forward_pe: number | null;
  pe_lt_median: number | null;
  pe_p25: number | null;
  pe_p75: number | null;
  pe_rolling_5yr_median: number | null;

  current_pfcf: number | null;
  forward_pfcf: number | null;
  pfcf_lt_median: number | null;
  pfcf_p25: number | null;
  pfcf_p75: number | null;
  pfcf_rolling_5yr_median: number | null;

  current_evebitda: number | null;
  forward_evebitda: number | null;
  evebitda_lt_median: number | null;
  evebitda_p25: number | null;
  evebitda_p75: number | null;
  evebitda_rolling_5yr_median: number | null;

  current_ps: number | null;
  forward_ps: number | null;
  ps_lt_median: number | null;
  ps_p25: number | null;
  ps_p75: number | null;
  ps_rolling_5yr_median: number | null;

  current_pbv: number | null;
  pbv_lt_median: number | null;
  pbv_rolling_5yr_median: number | null;

  // Returns
  current_roa: number | null;
  roa_lt_median: number | null;
  roa_rolling_5yr_median: number | null;

  current_roe: number | null;
  roe_lt_median: number | null;
  roe_rolling_5yr_median: number | null;

  current_roic: number | null;
  roic_lt_median: number | null;
  roic_rolling_5yr_median: number | null;

  // Growth rates
  rev_growth_1yr: number | null;
  rev_cagr_3yr: number | null;
  rev_cagr_5yr: number | null;
  rev_ntm_growth_est: number | null;
  earn_growth_1yr: number | null;
  earn_cagr_3yr: number | null;
  earn_cagr_5yr: number | null;
  earn_ntm_growth_est: number | null;

  // Margins
  current_gross_margin: number | null;
  gross_margin_5y_median: number | null;
  current_operating_margin: number | null;
  operating_margin_5y_median: number | null;
  operating_margin_change_3y: number | null;
  current_fcf_margin: number | null;
  fcf_margin_5y_median: number | null;
  fcf_margin_change_3y: number | null;

  // Goal / implied prices
  goal_pe: number | null;
  goal_pcf: number | null;
  goal_peg: number | null;
  goal_bv: number | null;
  goal_2x: number | null;
  goal_low: number | null;
  goal_high: number | null;

  // EPS & dividends
  current_ttm_eps: number | null;
  forward_12m_eps: number | null;
  dividend_yield: number | null;

  // Leverage
  debt_to_ebitda: number | null;
  interest_coverage: number | null;

  // Time series & estimates
  monthly_series: MonthlyDataPoint[];
  analyst_estimates: FundamentalsEstimate[];
  stats_updated_at: string | null;
}
