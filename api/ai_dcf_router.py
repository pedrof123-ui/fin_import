"""
FastAPI router + orchestration for the Agentic AI DCF Valuator (features/ai_dcf/SPEC.md).

Phase 2 (this file, initial cut) adds the assumption schemas, guardrails, the bridge from
LLM-authored assumptions to the deterministic DCF engine (dcf.run_dcf_av), the AiDcfResult
container, and the markdown renderers — all with zero LLM involvement, so the deterministic
core is fully testable before any prompt work begins. Later phases extend this same file with
the evidence-agent fan-out, the DCF Architect call, the orchestrator, and the cache/status/
endpoint scaffolding.

Design discipline carried over from api/research_router.py and api/industry_research_router.py:
the LLM authors assumptions and prose; every number in a rendered table comes from
dcf.run_dcf_av's output or a DB query, never from LLM arithmetic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import duckdb
from agents import Agent, Runner, OpenAIChatCompletionsModel
from fastapi import APIRouter
from openai import AsyncOpenAI
from pydantic import BaseModel, field_validator, model_validator

from api.industry_research_router import _sanitize_prose
from api.research_router import _coerce_optional_float, _DEFAULT_MODEL, _load_prompt, _md_table, _STYLE_GUIDE
from dcf.assumptions import DcfResult, UserOverrides, YearOverride
from dcf.model import run_dcf_av

log = logging.getLogger(__name__)
router = APIRouter()

_DATA_DIR = Path(__file__).parent.parent / "data"
_AI_DCF_DB = _DATA_DIR / "ai_dcf_cache.duckdb"
_AI_DCF_CACHE_TTL_HOURS = 24
_HIST_FUND_DB = _DATA_DIR / "historic_fundamentals.duckdb"

# ---------------------------------------------------------------------------
# Guardrail constants (SPEC 6.5)
# ---------------------------------------------------------------------------

TG_MIN, TG_MAX = 0.0, 0.04
REV_GROWTH_MIN, REV_GROWTH_MAX = -0.50, 1.00
EBIT_MARGIN_MIN, EBIT_MARGIN_MAX = -0.30, 0.60
EBIT_MARGIN_HIST_MAX_BUFFER = 0.10   # 10pp above historical max triggers a warning
CAPEX_MIN, CAPEX_MAX = 0.0, 0.35
COGS_MIN, COGS_MAX = 0.0, 1.0
COGS_DROP_WARN_PP = 0.15             # cogs_pct >15pp below historical median -> warn


# ---------------------------------------------------------------------------
# 2.1 — Pydantic schemas
# ---------------------------------------------------------------------------

def _coerce_float_list(v):
    """Element-wise `_coerce_optional_float` for list[float] fields — survives an LLM emitting
    '"n/a"'-style placeholder strings or percent-formatted strings inside a list."""
    if not isinstance(v, list):
        return v
    return [_coerce_optional_float(x) for x in v]


def _require_len_5(v, field_name: str):
    if not isinstance(v, list) or len(v) != 5:
        raise ValueError(f"{field_name} must have exactly 5 values (one per forecast year), got {v!r}")
    return v


def _sanitize_value(v):
    """Recursively applies research_router/industry_research_router's known fix for a live LLM
    quirk (gemini-3.5-flash occasionally emits a literal backslash-n instead of a real newline
    inside a structured-output string field) — confirmed live during the Phase 3 evidence-agent
    check (2026-07-30) on TXN's fundamentals brief. Leaves non-str/list values untouched, so it's
    safe to run over an already-validated nested BaseModel field (e.g. AiDcfAssumptions.bear)."""
    if isinstance(v, str):
        return _sanitize_prose(v)
    if isinstance(v, list):
        return [_sanitize_value(x) for x in v]
    return v


def _sanitize_all_fields(instance: BaseModel) -> BaseModel:
    for name in instance.__dict__:
        setattr(instance, name, _sanitize_value(getattr(instance, name)))
    return instance


class ScenarioAssumptions(BaseModel):
    revenue_growth: list[float]        # len 5, decimal (0.12 = 12%)
    cogs_pct: list[float]               # len 5, decimal % of revenue — see SPEC 6.2b
    ebit_margin_pct: list[float]        # len 5, decimal margin (not delta)
    capex_pct_revenue: list[float]      # len 5, decimal % of revenue
    terminal_growth_rate: float
    rationale: str

    @field_validator("revenue_growth", "cogs_pct", "ebit_margin_pct", "capex_pct_revenue", mode="before")
    @classmethod
    def _coerce_lists(cls, v):
        return _coerce_float_list(v)

    @field_validator("revenue_growth")
    @classmethod
    def _len_revenue_growth(cls, v):
        return _require_len_5(v, "revenue_growth")

    @field_validator("cogs_pct")
    @classmethod
    def _len_cogs_pct(cls, v):
        return _require_len_5(v, "cogs_pct")

    @field_validator("ebit_margin_pct")
    @classmethod
    def _len_ebit_margin_pct(cls, v):
        return _require_len_5(v, "ebit_margin_pct")

    @field_validator("capex_pct_revenue")
    @classmethod
    def _len_capex_pct_revenue(cls, v):
        return _require_len_5(v, "capex_pct_revenue")

    @field_validator("terminal_growth_rate", mode="before")
    @classmethod
    def _coerce_tg(cls, v):
        return _coerce_optional_float(v)

    @model_validator(mode="after")
    def _sanitize(self):
        return _sanitize_all_fields(self)


class AiDcfAssumptions(BaseModel):
    bear: ScenarioAssumptions
    base: ScenarioAssumptions
    bull: ScenarioAssumptions
    beta_override: Optional[float] = None
    tax_rate_override: Optional[float] = None
    cost_of_debt_override: Optional[float] = None
    wacc_rationale: str
    key_debates: list[str]

    @field_validator("beta_override", "tax_rate_override", "cost_of_debt_override", mode="before")
    @classmethod
    def _coerce_optional_overrides(cls, v):
        return _coerce_optional_float(v)

    @model_validator(mode="after")
    def _sanitize(self):
        return _sanitize_all_fields(self)


class FundamentalsBrief(BaseModel):
    growth_history: str
    margin_history: str
    capital_intensity: str
    working_capital: str
    cyclicality_assessment: str
    sustainable_ranges: str

    @model_validator(mode="after")
    def _sanitize(self):
        return _sanitize_all_fields(self)


class IndustryBrief(BaseModel):
    industry_growth_outlook: str
    pricing_margin_direction: str
    capex_cycle: str
    competitive_position: str
    terminal_context: str
    used_industry_report: bool
    industry_report_age_days: Optional[int] = None

    @field_validator("industry_report_age_days", mode="before")
    @classmethod
    def _coerce_age(cls, v):
        coerced = _coerce_optional_float(v)
        return int(coerced) if coerced is not None else None

    @model_validator(mode="after")
    def _sanitize(self):
        return _sanitize_all_fields(self)


class GuidanceBrief(BaseModel):
    explicit_guidance: str
    strategy_shifts: str
    demand_inflections: str
    guidance_credibility: str
    consensus_view: str

    @model_validator(mode="after")
    def _sanitize(self):
        return _sanitize_all_fields(self)


# ---------------------------------------------------------------------------
# 2.2 — Guardrails (validate_assumptions never mutates `a`; the one hard rule —
# terminal_growth_rate out of range — is enforced downstream in to_overrides, which drops the
# override rather than mutating a required Pydantic float field in place)
# ---------------------------------------------------------------------------

def _check_scenario_ranges(label: str, s: ScenarioAssumptions, bounds: dict) -> list[str]:
    warnings: list[str] = []

    for i, g in enumerate(s.revenue_growth, start=1):
        if not (REV_GROWTH_MIN <= g <= REV_GROWTH_MAX):
            warnings.append(
                f"{label} y{i}: revenue_growth {g:.1%} outside [{REV_GROWTH_MIN:.0%}, {REV_GROWTH_MAX:.0%}]"
            )

    ebit_margin_max = bounds.get("ebit_margin_max")
    for i, m in enumerate(s.ebit_margin_pct, start=1):
        if not (EBIT_MARGIN_MIN <= m <= EBIT_MARGIN_MAX):
            warnings.append(
                f"{label} y{i}: ebit_margin_pct {m:.1%} outside [{EBIT_MARGIN_MIN:.0%}, {EBIT_MARGIN_MAX:.0%}]"
            )
        elif ebit_margin_max is not None and m > ebit_margin_max + EBIT_MARGIN_HIST_MAX_BUFFER:
            warnings.append(
                f"{label} y{i}: ebit_margin_pct {m:.1%} exceeds historical max {ebit_margin_max:.1%} "
                f"by more than {EBIT_MARGIN_HIST_MAX_BUFFER:.0%}"
            )

    for i, c in enumerate(s.capex_pct_revenue, start=1):
        if not (CAPEX_MIN <= c <= CAPEX_MAX):
            warnings.append(
                f"{label} y{i}: capex_pct_revenue {c:.1%} outside [{CAPEX_MIN:.0%}, {CAPEX_MAX:.0%}]"
            )

    if bounds.get("reports_cogs"):
        hist_cogs = bounds.get("cogs_pct_median")
        for i, (cg, m) in enumerate(zip(s.cogs_pct, s.ebit_margin_pct), start=1):
            if not (COGS_MIN <= cg <= COGS_MAX):
                warnings.append(f"{label} y{i}: cogs_pct {cg:.1%} outside [{COGS_MIN:.0%}, {COGS_MAX:.0%}]")
            if hist_cogs is not None and cg < hist_cogs - COGS_DROP_WARN_PP:
                warnings.append(
                    f"{label} y{i}: cogs_pct {cg:.1%} is >{COGS_DROP_WARN_PP:.0%} below the historical "
                    f"median {hist_cogs:.1%} — verify the scenario rationale cites a specific "
                    "gross-margin driver"
                )
            if m > 1 - cg + 1e-6:
                warnings.append(
                    f"{label} y{i}: ebit_margin_pct {m:.1%} exceeds (1 - cogs_pct) = {(1 - cg):.1%} — "
                    "the engine will floor SG&A/R&D rather than hit this target (SPEC 6.2b)"
                )

    if not (TG_MIN <= s.terminal_growth_rate <= TG_MAX):
        warnings.append(
            f"{label}: terminal_growth_rate {s.terminal_growth_rate:.2%} outside "
            f"[{TG_MIN:.0%}, {TG_MAX:.0%}] — will be dropped, engine default used instead"
        )

    return warnings


def validate_assumptions(a: AiDcfAssumptions, bounds: dict) -> tuple[AiDcfAssumptions, list[str]]:
    """Guardrails per SPEC 6.5. `bounds` is api.ai_dcf_data.get_historical_margin_bounds(ticker)'s
    output: {"reports_cogs": bool, "cogs_pct_median": float|None, "ebit_margin_max": float|None}."""
    warnings: list[str] = []
    for label, s in [("bear", a.bear), ("base", a.base), ("bull", a.bull)]:
        warnings.extend(_check_scenario_ranges(label, s, bounds))
    return a, warnings


def check_scenario_ordering(engine_results: dict[str, Optional[DcfResult]]) -> list[str]:
    """Post-engine sanity: bear <= base <= bull on intrinsic value/share (SPEC 6.5)."""
    warnings: list[str] = []
    bear, base, bull = engine_results.get("bear"), engine_results.get("base"), engine_results.get("bull")
    if bear is not None and base is not None and bear.intrinsic_value_per_share > base.intrinsic_value_per_share:
        warnings.append(
            f"bear intrinsic value (${bear.intrinsic_value_per_share:.2f}) exceeds base "
            f"(${base.intrinsic_value_per_share:.2f}) — scenario ordering violated"
        )
    if base is not None and bull is not None and base.intrinsic_value_per_share > bull.intrinsic_value_per_share:
        warnings.append(
            f"base intrinsic value (${base.intrinsic_value_per_share:.2f}) exceeds bull "
            f"(${bull.intrinsic_value_per_share:.2f}) — scenario ordering violated"
        )
    return warnings


# ---------------------------------------------------------------------------
# 2.3 — Mapping assumptions -> UserOverrides (SPEC 6.2)
# ---------------------------------------------------------------------------

def _valid_terminal_growth(tg: float) -> Optional[float]:
    return tg if TG_MIN <= tg <= TG_MAX else None


def to_overrides(s: ScenarioAssumptions, a: AiDcfAssumptions, reports_cogs: bool) -> UserOverrides:
    """Only passes cogs_pct into YearOverride when reports_cogs is True — for no-COGS targets
    it's structurally meaningless (the forecaster pins cogs_pct at 0 regardless, Phase 0.3)."""
    years = {
        i: YearOverride(
            revenue_growth=s.revenue_growth[i - 1],
            cogs_pct=s.cogs_pct[i - 1] if reports_cogs else None,
            ebit_margin_pct=s.ebit_margin_pct[i - 1],
            capex_pct_revenue=s.capex_pct_revenue[i - 1],
        )
        for i in range(1, 6)
    }
    return UserOverrides(
        years=years,
        terminal_growth_rate=_valid_terminal_growth(s.terminal_growth_rate),
        beta=a.beta_override,
        tax_rate_override=a.tax_rate_override,
        cost_of_debt_override=a.cost_of_debt_override,
    )


