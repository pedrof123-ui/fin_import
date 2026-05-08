"""
Alpha Vantage financial statements database.

Usage:
    from av_financials_db import AVFinancialsDB, RateLimiter

    db = AVFinancialsDB()
    limiter = RateLimiter()
    rows = db.import_ticker("AAPL", api_key, limiter)
    results = db.query(["AAPL"], statement="income", period_type="annual")
    db.close()
"""

import logging
import time
from collections import deque
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = str(ROOT / "data" / "av_financials.duckdb")
_AV_URL = "https://www.alphavantage.co/query"

log = logging.getLogger(__name__)


# ── AV camelCase field → DB snake_case column ────────────────────────────────

_INCOME_COLS: list[tuple[str, str]] = [
    ("grossProfit",                        "gross_profit"),
    ("totalRevenue",                       "total_revenue"),
    ("costOfRevenue",                      "cost_of_revenue"),
    ("costofGoodsAndServicesSold",         "cost_of_goods_and_services_sold"),
    ("operatingIncome",                    "operating_income"),
    ("sellingGeneralAndAdministrative",    "selling_general_and_administrative"),
    ("researchAndDevelopment",             "research_and_development"),
    ("operatingExpenses",                  "operating_expenses"),
    ("investmentIncomeNet",                "investment_income_net"),
    ("netInterestIncome",                  "net_interest_income"),
    ("interestIncome",                     "interest_income"),
    ("interestExpense",                    "interest_expense"),
    ("nonInterestIncome",                  "non_interest_income"),
    ("otherNonOperatingIncome",            "other_non_operating_income"),
    ("depreciation",                       "depreciation"),
    ("depreciationAndAmortization",        "depreciation_and_amortization"),
    ("incomeBeforeTax",                    "income_before_tax"),
    ("incomeTaxExpense",                   "income_tax_expense"),
    ("interestAndDebtExpense",             "interest_and_debt_expense"),
    ("netIncomeFromContinuingOperations",  "net_income_from_continuing_ops"),
    ("comprehensiveIncomeNetOfTax",        "comprehensive_income_net_of_tax"),
    ("ebit",                               "ebit"),
    ("ebitda",                             "ebitda"),
    ("netIncome",                          "net_income"),
]

_BALANCE_COLS: list[tuple[str, str]] = [
    ("totalAssets",                           "total_assets"),
    ("totalCurrentAssets",                    "total_current_assets"),
    ("cashAndCashEquivalentsAtCarryingValue", "cash_and_cash_equivalents"),
    ("cashAndShortTermInvestments",           "cash_and_short_term_investments"),
    ("inventory",                             "inventory"),
    ("currentNetReceivables",                 "current_net_receivables"),
    ("totalNonCurrentAssets",                 "total_non_current_assets"),
    ("propertyPlantEquipment",                "property_plant_equipment"),
    ("accumulatedDepreciationAmortizationPPE","accumulated_depreciation_amortization_ppe"),
    ("intangibleAssets",                      "intangible_assets"),
    ("intangibleAssetsExcludingGoodwill",     "intangible_assets_excl_goodwill"),
    ("goodwill",                              "goodwill"),
    ("investments",                           "investments"),
    ("longTermInvestments",                   "long_term_investments"),
    ("shortTermInvestments",                  "short_term_investments"),
    ("otherCurrentAssets",                    "other_current_assets"),
    ("otherNonCurrentAssets",                 "other_non_current_assets"),
    ("totalLiabilities",                      "total_liabilities"),
    ("totalCurrentLiabilities",               "total_current_liabilities"),
    ("currentAccountsPayable",                "current_accounts_payable"),
    ("deferredRevenue",                       "deferred_revenue"),
    ("currentDebt",                           "current_debt"),
    ("shortTermDebt",                         "short_term_debt"),
    ("totalNonCurrentLiabilities",            "total_non_current_liabilities"),
    ("capitalLeaseObligations",               "capital_lease_obligations"),
    ("longTermDebt",                          "long_term_debt"),
    ("currentLongTermDebt",                   "current_long_term_debt"),
    ("longTermDebtNoncurrent",                "long_term_debt_noncurrent"),
    ("shortLongTermDebtTotal",                "short_long_term_debt_total"),
    ("otherCurrentLiabilities",               "other_current_liabilities"),
    ("otherNonCurrentLiabilities",            "other_non_current_liabilities"),
    ("totalShareholderEquity",                "total_shareholder_equity"),
    ("treasuryStock",                         "treasury_stock"),
    ("retainedEarnings",                      "retained_earnings"),
    ("commonStock",                           "common_stock"),
    ("commonStockSharesOutstanding",          "common_stock_shares_outstanding"),
]

