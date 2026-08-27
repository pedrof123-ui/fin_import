"""
Cost-of-debt-vs-risk-free-rate sanity warning (features/ai_dcf/PLAN_GUARDRAILS.md Phase 1).

Background: the IBM 2026-08-27 research report showed a 2.0% cost of debt against a 5.17%
risk-free rate -- economically odd-looking, but not necessarily wrong (a company can carry a
genuinely low *embedded* cost of debt on fixed-rate debt issued before the current rate-hike
cycle). The actual problem is that dcf.model.run_dcf_av applies a single flat WACC to both the
5-year forecast and the terminal value, and an embedded rate that low is not a defensible
discount rate for the terminal value. This is therefore an advisory warning (dcf.model.py, next
to the existing WACC<5% check), never a clip -- compute_cost_of_debt's own [2%,15%] embedded-rate
estimate is untouched.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from dcf import wacc as wacc_mod
from dcf.assumptions import UserOverrides
from dcf.av_data import AV_DB
from dcf.data import PRICES_DB
from dcf.model import run_dcf_av


def _income_df(diluted_shares: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame({"diluted_shares": [diluted_shares]})


def _balance_df(long_term_debt: float = 1000.0) -> pd.DataFrame:
    return pd.DataFrame({
        "short_term_debt": [0.0],
        "current_portion_long_term_debt": [0.0],
        "long_term_debt": [long_term_debt],
    })


@pytest.fixture(autouse=True)
def _stub_betas(monkeypatch):
    """compute_wacc always calls get_betas regardless of beta_override -- stub it so these are
    pure unit tests with no dependency on the stored-beta database."""
    monkeypatch.setattr(wacc_mod, "get_betas", lambda ticker, as_of=None: (1.0, 1.0))


def test_wacc_detail_flags_cost_of_debt_below_risk_free_rate():
    """The exact IBM shape: 2.0% cost of debt vs. a 5.17% risk-free rate must be visible on
    WaccDetail so dcf.model.run_dcf_av's warning check can fire."""
    detail = wacc_mod.compute_wacc(
        ticker="TESTCO",
        income_df=_income_df(),
        balance_df=_balance_df(),
        current_price=100.0,
        risk_free_rate=0.0517,
        cost_of_debt_override=0.02,
        tax_rate_override=0.21,
    )
    assert detail.cost_of_debt < detail.risk_free_rate


def test_wacc_detail_does_not_flag_cost_of_debt_above_risk_free_rate():
    detail = wacc_mod.compute_wacc(
        ticker="TESTCO",
        income_df=_income_df(),
        balance_df=_balance_df(),
        current_price=100.0,
        risk_free_rate=0.0517,
        cost_of_debt_override=0.08,
        tax_rate_override=0.21,
    )
    assert detail.cost_of_debt >= detail.risk_free_rate


@pytest.fixture(scope="module")
def _require_dbs():
    if not AV_DB.exists() or not PRICES_DB.exists():
        pytest.skip("AV or prices database not present")


def test_run_dcf_av_warns_when_cost_of_debt_below_risk_free_rate(_require_dbs):
    result = run_dcf_av(
        "AAPL",
        overrides=UserOverrides(risk_free_rate=0.06, cost_of_debt_override=0.02),
        as_of=date(2024, 6, 30),
    )
    assert any(
        "Cost of debt" in w and "risk-free rate" in w for w in result.warnings
    ), f"expected a cost-of-debt-vs-risk-free-rate warning, got: {result.warnings}"


def test_run_dcf_av_does_not_warn_when_cost_of_debt_above_risk_free_rate(_require_dbs):
    result = run_dcf_av(
        "AAPL",
        overrides=UserOverrides(risk_free_rate=0.03, cost_of_debt_override=0.08),
        as_of=date(2024, 6, 30),
    )
    assert not any("Cost of debt" in w and "risk-free rate" in w for w in result.warnings)