# ---------------------------------------------------------------------------
# 2.4 — Engine bridge
# ---------------------------------------------------------------------------

def run_ai_dcf_engine(
    ticker: str, assumptions: AiDcfAssumptions, reports_cogs: bool,
) -> dict[str, Optional[DcfResult]]:
    """Three run_dcf_av calls (bear/base/bull). A per-scenario engine exception degrades that
    scenario to None (same pattern as api.valuation_data.compute_dcf_scenarios); a None base
    scenario raises — the AI DCF is unavailable for this ticker/run."""
    ticker = ticker.upper()
    conn = duckdb.connect(str(_HIST_FUND_DB), read_only=True)
    results: dict[str, Optional[DcfResult]] = {}
    try:
        for label, scenario in [("bear", assumptions.bear), ("base", assumptions.base), ("bull", assumptions.bull)]:
            try:
                overrides = to_overrides(scenario, assumptions, reports_cogs)
                results[label] = run_dcf_av(ticker, overrides, estimates_conn=conn)
            except Exception:
                results[label] = None
    finally:
        conn.close()

    if results.get("base") is None:
        raise RuntimeError(f"AI DCF unavailable for {ticker}: base scenario engine run failed")
    return results


# ---------------------------------------------------------------------------
# 2.5 — AiDcfResult (JSON-round-trip-safe engine extract + result container)
# ---------------------------------------------------------------------------

