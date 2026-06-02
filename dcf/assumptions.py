from dataclasses import dataclass, field
from typing import List


@dataclass
class EarningsEstimate:
    date: str
    horizon: str  # "fiscal year" | "fiscal quarter"
    eps_estimate_avg: float | None
    eps_estimate_high: float | None
    eps_estimate_low: float | None
    eps_analyst_count: int | None
    revenue_estimate_avg: float | None
    revenue_estimate_high: float | None
    revenue_estimate_low: float | None
    revenue_analyst_count: int | None


@dataclass
class YearOverride:
    revenue: float | None = None          # absolute dollars; takes priority over revenue_growth
    revenue_growth: float | None = None
    cogs_pct: float | None = None
    sga_pct: float | None = None
    rd_pct: float | None = None
    interest_pct: float | None = None
    other_pct: float | None = None
    other_opex_pct: float | None = None
    capex_pct_revenue: float | None = None
    da_pct: float | None = None
    ebit_margin_pct: float | None = None  # AV DCF: overrides cogs/sga/rd via other_opex residual


@dataclass
class UserOverrides:
    years: dict[int, YearOverride] = field(default_factory=dict)
    terminal_growth_rate: float | None = None
    risk_free_rate: float | None = None
    market_risk_premium: float | None = None
    beta: float | None = None
    dso: float | None = None
    dpo: float | None = None
    dio: float | None = None
    cost_of_debt_override: float | None = None
    tax_rate_override: float | None = None
    y1_quarter_revenues: dict[int, float] | None = None  # keys 1-4
    default_ebit_margin_pct: float | None = None  # AV DCF: median historical margin, applied as flat default


@dataclass
class YearForecast:
    year: int
    revenue: float
    revenue_growth: float
    cogs_pct: float
    sga_pct: float
    rd_pct: float | None      # None when company doesn't report R&D
    interest_pct: float
    other_pct: float
    capex_pct_revenue: float
    da_pct: float = 0.03
    other_opex_pct: float = 0.0  # residual operating costs not in COGS/SGA/R&D
    reports_cogs: bool = True    # False for service cos. that don't break out cost of revenue


@dataclass
class NwcAssumptions:
    dso: float   # days sales outstanding
    dpo: float   # days payable outstanding
    dio: float   # days inventory outstanding


@dataclass
class WaccDetail:
    beta_raw: float
    beta_relevered: float
    risk_free_rate: float
    market_risk_premium: float
    cost_of_equity: float
    cost_of_debt: float
    tax_rate: float
    debt_weight: float
    equity_weight: float
    wacc: float
    total_debt: float
    market_cap: float
    beta_2yr: float | None = None


@dataclass
class FcffYear:
    year: int
    revenue: float
    ebit: float
    nopat: float
    da: float
    capex: float
    delta_nwc: float
    fcff: float
    discount_factor: float
    pv_fcff: float


@dataclass
class SensitivityCell:
    wacc: float
    terminal_growth: float
    intrinsic_value: float


@dataclass
class HistoricalRow:
    period_label: str
    revenue: float | None
    gross_profit: float | None
    operating_income: float | None
    net_income: float | None
    depreciation_amortization: float | None
    capital_expenditures: float | None
    total_assets: float | None
    total_debt: float | None
    cash_and_equivalents: float | None
    diluted_eps: float | None
    # Granular P&L for ratio display
    cost_of_revenue: float | None = None
    selling_general_admin: float | None = None
    research_development: float | None = None
    interest_expense: float | None = None
    period_end_date: str | None = None
    ebitda: float | None = None
    income_tax_expense: float | None = None
    pretax_income: float | None = None
    is_actual: bool = False
    # Balance sheet items for working-capital day metrics
    accounts_receivable: float | None = None
    accounts_payable: float | None = None
    inventory: float | None = None


@dataclass
class DcfResult:
    ticker: str
    intrinsic_value_per_share: float
    current_price: float | None
    upside_pct: float | None

    wacc_detail: WaccDetail
    terminal_growth_rate: float
    net_debt: float
    diluted_shares: float
    enterprise_value: float
    equity_value: float

    year_forecasts: list[YearForecast]
    fcff_series: list[FcffYear]
    pv_terminal_value: float
    terminal_fcff: float
    terminal_value: float
    tv_pct_enterprise_value: float

    nwc_assumptions: NwcAssumptions

    historical: list[HistoricalRow]
    proforma: list[HistoricalRow]

    sensitivity: list[SensitivityCell]

    warnings: List[str] = field(default_factory=list)
    y1_quarters: list = field(default_factory=list)
    analyst_estimates: list = field(default_factory=list)