_CASHFLOW_COLS: list[tuple[str, str]] = [
    ("operatingCashflow",                                         "operating_cashflow"),
    ("paymentsForOperatingActivities",                            "payments_for_operating_activities"),
    ("proceedsFromOperatingActivities",                           "proceeds_from_operating_activities"),
    ("changeInOperatingLiabilities",                              "change_in_operating_liabilities"),
    ("changeInOperatingAssets",                                   "change_in_operating_assets"),
    ("depreciationDepletionAndAmortization",                      "depreciation_depletion_and_amortization"),
    ("capitalExpenditures",                                       "capital_expenditures"),
    ("changeInReceivables",                                       "change_in_receivables"),
    ("changeInInventory",                                         "change_in_inventory"),
    ("profitLoss",                                                "profit_loss"),
    ("cashflowFromInvestment",                                    "cashflow_from_investment"),
    ("cashflowFromFinancing",                                     "cashflow_from_financing"),
    ("proceedsFromRepaymentsOfShortTermDebt",                     "proceeds_from_repayments_short_term_debt"),
    ("paymentsForRepurchaseOfCommonStock",                        "payments_for_repurchase_common_stock"),
    ("paymentsForRepurchaseOfEquity",                             "payments_for_repurchase_equity"),
    ("paymentsForRepurchaseOfPreferredStock",                     "payments_for_repurchase_preferred_stock"),
    ("dividendPayout",                                            "dividend_payout"),
    ("dividendPayoutCommonStock",                                 "dividend_payout_common_stock"),
    ("dividendPayoutPreferredStock",                              "dividend_payout_preferred_stock"),
    ("proceedsFromIssuanceOfCommonStock",                         "proceeds_from_issuance_common_stock"),
    ("proceedsFromIssuanceOfLongTermDebtAndCapitalSecuritiesNet", "proceeds_from_issuance_long_term_debt"),
    ("proceedsFromIssuanceOfPreferredStock",                      "proceeds_from_issuance_preferred_stock"),
    ("proceedsFromRepurchaseOfEquity",                            "proceeds_from_repurchase_equity"),
    ("proceedsFromSaleOfTreasuryStock",                           "proceeds_from_sale_treasury_stock"),
    ("stockBasedCompensation",                                    "stock_based_compensation"),
    ("changeInCashAndCashEquivalents",                            "change_in_cash_and_cash_equivalents"),
    ("changeInExchangeRate",                                      "change_in_exchange_rate"),
    ("netIncome",                                                 "net_income"),
]


def _v(raw: Any) -> float | None:
    """Convert an AV string value to float, returning None for missing data."""
    if raw is None or raw == "None":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class RateLimiter:
    """
    Rate limiter: at most max_calls per period seconds, with minimum inter-call spacing.

    The minimum spacing (period / max_calls) prevents per-second burst rejections even
    when the minute-level quota has not been reached.
    """

    def __init__(self, max_calls: int = 75, period: float = 60.0) -> None:
        self._max = max_calls
        self._period = period
        self._min_interval = period / max_calls  # 0.8s for 75/min
        self._calls: deque[float] = deque()

    def wait(self) -> None:
        now = time.monotonic()
        # Enforce minimum spacing between consecutive calls
        if self._calls:
            since_last = now - self._calls[-1]
            if since_last < self._min_interval:
                time.sleep(self._min_interval - since_last)
                now = time.monotonic()
        # Enforce sliding-window minute-level limit
        while self._calls and now - self._calls[0] >= self._period:
            self._calls.popleft()
        if len(self._calls) >= self._max:
            sleep_for = self._period - (now - self._calls[0])
            if sleep_for > 0:
                log.debug("Rate limit reached; sleeping %.1fs", sleep_for)
                time.sleep(sleep_for)
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= self._period:
                self._calls.popleft()
        self._calls.append(time.monotonic())