def _extract_engine_result(r: DcfResult) -> dict:
    """Flat, JSON-serializable subset of a DcfResult — everything the renderers need,
    nothing more."""
    return {
        "intrinsic_value_per_share": r.intrinsic_value_per_share,
        "wacc": r.wacc_detail.wacc,
        "beta_raw": r.wacc_detail.beta_raw,
        "beta_relevered": r.wacc_detail.beta_relevered,
        "cost_of_equity": r.wacc_detail.cost_of_equity,
        "cost_of_debt": r.wacc_detail.cost_of_debt,
        "tax_rate": r.wacc_detail.tax_rate,
        "terminal_growth_rate": r.terminal_growth_rate,
        "tv_pct_enterprise_value": r.tv_pct_enterprise_value,
        "year_forecasts": [
            {
                "year": yf.year,
                "revenue": fc.revenue,
                "revenue_growth": yf.revenue_growth,
                "ebit_margin": (fc.ebit / fc.revenue) if fc.revenue else None,
                "capex_pct_revenue": yf.capex_pct_revenue,
                "fcff": fc.fcff,
            }
            for yf, fc in zip(r.year_forecasts[:5], r.fcff_series[:5])
        ],
        "warnings": list(r.warnings),
    }


@dataclass
class AiDcfResult:
    ticker: str
    model: str
    generated_at: str  # ISO timestamp
    assumptions: AiDcfAssumptions
    fundamentals_brief: FundamentalsBrief
    industry_brief: IndustryBrief
    guidance_brief: GuidanceBrief
    engine: dict[str, Optional[dict]]      # {"bear": extract|None, "base": extract|None, "bull": extract|None}
    qc_warnings: list[str] = field(default_factory=list)
    inputs_available: dict = field(default_factory=dict)

    @classmethod
    def build(
        cls, ticker: str, model: str, assumptions: AiDcfAssumptions,
        fundamentals_brief: FundamentalsBrief, industry_brief: IndustryBrief, guidance_brief: GuidanceBrief,
        engine_results: dict[str, Optional[DcfResult]], qc_warnings: list[str], inputs_available: dict,
    ) -> "AiDcfResult":
        return cls(
            ticker=ticker.upper(),
            model=model,
            generated_at=datetime.now().isoformat(),
            assumptions=assumptions,
            fundamentals_brief=fundamentals_brief,
            industry_brief=industry_brief,
            guidance_brief=guidance_brief,
            engine={k: (_extract_engine_result(v) if v is not None else None) for k, v in engine_results.items()},
            qc_warnings=qc_warnings,
            inputs_available=inputs_available,
        )

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "model": self.model,
            "generated_at": self.generated_at,
            "assumptions": self.assumptions.model_dump(),
            "fundamentals_brief": self.fundamentals_brief.model_dump(),
            "industry_brief": self.industry_brief.model_dump(),
            "guidance_brief": self.guidance_brief.model_dump(),
            "engine": self.engine,
            "qc_warnings": self.qc_warnings,
            "inputs_available": self.inputs_available,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, d: dict) -> "AiDcfResult":
        return cls(
            ticker=d["ticker"],
            model=d["model"],
            generated_at=d["generated_at"],
            assumptions=AiDcfAssumptions.model_validate(d["assumptions"]),
            fundamentals_brief=FundamentalsBrief.model_validate(d["fundamentals_brief"]),
            industry_brief=IndustryBrief.model_validate(d["industry_brief"]),
            guidance_brief=GuidanceBrief.model_validate(d["guidance_brief"]),
            engine=d["engine"],
            qc_warnings=d.get("qc_warnings", []),
            inputs_available=d.get("inputs_available", {}),
        )

    @classmethod
    def from_json(cls, s: str) -> "AiDcfResult":
        return cls.from_dict(json.loads(s))


# ---------------------------------------------------------------------------
# 2.6 — Renderers (deterministic; every number comes from AiDcfResult.engine or DcfResult)
# ---------------------------------------------------------------------------

def _fv(x, fmt: str = ".2f") -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "n/a"
    return f"{x:{fmt}}"


