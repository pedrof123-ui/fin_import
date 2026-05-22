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

// Absolute dollar amounts in billions (e.g. "450.23B"). Empty string when not applicable (e.g. no R&D).
export interface YearRowState {
  revenue: string;
  gross_profit: string;
  sga: string;
  rd: string;
  da: string;
  capex: string;
}

export interface YearOverrideBody {
  revenue_growth?: number;
  cogs_pct?: number;
  sga_pct?: number;
  rd_pct?: number;
  interest_pct?: number;
  other_pct?: number;
  capex_pct_revenue?: number;
  da_pct?: number;
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