class AVFinancialsDB:
    """Manages a DuckDB database of Alpha Vantage financial statements."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self._create_schema()
        log.debug("Connected to %s", db_path)

    # ── Schema ───────────────────────────────────────────────────────────────

    def _create_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                ticker          VARCHAR PRIMARY KEY,
                last_updated_at TIMESTAMP,
                total_annual    INTEGER DEFAULT 0,
                total_quarterly INTEGER DEFAULT 0
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS income_statements (
                ticker                              VARCHAR NOT NULL,
                fiscal_date_ending                  DATE    NOT NULL,
                period_type                         VARCHAR NOT NULL,
                reported_currency                   VARCHAR,
                fetched_at                          TIMESTAMP,
                gross_profit                        DOUBLE,
                total_revenue                       DOUBLE,
                cost_of_revenue                     DOUBLE,
                cost_of_goods_and_services_sold     DOUBLE,
                operating_income                    DOUBLE,
                selling_general_and_administrative  DOUBLE,
                research_and_development            DOUBLE,
                operating_expenses                  DOUBLE,
                investment_income_net               DOUBLE,
                net_interest_income                 DOUBLE,
                interest_income                     DOUBLE,
                interest_expense                    DOUBLE,
                non_interest_income                 DOUBLE,
                other_non_operating_income          DOUBLE,
                depreciation                        DOUBLE,
                depreciation_and_amortization       DOUBLE,
                income_before_tax                   DOUBLE,
                income_tax_expense                  DOUBLE,
                interest_and_debt_expense           DOUBLE,
                net_income_from_continuing_ops      DOUBLE,
                comprehensive_income_net_of_tax     DOUBLE,
                ebit                                DOUBLE,
                ebitda                              DOUBLE,
                net_income                          DOUBLE,
                PRIMARY KEY (ticker, fiscal_date_ending, period_type)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS balance_sheets (
                ticker                                   VARCHAR NOT NULL,
                fiscal_date_ending                       DATE    NOT NULL,
                period_type                              VARCHAR NOT NULL,
                reported_currency                        VARCHAR,
                fetched_at                               TIMESTAMP,
                total_assets                             DOUBLE,
                total_current_assets                     DOUBLE,
                cash_and_cash_equivalents                DOUBLE,
                cash_and_short_term_investments          DOUBLE,
                inventory                                DOUBLE,
                current_net_receivables                  DOUBLE,
                total_non_current_assets                 DOUBLE,
                property_plant_equipment                 DOUBLE,
                accumulated_depreciation_amortization_ppe DOUBLE,
                intangible_assets                        DOUBLE,
                intangible_assets_excl_goodwill          DOUBLE,
                goodwill                                 DOUBLE,
                investments                              DOUBLE,
                long_term_investments                    DOUBLE,
                short_term_investments                   DOUBLE,
                other_current_assets                     DOUBLE,
                other_non_current_assets                 DOUBLE,
                total_liabilities                        DOUBLE,
                total_current_liabilities                DOUBLE,
                current_accounts_payable                 DOUBLE,
                deferred_revenue                         DOUBLE,
                current_debt                             DOUBLE,
                short_term_debt                          DOUBLE,
                total_non_current_liabilities            DOUBLE,
                capital_lease_obligations                DOUBLE,
                long_term_debt                           DOUBLE,
                current_long_term_debt                   DOUBLE,
                long_term_debt_noncurrent                DOUBLE,
                short_long_term_debt_total               DOUBLE,
                other_current_liabilities                DOUBLE,
                other_non_current_liabilities            DOUBLE,
                total_shareholder_equity                 DOUBLE,
                treasury_stock                           DOUBLE,
                retained_earnings                        DOUBLE,
                common_stock                             DOUBLE,
                common_stock_shares_outstanding          DOUBLE,
                PRIMARY KEY (ticker, fiscal_date_ending, period_type)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cash_flow_statements (
                ticker                                  VARCHAR NOT NULL,
                fiscal_date_ending                      DATE    NOT NULL,
                period_type                             VARCHAR NOT NULL,
                reported_currency                       VARCHAR,
                fetched_at                              TIMESTAMP,
                operating_cashflow                      DOUBLE,
                payments_for_operating_activities       DOUBLE,
                proceeds_from_operating_activities      DOUBLE,
                change_in_operating_liabilities         DOUBLE,
                change_in_operating_assets              DOUBLE,
                depreciation_depletion_and_amortization DOUBLE,
                capital_expenditures                    DOUBLE,
                change_in_receivables                   DOUBLE,
                change_in_inventory                     DOUBLE,
                profit_loss                             DOUBLE,
                cashflow_from_investment                DOUBLE,
                cashflow_from_financing                 DOUBLE,
                proceeds_from_repayments_short_term_debt DOUBLE,
                payments_for_repurchase_common_stock    DOUBLE,
                payments_for_repurchase_equity          DOUBLE,
                payments_for_repurchase_preferred_stock DOUBLE,
                dividend_payout                         DOUBLE,
                dividend_payout_common_stock            DOUBLE,
                dividend_payout_preferred_stock         DOUBLE,
                proceeds_from_issuance_common_stock     DOUBLE,
                proceeds_from_issuance_long_term_debt   DOUBLE,
                proceeds_from_issuance_preferred_stock  DOUBLE,
                proceeds_from_repurchase_equity         DOUBLE,
                proceeds_from_sale_treasury_stock       DOUBLE,
                stock_based_compensation                DOUBLE,
                change_in_cash_and_cash_equivalents     DOUBLE,
                change_in_exchange_rate                 DOUBLE,
                net_income                              DOUBLE,
                PRIMARY KEY (ticker, fiscal_date_ending, period_type)
            )
        """)

        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS import_log_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS import_log (
                id               INTEGER PRIMARY KEY DEFAULT nextval('import_log_seq'),
                ticker           VARCHAR   NOT NULL,
                run_at           TIMESTAMP NOT NULL,
                success          BOOLEAN   NOT NULL,
                statements       VARCHAR,
                periods_inserted INTEGER,
                error_msg        VARCHAR
            )
        """)

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def _fetch(self, function: str, symbol: str, api_key: str, limiter: RateLimiter) -> dict:
        limiter.wait()
        log.debug("GET %s %s", function, symbol)
        resp = requests.get(
            _AV_URL,
            params={"function": function, "symbol": symbol, "apikey": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for key in ("Error Message", "Information", "Note"):
            if data.get(key):
                raise RuntimeError(f"AV API [{function}] {data[key]}")
        return data

    # ── Upsert helpers ────────────────────────────────────────────────────────

    def _upsert_rows(
        self,
        table: str,
        col_map: list[tuple[str, str]],
        ticker: str,
        reports: list[dict],
        period_type: str,
    ) -> int:
        if not reports:
            return 0
        db_cols = [db for _, db in col_map]
        placeholders = ", ".join(["?"] * (5 + len(db_cols)))
        col_list = "ticker, fiscal_date_ending, period_type, reported_currency, fetched_at, " + ", ".join(db_cols)
        sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
        fetched_at = datetime.now(UTC)
        count = 0
        for report in reports:
            currency = report.get("reportedCurrency")
            values = [
                ticker,
                report["fiscalDateEnding"],
                period_type,
                currency,
                fetched_at,
                *[_v(report.get(av)) for av, _ in col_map],
            ]
            self.conn.execute(sql, values)
            count += 1
        return count

    def _upsert_income(self, ticker: str, reports: list[dict], period_type: str) -> int:
        return self._upsert_rows("income_statements", _INCOME_COLS, ticker, reports, period_type)

    def _upsert_balance(self, ticker: str, reports: list[dict], period_type: str) -> int:
        return self._upsert_rows("balance_sheets", _BALANCE_COLS, ticker, reports, period_type)

    def _upsert_cashflow(self, ticker: str, reports: list[dict], period_type: str) -> int:
        return self._upsert_rows("cash_flow_statements", _CASHFLOW_COLS, ticker, reports, period_type)

    # ── Company metadata ──────────────────────────────────────────────────────

    def _update_company(self, ticker: str) -> None:
        annual = self.conn.execute(
            "SELECT COUNT(*) FROM income_statements WHERE ticker = ? AND period_type = 'annual'",
            [ticker],
        ).fetchone()[0]
        quarterly = self.conn.execute(
            "SELECT COUNT(*) FROM income_statements WHERE ticker = ? AND period_type = 'quarterly'",
            [ticker],
        ).fetchone()[0]
        existing = self.conn.execute(
            "SELECT ticker FROM companies WHERE ticker = ?", [ticker]
        ).fetchone()
        now = datetime.now(UTC)
        if existing:
            self.conn.execute(
                "UPDATE companies SET last_updated_at = ?, total_annual = ?, total_quarterly = ? WHERE ticker = ?",
                [now, annual, quarterly, ticker],
            )
        else:
            self.conn.execute(
                "INSERT INTO companies (ticker, last_updated_at, total_annual, total_quarterly) VALUES (?, ?, ?, ?)",
                [ticker, now, annual, quarterly],
            )

    def _log_import(
        self,
        ticker: str,
        success: bool,
        statements: str | None,
        periods_inserted: int,
        error_msg: str | None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO import_log (ticker, run_at, success, statements, periods_inserted, error_msg)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [ticker, datetime.now(UTC), success, statements, periods_inserted, error_msg],
        )

    # ── Public: import ────────────────────────────────────────────────────────

    def import_ticker(self, ticker: str, api_key: str, limiter: RateLimiter) -> int:
        """
        Fetch all three financial statements for ticker and upsert into the DB.
        Returns total rows inserted. Raises on unrecoverable error.
        """
        log.info("Importing %s", ticker)
        total = 0
        succeeded: list[str] = []
        errors: list[str] = []

        for function, upsert_fn, label in [
            ("INCOME_STATEMENT", self._income_upsert_from_payload, "income"),
            ("BALANCE_SHEET",    self._balance_upsert_from_payload,  "balance"),
            ("CASH_FLOW",        self._cashflow_upsert_from_payload,  "cashflow"),
        ]:
            try:
                payload = self._fetch(function, ticker, api_key, limiter)
                n = upsert_fn(ticker, payload)
                total += n
                succeeded.append(label)
                log.info("  %s: %d rows", label, n)
            except Exception as exc:
                log.warning("  %s failed for %s: %s", label, ticker, exc)
                errors.append(f"{label}: {exc}")

        success = len(succeeded) == 3
        if succeeded:
            self._update_company(ticker)

        self._log_import(
            ticker,
            success=success,
            statements=",".join(succeeded) if succeeded else None,
            periods_inserted=total,
            error_msg="; ".join(errors) if errors else None,
        )

        if not succeeded:
            raise RuntimeError(f"All statements failed for {ticker}: {'; '.join(errors)}")

        return total

    def _income_upsert_from_payload(self, ticker: str, payload: dict) -> int:
        n = self._upsert_income(ticker, payload.get("annualReports", []), "annual")
        n += self._upsert_income(ticker, payload.get("quarterlyReports", []), "quarterly")
        return n

    def _balance_upsert_from_payload(self, ticker: str, payload: dict) -> int:
        n = self._upsert_balance(ticker, payload.get("annualReports", []), "annual")
        n += self._upsert_balance(ticker, payload.get("quarterlyReports", []), "quarterly")
        return n

    def _cashflow_upsert_from_payload(self, ticker: str, payload: dict) -> int:
        n = self._upsert_cashflow(ticker, payload.get("annualReports", []), "annual")
        n += self._upsert_cashflow(ticker, payload.get("quarterlyReports", []), "quarterly")
        return n

    # ── Public: query ─────────────────────────────────────────────────────────

    def query(
        self,
        tickers: list[str],
        statement: str = "all",
        period_type: str = "all",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, pd.DataFrame]:
        """
        Return stored financial statements as DataFrames.

        Args:
            tickers:     One or more ticker symbols.
            statement:   'income', 'balance', 'cashflow', or 'all'.
            period_type: 'annual', 'quarterly', or 'all'.
            start_date:  Inclusive lower bound on fiscal_date_ending.
            end_date:    Inclusive upper bound on fiscal_date_ending.

        Returns:
            Dict keyed by statement name ('income', 'balance', 'cashflow').
        """
        table_map = {
            "income":   "income_statements",
            "balance":  "balance_sheets",
            "cashflow": "cash_flow_statements",
        }
        targets = list(table_map.keys()) if statement == "all" else [statement]

        placeholders = ", ".join(["?"] * len(tickers))
        params: list[Any] = list(tickers)
        where = f"WHERE ticker IN ({placeholders})"

        if period_type != "all":
            where += " AND period_type = ?"
            params.append(period_type)
        if start_date is not None:
            where += " AND fiscal_date_ending >= ?"
            params.append(start_date)
        if end_date is not None:
            where += " AND fiscal_date_ending <= ?"
            params.append(end_date)

        results: dict[str, pd.DataFrame] = {}
        for key in targets:
            table = table_map[key]
            df = self.conn.execute(
                f"SELECT * FROM {table} {where} ORDER BY ticker, fiscal_date_ending DESC",
                params,
            ).df()
            results[key] = df

        return results

    # ── Public: helpers ───────────────────────────────────────────────────────

    def list_tickers(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT ticker FROM companies ORDER BY ticker").fetchall()]

    def has_ticker(self, ticker: str) -> bool:
        return self.conn.execute(
            "SELECT COUNT(*) FROM companies WHERE ticker = ?", [ticker]
        ).fetchone()[0] > 0

    def close(self) -> None:
        self.conn.close()
        log.debug("Connection closed")