def render_ai_dcf_markdown(result: AiDcfResult) -> str:
    """Standalone AI DCF report (SPEC 7.1) — also the cached markdown artifact."""
    lines = [
        f"# AI DCF Valuation — {result.ticker}",
        "",
        f"**Model:** {result.model}  |  **Prepared:** {result.generated_at[:10]}",
        "",
    ]

    ia = result.inputs_available
    age = ia.get("industry_report_age_days")
    lines += [
        "**Inputs used:** "
        f"industry report {'(' + str(age) + 'd old)' if age is not None else '(unavailable)'}, "
        f"MD&A filings found: {ia.get('mda_filings_found', 0)}, "
        f"competitor transcripts found: {ia.get('competitor_transcripts_found', 0)}",
        "",
        "---",
        "",
        "## Valuation Summary",
        "",
    ]
    val_rows = []
    for label, key in [("Bear", "bear"), ("Base", "base"), ("Bull", "bull")]:
        e = result.engine.get(key)
        if e is None:
            val_rows.append([label, "n/a", "n/a", "n/a"])
        else:
            val_rows.append([
                label, f"${_fv(e['intrinsic_value_per_share'])}",
                f"{_fv(e['wacc'] * 100, '.2f')}%", f"{_fv(e['terminal_growth_rate'] * 100, '.2f')}%",
            ])
    lines += _md_table(["Scenario", "Intrinsic Value/Share", "WACC", "Terminal Growth"], val_rows)
    lines += ["", "---", "", "## Assumptions", ""]

    assum_rows = []
    for label, scenario in [("Bear", result.assumptions.bear), ("Base", result.assumptions.base),
                             ("Bull", result.assumptions.bull)]:
        for i in range(5):
            assum_rows.append([
                f"{label} Y{i + 1}",
                f"{scenario.revenue_growth[i] * 100:.1f}%",
                f"{scenario.cogs_pct[i] * 100:.1f}%",
                f"{scenario.ebit_margin_pct[i] * 100:.1f}%",
                f"{scenario.capex_pct_revenue[i] * 100:.1f}%",
            ])
    lines += _md_table(["Scenario/Year", "Revenue Growth", "COGS %", "EBIT Margin", "Capex %"], assum_rows)
    lines += ["", "---", "", "## Key Debates", ""]
    for d in result.assumptions.key_debates:
        lines.append(f"- {d}")

    lines += ["", "---", "", "## Scenario Rationales", ""]
    for label, scenario in [("Bear", result.assumptions.bear), ("Base", result.assumptions.base),
                             ("Bull", result.assumptions.bull)]:
        lines += [f"**{label}:** {scenario.rationale}", ""]
    lines += [f"**WACC rationale:** {result.assumptions.wacc_rationale}", "", "---", ""]

    lines += ["## Evidence Briefs", "", "### Fundamentals Historian", ""]
    fb = result.fundamentals_brief
    lines += [
        f"**Growth history:** {fb.growth_history}", "",
        f"**Margin history:** {fb.margin_history}", "",
        f"**Capital intensity:** {fb.capital_intensity}", "",
        f"**Working capital:** {fb.working_capital}", "",
        f"**Cyclicality:** {fb.cyclicality_assessment}", "",
        f"**Sustainable ranges:** {fb.sustainable_ranges}", "",
    ]
    lines += ["### Industry & Competitors", ""]
    ib = result.industry_brief
    lines += [
        f"**Industry growth outlook:** {ib.industry_growth_outlook}", "",
        f"**Pricing/margin direction:** {ib.pricing_margin_direction}", "",
        f"**Capex cycle:** {ib.capex_cycle}", "",
        f"**Competitive position:** {ib.competitive_position}", "",
        f"**Terminal-growth context:** {ib.terminal_context}", "",
    ]
    lines += ["### Guidance & MD&A", ""]
    gb = result.guidance_brief
    lines += [
        f"**Explicit guidance:** {gb.explicit_guidance}", "",
        f"**Strategy shifts:** {gb.strategy_shifts}", "",
        f"**Demand inflections:** {gb.demand_inflections}", "",
        f"**Guidance credibility:** {gb.guidance_credibility}", "",
        f"**Consensus view:** {gb.consensus_view}", "",
    ]

    if result.qc_warnings:
        lines += ["---", "", "## QC Warnings", ""]
        for w in result.qc_warnings:
            lines.append(f"- {w}")

    lines.append("")
    lines.append(f"*AI DCF prepared by {result.model} on {result.generated_at[:10]}. "
                 "For informational purposes only. Not investment advice.*")
    return "\n".join(lines)


def _mechanical_row_stats(r: Optional[DcfResult]) -> dict:
    if r is None:
        return {"rev_cagr": None, "avg_margin": None, "capex": None, "tg": None, "wacc": None}
    rev_cagr = (
        (r.year_forecasts[4].revenue / r.year_forecasts[0].revenue) ** (1 / 4) - 1
        if len(r.year_forecasts) >= 5 and r.year_forecasts[0].revenue > 0 else None
    )
    n = min(5, len(r.year_forecasts))
    avg_margin = sum(
        1 - yf.cogs_pct - yf.sga_pct - (yf.rd_pct or 0) - yf.other_opex_pct
        for yf in r.year_forecasts[:5]
    ) / n if n else None
    avg_capex = sum(yf.capex_pct_revenue for yf in r.year_forecasts[:5]) / n if n else None
    return {
        "rev_cagr": rev_cagr, "avg_margin": avg_margin, "capex": avg_capex,
        "tg": r.terminal_growth_rate, "wacc": r.wacc_detail.wacc,
    }


def _ai_row_stats(extract: Optional[dict]) -> dict:
    if extract is None:
        return {"rev_cagr": None, "avg_margin": None, "capex": None, "tg": None, "wacc": None}
    yfs = extract["year_forecasts"]
    rev_cagr = (
        (yfs[4]["revenue"] / yfs[0]["revenue"]) ** (1 / 4) - 1
        if len(yfs) >= 5 and yfs[0]["revenue"] > 0 else None
    )
    margins = [y["ebit_margin"] for y in yfs if y["ebit_margin"] is not None]
    avg_margin = sum(margins) / len(margins) if margins else None
    avg_capex = sum(y["capex_pct_revenue"] for y in yfs) / len(yfs) if yfs else None
    return {
        "rev_cagr": rev_cagr, "avg_margin": avg_margin, "capex": avg_capex,
        "tg": extract["terminal_growth_rate"], "wacc": extract["wacc"],
    }


def _pct_cell(v) -> str:
    return f"{v * 100:.1f}%" if v is not None else "n/a"


def render_ai_dcf_comparison_table(
    ai_engine: dict[str, Optional[dict]], mechanical_scenarios: dict[str, Optional[DcfResult]],
) -> str:
    """SPEC 7.2 — "AI vs. Mechanical DCF Assumptions" table. Both columns come from engine
    output (AI's own run_dcf_av results and the existing mechanical compute_dcf_scenarios
    output) — never LLM prose."""
    rows = []
    for label, key in [("Bear", "bear"), ("Base", "base"), ("Bull", "bull")]:
        ai_stats = _ai_row_stats(ai_engine.get(key))
        mech_stats = _mechanical_row_stats(mechanical_scenarios.get(key))
        rows.append([
            label,
            _pct_cell(ai_stats["rev_cagr"]), _pct_cell(mech_stats["rev_cagr"]),
            _pct_cell(ai_stats["avg_margin"]), _pct_cell(mech_stats["avg_margin"]),
            _pct_cell(ai_stats["capex"]), _pct_cell(mech_stats["capex"]),
            _pct_cell(ai_stats["tg"]), _pct_cell(mech_stats["tg"]),
            _pct_cell(ai_stats["wacc"]), _pct_cell(mech_stats["wacc"]),
        ])
    lines = ["#### AI vs. Mechanical DCF Assumptions", ""]
    lines += _md_table(
        ["Scenario", "AI Rev CAGR", "Mech Rev CAGR", "AI EBIT Margin", "Mech EBIT Margin",
         "AI Capex%", "Mech Capex%", "AI TG", "Mech TG", "AI WACC", "Mech WACC"],
        rows,
    )
    return "\n".join(lines)


