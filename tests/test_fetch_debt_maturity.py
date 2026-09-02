"""
Tests for scripts/fetch_debt_maturity.py (PLAN_DEBT_MATURITY.md Phase 1).

Runs against cached HTML fixtures (tests/fixtures/debt_maturity/), not live SEC calls --
per the plan's Phase 1.3. Fixtures are real TextBlock HTML captured from IBM, AAPL, and
Southern Company's 10-Ks, chosen to cover the layout variants found in Phase 0/1: IBM's
multi-currency per-bond-year table, Apple's coarse two-bucket table with a secondary
"effective rate" column, and Southern Company's multi-subsidiary table where the coupon
column comes after (not before) the maturity-year column.
"""

from pathlib import Path

import pytest

from scripts.fetch_debt_maturity import (
    parse_debt_instruments,
    parse_maturities_ladder,
    extract_debt_tranches,
)

FIXTURES = Path(__file__).parent / "fixtures" / "debt_maturity"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def _by_label(rows, label):
    return next(r for r in rows if r["raw_label"] == label)


# --- IBM: multi-currency, per-bond-year, coupon-before-year ---------------------------

class TestIBM:
    def test_debt_instruments_row_count(self):
        rows = parse_debt_instruments(_load("ibm_debt_instruments.html"))
        assert len(rows) == 43  # 25 USD + 14 EUR + 2 named other-currency + 1 finance lease

    def test_matured_tranche_is_zero_not_dropped(self):
        rows = parse_debt_instruments(_load("ibm_debt_instruments.html"))
        matured = [r for r in rows if r["raw_label"] == "5.1%" and r["maturity_year"] == 2025]
        assert matured and matured[0]["amount"] == 0.0

    def test_usd_tranche(self):
        rows = parse_debt_instruments(_load("ibm_debt_instruments.html"))
        r = next(r for r in rows if r["raw_label"] == "3.7%" and r["maturity_year"] == 2026)
        assert r["amount"] == 5800.0
        assert r["coupon_rate"] == pytest.approx(0.037)
        assert r["currency"] == "USD"

    def test_euro_section_currency(self):
        rows = parse_debt_instruments(_load("ibm_debt_instruments.html"))
        r = next(r for r in rows if r["raw_label"] == "2.3%" and r["maturity_year"] == 2027)
        assert r["currency"] == "EUR"

    def test_named_currency_overrides_section(self):
        rows = parse_debt_instruments(_load("ibm_debt_instruments.html"))
        gbp = _by_label(rows, "Pound sterling (4.9%)")
        jpy = _by_label(rows, "Japanese yen (1.0%)")
        assert gbp["currency"] == "GBP" and gbp["coupon_rate"] == pytest.approx(0.049)
        assert jpy["currency"] == "JPY" and jpy["coupon_rate"] == pytest.approx(0.01)

    def test_ambiguous_section_falls_back_to_usd_not_prior_currency(self):
        """The "Other currencies" umbrella header doesn't name a single currency, and
        follows the Euro section -- regression test for a currency-state leak where an
        unresolved header row left the previous section's currency (EUR) in effect."""
        rows = parse_debt_instruments(_load("ibm_debt_instruments.html"))
        other = _by_label(rows, "Other (13.8%)")
        lease = _by_label(rows, "Finance lease obligations (5.1% weighted-average interest rate at December\xa031, 2025)")
        assert other["currency"] == "USD"
        assert lease["currency"] == "USD"

    def test_maturities_ladder(self):
        rows = parse_maturities_ladder(_load("ibm_maturities_ladder.html"))
        by_year = {r["maturity_year"]: r["amount"] for r in rows if r["maturity_year"]}
        assert by_year == {2026: 6425.0, 2027: 6753.0, 2028: 5172.0, 2029: 5095.0, 2030: 4492.0}
        thereafter = next(r for r in rows if r["maturity_year"] is None)
        assert thereafter["amount"] == 34348.0
        assert all(r["coupon_rate"] is None for r in rows)


# --- Apple: coarse buckets, coupon range in description, secondary rate column --------

class TestAAPL:
    def test_debt_instruments(self):
        rows = parse_debt_instruments(_load("aapl_debt_instruments.html"))
        assert len(rows) == 2
        bulk = _by_label(rows, "Fixed-rate 0.000% – 4.850% notes")
        assert bulk["amount"] == 86781.0
        assert bulk["coupon_rate"] == pytest.approx(0.02425)  # midpoint of the stated range
        assert bulk["maturity_year"] == 2044  # midpoint of 2025-2062, not the secondary rate col

        recent = _by_label(rows, "Fixed-rate 4.000% – 4.750% notes")
        assert recent["amount"] == 4500.0
        assert recent["maturity_year"] == 2032

    def test_maturities_ladder(self):
        rows = parse_maturities_ladder(_load("aapl_maturities_ladder.html"))
        by_year = {r["maturity_year"]: r["amount"] for r in rows if r["maturity_year"]}
        assert by_year == {2026: 12393.0, 2027: 10078.0, 2028: 9300.0, 2029: 5235.0, 2030: 4972.0}
        assert next(r for r in rows if r["maturity_year"] is None)["amount"] == 49303.0


