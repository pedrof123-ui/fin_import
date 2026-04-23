from dataclasses import dataclass, field


@dataclass
class YearOverride:
    revenue_growth: float | None = None    # e.g. 0.10 = 10%
    gross_margin: float | None = None      # e.g. 0.40 = 40%
    operating_margin: float | None = None  # e.g. 0.20 = 20%
    capex_pct_revenue: float | None = None # e.g. 0.05 = 5%


@dataclass
class UserOverrides:
    years: dict[int, YearOverride] = field(default_factory=dict)  # keys 1-5
    terminal_growth_rate: float | None = None
    risk_free_rate: float | None = None
    market_risk_premium: float | None = None
    beta: float | None = None


@dataclass
class YearForecast:
    year: int
    revenue: float
    revenue_growth: float
    gross_margin: float
    operating_margin: float
    capex_pct_revenue: float


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
    period_label: str      # e.g. "FY 2024"
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

    historical: list[HistoricalRow]
    proforma: list[HistoricalRow]

    sensitivity: list[SensitivityCell]