def render_ai_dcf_triangulation_row(ai_engine: dict[str, Optional[dict]]) -> list[str]:
    """Row for research_router._model_summary_table: ["DCF (AI-authored)", bear, base, bull]."""
    def _v(key):
        e = ai_engine.get(key)
        return f"${_fv(e['intrinsic_value_per_share'])}" if e else "n/a"
    return ["DCF (AI-authored)", _v("bear"), _v("base"), _v("bull")]


# ---------------------------------------------------------------------------
# 3 — Evidence agent fan-out (Stage 1). Timeout/fallback pattern copied from
# research_router._run_subagent (that one is a closure over _run_research_agent's locals; this
# is a standalone async function so it's independently testable/mockable).
# ---------------------------------------------------------------------------

_LLM_TIMEOUT = 400  # matches research_router._LLM_TIMEOUT


def _fill_prompt(prompt_name: str, ticker: str, model: str, context: str) -> str:
    return (
        _load_prompt(prompt_name)
        .replace("{style_guide}", _STYLE_GUIDE)
        .replace("{ticker}", ticker.upper())
        .replace("{date}", datetime.now().strftime("%Y-%m-%d"))
        .replace("{model}", model)
        .replace("{context}", context)
    )


def _fallback_fundamentals_brief(ticker: str) -> FundamentalsBrief:
    return FundamentalsBrief(
        growth_history=f"[ERROR] Fundamentals Historian sub-agent failed for {ticker}",
        margin_history="[ERROR] Unavailable",
        capital_intensity="[ERROR] Unavailable",
        working_capital="[ERROR] Unavailable",
        cyclicality_assessment="[ERROR] Unavailable",
        sustainable_ranges="[ERROR] Unavailable",
    )


def _fallback_industry_brief(ticker: str) -> IndustryBrief:
    return IndustryBrief(
        industry_growth_outlook=f"[ERROR] Industry & Competitors sub-agent failed for {ticker}",
        pricing_margin_direction="[ERROR] Unavailable",
        capex_cycle="[ERROR] Unavailable",
        competitive_position="[ERROR] Unavailable",
        terminal_context="[ERROR] Unavailable",
        used_industry_report=False,
        industry_report_age_days=None,
    )


def _fallback_guidance_brief(ticker: str) -> GuidanceBrief:
    return GuidanceBrief(
        explicit_guidance=f"[ERROR] Guidance & MD&A sub-agent failed for {ticker}",
        strategy_shifts="[ERROR] Unavailable",
        demand_inflections="[ERROR] Unavailable",
        guidance_credibility="[ERROR] Unavailable",
        consensus_view="[ERROR] Unavailable",
    )


async def _run_evidence_agent(name: str, prompt_name: str, ticker: str, model_label: str,
                               context: str, output_type, fallback, llm):
    instructions = _fill_prompt(prompt_name, ticker, model_label, context)
    agent = Agent(name=name, instructions=instructions, model=llm, output_type=output_type)
    try:
        result = await asyncio.wait_for(
            Runner.run(agent, f"Produce your brief for {ticker.upper()}."), timeout=_LLM_TIMEOUT,
        )
        return result.final_output
    except asyncio.TimeoutError:
        log.error("[%s] ai_dcf: %s evidence agent timed out after %ds", ticker, name, _LLM_TIMEOUT)
        return fallback
    except Exception as e:
        log.error("[%s] ai_dcf: %s evidence agent failed: %s", ticker, name, e)
        return fallback


async def run_evidence_agents(
    ticker: str, model: str, fundamentals_context: str, industry_context: str, guidance_context: str,
) -> tuple[FundamentalsBrief, IndustryBrief, GuidanceBrief]:
    """Stage 1 — the three evidence sub-agents in parallel. A single agent failing/timing out
    never kills the run: it degrades to its own [ERROR] fallback brief while the other two
    real outputs proceed (mirrors research_router's specialist fan-out)."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
    llm = OpenAIChatCompletionsModel(model=model, openai_client=client)

    fundamentals, industry, guidance = await asyncio.gather(
        _run_evidence_agent(
            "fundamentals_historian", "ai_dcf_fundamentals.md", ticker, model,
            fundamentals_context, FundamentalsBrief, _fallback_fundamentals_brief(ticker), llm,
        ),
        _run_evidence_agent(
            "industry_competitors_analyst", "ai_dcf_industry.md", ticker, model,
            industry_context, IndustryBrief, _fallback_industry_brief(ticker), llm,
        ),
        _run_evidence_agent(
            "guidance_mda_analyst", "ai_dcf_guidance.md", ticker, model,
            guidance_context, GuidanceBrief, _fallback_guidance_brief(ticker), llm,
        ),
    )
    return fundamentals, industry, guidance


# ---------------------------------------------------------------------------
# 4.1/4.3 — DCF Architect (Stage 2). No fallback here by design: an Architect failure means the
# AI DCF is unavailable for this run (SPEC 6.8's failure-isolation contract) — the caller
# (run_ai_dcf) lets the exception propagate so the research pipeline can degrade cleanly.
# ---------------------------------------------------------------------------

def _format_brief_for_architect(label: str, brief: BaseModel) -> str:
    lines = [f"--- {label} ---", ""]
    for field_name, value in brief.model_dump().items():
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        lines.append(f"{field_name}: {value}")
    return "\n".join(lines)


def build_architect_context(
    fundamentals_brief: FundamentalsBrief, industry_brief: IndustryBrief, guidance_brief: GuidanceBrief,
    engine_context: str,
) -> str:
    return (
        f"{_format_brief_for_architect('FUNDAMENTALS HISTORIAN BRIEF', fundamentals_brief)}\n\n"
        f"{_format_brief_for_architect('INDUSTRY & COMPETITORS BRIEF', industry_brief)}\n\n"
        f"{_format_brief_for_architect('GUIDANCE & MD&A BRIEF', guidance_brief)}\n\n"
        f"--- ENGINE CONTEXT ---\n\n{engine_context}"
    )


async def run_architect(ticker: str, model: str, context: str) -> AiDcfAssumptions:
    """Stage 2 — a single structured-output call authoring bear/base/bull assumptions. Raises
    on any failure (timeout, provider error, schema-grammar limit) — see 4.3's split-call
    fallback seam, added only if the compiled-grammar error is actually observed live."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
    llm = OpenAIChatCompletionsModel(model=model, openai_client=client)
    instructions = _fill_prompt("ai_dcf_architect.md", ticker, model, context)
    agent = Agent(name="dcf_architect", instructions=instructions, model=llm, output_type=AiDcfAssumptions)
    result = await asyncio.wait_for(
        Runner.run(agent, f"Author bear/base/bull DCF assumptions for {ticker.upper()}."),
        timeout=_LLM_TIMEOUT,
    )
    return result.final_output


# ---------------------------------------------------------------------------
# 4.2 — Orchestrator: gather (Phase 1) -> evidence fan-out (Phase 3) -> Architect (4.1) ->
# guardrails (2.2) -> engine runs (2.4) -> AiDcfResult (2.5).
# ---------------------------------------------------------------------------