# --- Southern Company: multi-subsidiary, coupon *after* the year column ---------------

class TestSouthernCompany:
    def test_coupon_after_year_layout(self):
        """Southern Co.'s column order is description, year-range, coupon%, amount --
        the opposite of IBM's coupon-then-year order."""
        rows = parse_debt_instruments(_load("so_debt_instruments.html"))
        senior_notes = [r for r in rows if r["raw_label"] == "Senior notes(a)"]
        assert senior_notes  # was silently dropped to zero rows before the fix
        r = senior_notes[0]
        assert r["coupon_rate"] == pytest.approx(0.0438)
        assert r["amount"] == 49922.0
        assert r["maturity_year"] == 2050  # midpoint of the disclosed 2026-2075 range

    def test_maturities_ladder_picks_parent_column_not_subsidiary(self):
        """The ladder table has one column per subsidiary; the ticker's own (first,
        consolidated "Southern Company") column must be picked, not a subsidiary's."""
        rows = parse_maturities_ladder(_load("so_maturities_ladder.html"))
        by_year = {r["maturity_year"]: r["amount"] for r in rows}
        assert by_year[2026] == 6211.0
        assert by_year[2027] == 3407.0


# --- Generic edge cases (synthetic HTML, no fixture needed) ---------------------------

class TestEdgeCases:
    def test_empty_html(self):
        assert parse_debt_instruments("") == []
        assert parse_maturities_ladder("<p>no tables here</p>") == []

    def test_total_row_excluded(self):
        html = "<table><tr><td>Total</td><td>2026</td><td>4.0%</td><td>1000</td></tr></table>"
        assert parse_debt_instruments(html) == []

    def test_dash_amount_is_zero(self):
        html = "<table><tr><td>3.0% notes due 2027</td><td>—</td></tr></table>"
        rows = parse_debt_instruments(html)
        assert rows and rows[0]["amount"] == 0.0

    def test_no_coupon_no_data_row(self):
        """A maturities-ladder-style row with no % anywhere is correctly rejected by
        the debt-instruments parser (require_coupon=True) but accepted by the
        maturities-ladder parser (coupon not required)."""
        html = "<table><tr><td>2026</td><td>1000</td></tr></table>"
        assert parse_debt_instruments(html) == []
        rows = parse_maturities_ladder(html)
        assert rows and rows[0]["amount"] == 1000.0 and rows[0]["coupon_rate"] is None


# --- extract_debt_tranches wiring (fake filing, no network) ---------------------------

class _FakeFacts:
    def __init__(self, df):
        self._df = df

    def to_dataframe(self):
        return self._df


class _FakeXBRL:
    def __init__(self, df):
        self.facts = _FakeFacts(df)


class _FakeFiling:
    def __init__(self, df, cik="12345", filing_date="2026-01-01"):
        self._df = df
        self.cik = cik
        self.filing_date = filing_date

    def xbrl(self):
        return _FakeXBRL(self._df)


def test_extract_debt_tranches_no_coverage_returns_empty():
    import pandas as pd

    empty = pd.DataFrame(columns=["concept", "value", "fiscal_year"])
    assert extract_debt_tranches("ZZZZ", filing=_FakeFiling(empty)) == []


def test_extract_debt_tranches_no_filing_returns_empty(monkeypatch):
    import scripts.fetch_debt_maturity as mod

    class _NoFilings:
        def get_filings(self, **kwargs):
            class _Empty:
                def latest(self_inner):
                    return None
            return _Empty()

    monkeypatch.setattr(mod, "Company", lambda ticker: _NoFilings())
    assert extract_debt_tranches("ZZZZ") == []


def test_extract_debt_tranches_wires_ticker_cik_fiscal_year():
    import pandas as pd

    html = "<table><tr><td>2026</td><td>1000</td></tr></table>"
    df = pd.DataFrame([
        {
            "concept": "us-gaap:ScheduleOfMaturitiesOfLongTermDebtTableTextBlock",
            "value": html,
            "fiscal_year": 2025,
        }
    ])
    rows = extract_debt_tranches("ACME", filing=_FakeFiling(df, cik="999", filing_date="2026-03-01"))
    assert len(rows) == 1
    r = rows[0]
    assert r["ticker"] == "ACME"
    assert r["cik"] == "999"
    assert r["fiscal_year"] == 2025
    assert r["filed_date"] == "2026-03-01"
    assert r["source_concept"] == "maturities_ladder"