_DATA_TIMEOUT = 30
_EARNINGS_TIMEOUT = 30
_TAVILY_TIMEOUT = 20
_EMPTY_BOUNDS = {"reports_cogs": False, "cogs_pct_median": None, "ebit_margin_max": None}


async def _const(value):
    return value


async def run_ai_dcf(ticker: str, model: str, status_cb=None) -> AiDcfResult:
    """Full AI DCF pipeline for one ticker/model. Raises on Architect failure or base-scenario
    engine failure (AI DCF unavailable) — callers (standalone endpoint, research pipeline)
    decide how to degrade; this function never partially-succeeds silently."""
    from api.ai_dcf_data import (
        build_fundamentals_context, build_guidance_context, build_industry_context,
        get_competitor_transcripts, get_engine_context, get_fundamentals_history,
        get_historical_margin_bounds, get_industry_name, get_industry_report, get_mda_history,
    )
    from api.industry_data import get_industry_aggregates, get_industry_web_search
    from api.research_router import (
        get_beat_miss_summary, get_earnings_trend_summary, get_estimates_summary, get_peer_comparison,
    )

    ticker = ticker.upper()
    loop = asyncio.get_event_loop()

    def _status(phase: str, message: str) -> None:
        if status_cb:
            status_cb(phase, message)

    _status("gathering_data", f"Gathering fundamentals, MD&A, industry & competitor data for {ticker}...")

    async def _run(fn, *args, timeout=_DATA_TIMEOUT, default=None):
        try:
            return await asyncio.wait_for(loop.run_in_executor(None, lambda: fn(*args)), timeout=timeout)
        except asyncio.TimeoutError:
            return default if default is not None else f"[ERROR] {fn.__name__} timed out after {timeout}s"
        except Exception as e:
            return default if default is not None else f"[ERROR] {fn.__name__} failed: {e}"

    industry_name = await _run(get_industry_name, ticker, default="")

    (fundamentals_history, mda_history, industry_report, competitor_transcripts,
     engine_context, bounds, target_transcripts, estimates, peer_table, beat_miss,
     industry_aggregates, tavily_search) = await asyncio.gather(
        _run(get_fundamentals_history, ticker),
        _run(get_mda_history, ticker),
        _run(get_industry_report, ticker, default=None),
        _run(get_competitor_transcripts, ticker),
        _run(get_engine_context, ticker),
        _run(get_historical_margin_bounds, ticker, default=dict(_EMPTY_BOUNDS)),
        _run(get_earnings_trend_summary, ticker, timeout=_EARNINGS_TIMEOUT),
        _run(get_estimates_summary, ticker),
        _run(get_peer_comparison, ticker),
        _run(get_beat_miss_summary, ticker, timeout=_EARNINGS_TIMEOUT),
        _run(get_industry_aggregates, industry_name) if industry_name
            else _const("[INFO] No industry classification on file — cannot compute industry aggregates"),
        _run(get_industry_web_search, industry_name, timeout=_TAVILY_TIMEOUT) if industry_name
            else _const("[INFO] No industry classification on file — cannot run industry web search"),
    )

    fund_ctx = build_fundamentals_context(fundamentals_history)
    industry_ctx = build_industry_context(
        peer_table, industry_aggregates, tavily_search, industry_report, competitor_transcripts,
    )
    guidance_ctx = build_guidance_context(mda_history, target_transcripts, beat_miss, estimates)

    _status("running_evidence", "Running evidence specialists (fundamentals, industry & competitors, guidance & MD&A)...")
    fundamentals_brief, industry_brief, guidance_brief = await run_evidence_agents(
        ticker, model, fund_ctx, industry_ctx, guidance_ctx,
    )

    _status("running_architect", "DCF Architect authoring bear/base/bull assumptions...")
    architect_context = build_architect_context(fundamentals_brief, industry_brief, guidance_brief, engine_context)
    assumptions = await run_architect(ticker, model, architect_context)

    _status("computing_dcf", "Running the deterministic DCF engine for bear/base/bull...")
    reports_cogs = bool(bounds.get("reports_cogs", False))
    assumptions, qc_warnings = validate_assumptions(assumptions, bounds)
    engine_results = run_ai_dcf_engine(ticker, assumptions, reports_cogs)
    qc_warnings = qc_warnings + check_scenario_ordering(engine_results)

    inputs_available = {
        "industry_report_age_days": industry_report[1] if isinstance(industry_report, tuple) else None,
        # Approximate filing/transcript counts from the "--- [" block markers get_mda_history/
        # get_competitor_transcripts emit per item — good enough for a report-header display,
        # not used for any correctness-critical logic.
        "mda_filings_found": mda_history.count("--- ["),
        "competitor_transcripts_found": competitor_transcripts.count("--- ["),
    }

    return AiDcfResult.build(
        ticker=ticker, model=model, assumptions=assumptions,
        fundamentals_brief=fundamentals_brief, industry_brief=industry_brief, guidance_brief=guidance_brief,
        engine_results=engine_results, qc_warnings=qc_warnings, inputs_available=inputs_available,
    )


# ---------------------------------------------------------------------------
# 5.1 — DuckDB cache (24h TTL, keyed by ticker + model). Same trio shape as
# research_router._init_cache/_cache_get/_cache_put, extended with a result_json column so the
# structured AiDcfResult survives a cache round-trip, not just its rendered markdown.
# ---------------------------------------------------------------------------

def _init_ai_dcf_cache() -> None:
    _AI_DCF_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(_AI_DCF_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_dcf_cache (
            ticker          VARCHAR,
            model           VARCHAR,
            result_json     VARCHAR,
            report_markdown VARCHAR,
            generated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ticker, model)
        )
    """)
    conn.close()


def _ai_dcf_cache_get(ticker: str, model: str) -> Optional[tuple[str, str]]:
    """Returns (result_json, report_markdown) for a fresh cache hit, else None."""
    if not _AI_DCF_DB.exists():
        return None
    conn = duckdb.connect(str(_AI_DCF_DB), read_only=True)
    row = conn.execute(
        "SELECT result_json, report_markdown, generated_at FROM ai_dcf_cache WHERE ticker = ? AND model = ?",
        [ticker.upper(), model],
    ).fetchone()
    conn.close()
    if not row:
        return None
    result_json, report_markdown, generated_at = row
    if isinstance(generated_at, str):
        generated_at = datetime.fromisoformat(generated_at)
    if datetime.now() - generated_at > timedelta(hours=_AI_DCF_CACHE_TTL_HOURS):
        return None
    return result_json, report_markdown


def _ai_dcf_cache_put(ticker: str, model: str, result_json: str, report_markdown: str) -> None:
    _init_ai_dcf_cache()
    conn = duckdb.connect(str(_AI_DCF_DB))
    conn.execute("""
        INSERT INTO ai_dcf_cache (ticker, model, result_json, report_markdown, generated_at)
        VALUES (?, ?, ?, ?, now())
        ON CONFLICT (ticker, model) DO UPDATE SET
            result_json     = excluded.result_json,
            report_markdown = excluded.report_markdown,
            generated_at    = excluded.generated_at
    """, [ticker.upper(), model, result_json, report_markdown])
    conn.close()


# ---------------------------------------------------------------------------
# 5.2 — Background task registry + live status (mirrors research_router's
# _background_tasks/_task_status/_set_status/_get_or_start shape exactly), plus
# get_or_run_ai_dcf: the one piece the report-cache pattern doesn't already have — an
# in-process, cache-aware entry point that joins an in-flight run instead of double-starting.
# ---------------------------------------------------------------------------

_background_tasks: dict[tuple[str, str], asyncio.Task] = {}

# phase is one of: gathering_data, running_evidence, running_architect, computing_dcf,
# done, error, cancelled (SPEC 6.9).
_task_status: dict[tuple[str, str], dict] = {}

_GENERATING_MD = (
    "## Generating AI DCF Valuation for {ticker}...\n\n"
    "Gathering fundamentals, MD&A, industry & competitor data, running the evidence team "
    "and DCF Architect, then computing the DCF.\n"
    "This takes approximately 60-130 seconds.\n"
)


def _set_ai_dcf_status(key: tuple[str, str], phase: str, message: str, error: Optional[str] = None) -> None:
    _task_status[key] = {"phase": phase, "message": message, "error": error}


async def _background_generate_ai_dcf(ticker: str, model: str) -> Optional[AiDcfResult]:
    """Runs the full pipeline, writes the cache, sets live status — and returns the result (or
    None on failure) so get_or_run_ai_dcf can await this same task directly instead of starting
    a second run."""
    key = (ticker, model)
    log.info("[%s] ai_dcf: background task started (model=%s)", ticker, model)
    try:
        result = await run_ai_dcf(
            ticker, model, status_cb=lambda phase, msg: _set_ai_dcf_status(key, phase, msg),
        )
        markdown = render_ai_dcf_markdown(result)
        _ai_dcf_cache_put(ticker, model, result.to_json(), markdown)
        _set_ai_dcf_status(key, "done", "AI DCF ready.")
        log.info("[%s] ai_dcf: result cached (model=%s)", ticker, model)
        return result
    except Exception as e:
        log.error("[%s] ai_dcf: background task failed (model=%s): %s", ticker, model, e)
        _set_ai_dcf_status(key, "error", f"AI DCF generation failed: {e}", error=str(e))
        return None
    finally:
        _background_tasks.pop(key, None)


def _get_or_start_ai_dcf(ticker: str, model: str, retry: bool = False) -> str:
    """Standalone-endpoint entry point: returns cached markdown immediately, or kicks off (if
    not already running) a background generation and returns a "generating" placeholder.
    Mirrors research_router._get_or_start's retry-guard semantics exactly."""
    ticker = ticker.upper()
    key = (ticker, model)
    cached = _ai_dcf_cache_get(ticker, model)
    if cached is not None:
        _task_status.pop(key, None)
        return cached[1]

    if retry:
        _task_status.pop(key, None)

    status = _task_status.get(key)
    if status and status.get("phase") in ("error", "cancelled") and not retry:
        return _GENERATING_MD.format(ticker=ticker)

    if key not in _background_tasks or _background_tasks[key].done():
        _background_tasks[key] = asyncio.create_task(_background_generate_ai_dcf(ticker, model))
    return _GENERATING_MD.format(ticker=ticker)


async def get_or_run_ai_dcf(ticker: str, model: str) -> Optional[AiDcfResult]:
    """In-process entry point for the research pipeline (Phase 6): returns a fresh cached
    result if one exists, joins an already-running task (started by this same call, a
    concurrent caller, or the standalone endpoint) instead of double-starting a run, or starts
    and awaits a new one. Returns None on any failure — callers degrade gracefully rather than
    propagating an exception into the research report pipeline (SPEC 6.8)."""
    ticker = ticker.upper()
    key = (ticker, model)

    cached = _ai_dcf_cache_get(ticker, model)
    if cached is not None:
        try:
            return AiDcfResult.from_json(cached[0])
        except Exception as e:
            log.warning("[%s] ai_dcf: cached result_json failed to deserialize, re-running: %s", ticker, e)

    existing = _background_tasks.get(key)
    if existing is not None and not existing.done():
        return await existing

    task = asyncio.create_task(_background_generate_ai_dcf(ticker, model))
    _background_tasks[key] = task
    return await task


# ---------------------------------------------------------------------------
# 5.3 — Endpoints (mirror the single-name researcher's shapes)
# ---------------------------------------------------------------------------

@router.get("/research/ai-dcf")
async def ai_dcf_report(ticker: str, model: str = _DEFAULT_MODEL, retry: bool = False, format: str = "markdown"):
    ticker = ticker.strip().upper()
    model = model.strip() or _DEFAULT_MODEL
    if format == "json":
        cached = _ai_dcf_cache_get(ticker, model)
        if cached is None:
            _get_or_start_ai_dcf(ticker, model, retry=retry)
            return {"status": "generating"}
        return json.loads(cached[0])
    return _get_or_start_ai_dcf(ticker, model, retry=retry)


@router.get("/research/ai-dcf/status")
async def ai_dcf_status(ticker: str, model: str = _DEFAULT_MODEL):
    ticker = ticker.strip().upper()
    model = model.strip() or _DEFAULT_MODEL
    status = _task_status.get((ticker, model))
    if status is not None:
        return status
    cached = _ai_dcf_cache_get(ticker, model) is not None
    return {"phase": "done" if cached else "idle", "message": "", "error": None}


@router.post("/research/ai-dcf/cancel")
async def ai_dcf_cancel(ticker: str, model: str = _DEFAULT_MODEL):
    ticker = ticker.strip().upper()
    model = model.strip() or _DEFAULT_MODEL
    key = (ticker, model)
    task = _background_tasks.get(key)
    if task and not task.done():
        task.cancel()
        _set_ai_dcf_status(key, "cancelled", "Cancelled by user.")
        log.info("[%s] ai_dcf: generation cancelled by user (model=%s)", ticker, model)
        return {"status": "cancelled"}
    return {"status": "not_running"}


# ---------------------------------------------------------------------------
# 6.2 — Research-pipeline integration helper: formats an AiDcfResult (or its absence) into the
# text block the Valuation Analyst sub-agent's context needs (api/research_router.py).
# ---------------------------------------------------------------------------

def format_ai_dcf_summary(result: Optional[AiDcfResult]) -> str:
    """AI-authored DCF summary for the Valuation Analyst's context — assumptions + engine
    values + key debates, clearly labeled AI-AUTHORED so it's never confused with the
    mechanical engine-default DCF summary already in that context."""
    if result is None:
        return "[INFO] AI DCF unavailable for this run — proceed using the mechanical DCF alone"

    lines = [
        f"AI-AUTHORED DCF VALUATION — {result.ticker} "
        "(agent-authored assumptions, grounded in company history, industry trends, "
        "competitor transcripts, and multi-year MD&A/guidance — NOT the mechanical engine "
        "defaults shown above)",
        "",
    ]
    for label, key in [("BEAR", "bear"), ("BASE", "base"), ("BULL", "bull")]:
        e = result.engine.get(key)
        s = getattr(result.assumptions, key)
        if e is None:
            lines.append(f"{label}: [unavailable]")
            continue
        rev_growth = ", ".join(f"{g * 100:.1f}%" for g in s.revenue_growth)
        ebit_margin = ", ".join(f"{m * 100:.1f}%" for m in s.ebit_margin_pct)
        lines.append(
            f"{label}: intrinsic value/share = ${e['intrinsic_value_per_share']:.2f}  "
            f"| revenue growth Y1-Y5 = [{rev_growth}]  | EBIT margin Y1-Y5 = [{ebit_margin}]  "
            f"| TG = {e['terminal_growth_rate'] * 100:.2f}%  | WACC = {e['wacc'] * 100:.2f}%"
        )
        lines.append(f"  Rationale: {s.rationale}")
    lines += ["", f"WACC rationale: {result.assumptions.wacc_rationale}", ""]
    lines.append("KEY DEBATES (the assumption calls that most drive this valuation):")
    for d in result.assumptions.key_debates:
        lines.append(f"  - {d}")
    if result.qc_warnings:
        lines += ["", f"QC WARNINGS ({len(result.qc_warnings)}): " + "; ".join(result.qc_warnings[:5])]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 8 — DCF reconciliation audit trail (features/ai_dcf/SPEC.md 11). Deliberately deterministic,
# not a semantic grade of the Valuation Analyst's reconciliation prose — see SPEC 11 for why an
# LLM-graded check was rejected (low-value, circular: an LLM judging another LLM's compliance
# with an LLM's own instruction).
# ---------------------------------------------------------------------------

_RECONCILIATION_LOG_DB = _DATA_DIR / "dcf_reconciliation_log.duckdb"
_DIVERGENCE_WARN_THRESHOLD = 0.20   # >20% base-value disagreement, mirrors research_valuation.md
_MIN_RECONCILIATION_CHARS = 20      # below this, treat dcf_reconciliation as empty/near-empty


def compute_divergence_pct(mechanical_base: Optional[float], ai_base: Optional[float]) -> Optional[float]:
    """(ai_base - mechanical_base) / abs(mechanical_base). None if either value is missing or
    mechanical_base is 0 (divergence is undefined, not infinite)."""
    if mechanical_base is None or ai_base is None or mechanical_base == 0:
        return None
    return (ai_base - mechanical_base) / abs(mechanical_base)


def compute_dcf_anchor(
    fair_value_base: float, mechanical_base: Optional[float], ai_base: Optional[float],
) -> str:
    """Deterministic proxy for which DCF the Valuation Analyst's actual fair_value_base ended up
    numerically closer to — NOT a semantic judgment of its reconciliation reasoning. One of:
    "mechanical", "ai", "tied" (exactly equidistant), "mechanical_only", "ai_only" (only one DCF
    available), "neither_available"."""
    if mechanical_base is None and ai_base is None:
        return "neither_available"
    if mechanical_base is None:
        return "ai_only"
    if ai_base is None:
        return "mechanical_only"
    dist_mech = abs(fair_value_base - mechanical_base)
    dist_ai = abs(fair_value_base - ai_base)
    if dist_mech < dist_ai:
        return "mechanical"
    if dist_ai < dist_mech:
        return "ai"
    return "tied"


def _init_reconciliation_log() -> None:
    _RECONCILIATION_LOG_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(_RECONCILIATION_LOG_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dcf_reconciliation_log (
            ticker              VARCHAR,
            model               VARCHAR,
            generated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            mechanical_base     DOUBLE,
            ai_base             DOUBLE,
            divergence_pct      DOUBLE,
            anchor              VARCHAR,
            reconciliation_text VARCHAR
        )
    """)
    conn.close()


def log_dcf_reconciliation(
    ticker: str, model: str, mechanical_base: Optional[float], ai_base: Optional[float],
    fair_value_base: float, reconciliation_text: str,
) -> None:
    """Persists one audit-trail row per real research-report generation (never on a cache hit —
    callers only invoke this from the actual generation path): the two DCF base values (ground
    truth, not the Valuation Analyst's echoed fields), their divergence, a deterministic anchor
    label, and the raw reconciliation text. Never raises — a logging failure must not break
    report generation, matching this feature's failure-isolation contract elsewhere."""
    try:
        divergence_pct = compute_divergence_pct(mechanical_base, ai_base)
        anchor = compute_dcf_anchor(fair_value_base, mechanical_base, ai_base)
        _init_reconciliation_log()
        conn = duckdb.connect(str(_RECONCILIATION_LOG_DB))
        conn.execute("""
            INSERT INTO dcf_reconciliation_log
                (ticker, model, generated_at, mechanical_base, ai_base, divergence_pct, anchor, reconciliation_text)
            VALUES (?, ?, now(), ?, ?, ?, ?, ?)
        """, [ticker.upper(), model, mechanical_base, ai_base, divergence_pct, anchor, reconciliation_text])
        conn.close()
    except Exception as e:
        log.error("[%s] ai_dcf: failed to log DCF reconciliation (model=%s): %s", ticker, model, e)


def get_reconciliation_log(ticker: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Ad-hoc read helper for future analysis (e.g. "when the two DCFs disagreed a lot, which
    one was closer to how the stock actually performed") — not used by the live pipeline."""
    if not _RECONCILIATION_LOG_DB.exists():
        return []
    conn = duckdb.connect(str(_RECONCILIATION_LOG_DB), read_only=True)
    where = "WHERE ticker = ?" if ticker else ""
    params = [ticker.upper()] if ticker else []
    rows = conn.execute(f"""
        SELECT ticker, model, generated_at, mechanical_base, ai_base, divergence_pct, anchor, reconciliation_text
        FROM dcf_reconciliation_log {where}
        ORDER BY generated_at DESC LIMIT ?
    """, params + [limit]).fetchall()
    conn.close()
    cols = ["ticker", "model", "generated_at", "mechanical_base", "ai_base", "divergence_pct", "anchor", "reconciliation_text"]
    return [dict(zip(cols, r)) for r in rows]
