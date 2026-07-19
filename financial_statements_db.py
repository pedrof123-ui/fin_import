"""
Financial Statements Database Manager
Stores 10-K and 10-Q financial statements in DuckDB for analysis

Features:
- Stores income statements, balance sheets, and cash flow statements
- Supports both annual (10-K) and quarterly (10-Q) filings
- Tracks filing dates and period end dates
- Data quality metrics
- Time series analysis
- Easy querying and export

Usage:
    from financial_statements_db import FinancialStatementsDB
    
    # Create database
    db = FinancialStatementsDB('data/financial_statements.duckdb')
    
    # Insert statements
    db.insert_income_statement(income_df)
    db.insert_balance_sheet(balance_df)
    db.insert_cash_flow(cashflow_df)
    
    # Query
    aapl_data = db.get_company_statements('AAPL')
    revenue_ts = db.get_time_series('AAPL', 'income', 'revenue')
"""

import os

import duckdb
import pandas as pd
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pathlib import Path

_DEFAULT_FS_DB = os.environ.get("FINANCIAL_STATEMENTS_DB_PATH", "data/financial_statements.duckdb")


class FinancialStatementsDB:
    """
    Manages DuckDB database for financial statements storage and analysis
    """
    
    def __init__(self, db_path: str = _DEFAULT_FS_DB):
        """
        Initialize database connection and create tables if needed
        
        Args:
            db_path: Path to DuckDB database file
        """
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self._create_schema()
        print(f"Connected to financial statements database: {db_path}")
    
    def _create_schema(self):
        """Create database schema with all necessary tables"""
        
        # ====================================================================
        # COMPANIES TABLE - Master company information
        # ====================================================================
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                ticker VARCHAR PRIMARY KEY,
                company_name VARCHAR,
                cik VARCHAR,
                sector VARCHAR,
                industry VARCHAR,
                first_filing_date DATE,
                last_filing_date DATE,
                total_filings INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # ====================================================================
        # INCOME STATEMENTS TABLE
        # ====================================================================
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS income_statements (
                -- Primary Key
                ticker VARCHAR NOT NULL,
                filing_date DATE NOT NULL,
                period_end_date DATE NOT NULL,
                
                -- Metadata
                filing_type VARCHAR,        -- 10-K, 10-Q, 10-K/A, etc.
                fiscal_year INTEGER,
                fiscal_quarter INTEGER,     -- 1-4 for quarterly, NULL for annual
                period_type VARCHAR,        -- 'Annual' or 'Quarterly'
                
                -- Data Quality
                extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fields_extracted INTEGER,
                total_fields INTEGER,
                coverage_pct DOUBLE,
                
                -- Revenue & Costs
                revenue DOUBLE,
                cost_of_revenue DOUBLE,
                gross_profit DOUBLE,
                
                -- Operating Expenses
                research_development DOUBLE,
                selling_general_admin DOUBLE,
                depreciation_amortization DOUBLE,
                restructuring_charges DOUBLE,
                other_operating_expenses DOUBLE,
                total_operating_expenses DOUBLE,
                operating_income DOUBLE,
                
                -- Non-Operating Items
                interest_income DOUBLE,
                interest_expense DOUBLE,
                equity_method_investments DOUBLE,
                investment_gains_losses DOUBLE,
                other_nonoperating_income DOUBLE,
                
                -- Pre-tax and Tax
                pretax_income DOUBLE,
                income_tax_expense DOUBLE,
                tax_rate DOUBLE,
                
                -- Net Income
                net_income_continuing_ops DOUBLE,
                discontinued_operations DOUBLE,
                net_income DOUBLE,
                net_income_attributable_to_nci DOUBLE,
                net_income_attributable_to_parent DOUBLE,
                
                -- Comprehensive Income
                other_comprehensive_income DOUBLE,
                comprehensive_income DOUBLE,
                
                -- Per Share Data
                basic_eps DOUBLE,
                diluted_eps DOUBLE,
                basic_shares DOUBLE,
                diluted_shares DOUBLE,
                
                -- Primary Key Constraint
                PRIMARY KEY (ticker, filing_date, period_end_date)
            )
        """)
        
        # ====================================================================
        # BALANCE SHEETS TABLE
        # ====================================================================
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS balance_sheets (
                -- Primary Key
                ticker VARCHAR NOT NULL,
                filing_date DATE NOT NULL,
                period_end_date DATE NOT NULL,
                
                -- Metadata
                filing_type VARCHAR,
                fiscal_year INTEGER,
                fiscal_quarter INTEGER,
                period_type VARCHAR,
                
                -- Data Quality
                extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fields_extracted INTEGER,
                total_fields INTEGER,
                coverage_pct DOUBLE,
                
                -- Current Assets
                cash_and_equivalents DOUBLE,
                short_term_investments DOUBLE,
                accounts_receivable DOUBLE,
                inventory DOUBLE,
                prepaid_expenses DOUBLE,
                other_current_assets DOUBLE,
                total_current_assets DOUBLE,
                
                -- Non-Current Assets
                ppe_gross DOUBLE,
                accumulated_depreciation DOUBLE,
                ppe_net DOUBLE,
                goodwill DOUBLE,
                intangible_assets DOUBLE,
                long_term_investments DOUBLE,
                deferred_tax_assets DOUBLE,
                other_noncurrent_assets DOUBLE,
                total_noncurrent_assets DOUBLE,
                total_assets DOUBLE,
                
                -- Current Liabilities
                accounts_payable DOUBLE,
                accrued_expenses DOUBLE,
                short_term_debt DOUBLE,
                current_portion_long_term_debt DOUBLE,
                deferred_revenue_current DOUBLE,
                other_current_liabilities DOUBLE,
                total_current_liabilities DOUBLE,
                
                -- Non-Current Liabilities
                long_term_debt DOUBLE,
                deferred_tax_liabilities DOUBLE,
                deferred_revenue_noncurrent DOUBLE,
                other_noncurrent_liabilities DOUBLE,
                total_noncurrent_liabilities DOUBLE,
                total_liabilities DOUBLE,
                
                -- Equity
                common_stock DOUBLE,
                additional_paid_in_capital DOUBLE,
                retained_earnings DOUBLE,
                treasury_stock DOUBLE,
                accumulated_other_comprehensive_income DOUBLE,
                total_stockholders_equity DOUBLE,
                noncontrolling_interest DOUBLE,
                total_equity DOUBLE,
                
                -- Validation
                total_liabilities_and_equity DOUBLE,
                
                -- Primary Key Constraint
                PRIMARY KEY (ticker, filing_date, period_end_date)
            )
        """)
        
        # ====================================================================
        # CASH FLOW STATEMENTS TABLE
        # ====================================================================
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cash_flow_statements (
                -- Primary Key
                ticker VARCHAR NOT NULL,
                filing_date DATE NOT NULL,
                period_end_date DATE NOT NULL,
                
                -- Metadata
                filing_type VARCHAR,
                fiscal_year INTEGER,
                fiscal_quarter INTEGER,
                period_type VARCHAR,
                
                -- Data Quality
                extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fields_extracted INTEGER,
                total_fields INTEGER,
                coverage_pct DOUBLE,
                
                -- Operating Activities
                net_income_starting_point DOUBLE,
                depreciation_amortization DOUBLE,
                stock_based_compensation DOUBLE,
                deferred_taxes DOUBLE,
                change_accounts_receivable DOUBLE,
                change_inventory DOUBLE,
                change_accounts_payable DOUBLE,
                change_accrued_expenses DOUBLE,
                change_deferred_revenue DOUBLE,
                other_operating_activities DOUBLE,
                net_cash_operating_activities DOUBLE,
                
                -- Investing Activities
                capital_expenditures DOUBLE,
                acquisitions DOUBLE,
                purchase_investments DOUBLE,
                sale_investments DOUBLE,
                other_investing_activities DOUBLE,
                net_cash_investing_activities DOUBLE,
                
                -- Financing Activities
                debt_issuance DOUBLE,
                debt_repayment DOUBLE,
                common_stock_issuance DOUBLE,
                stock_repurchase DOUBLE,
                dividends_paid DOUBLE,
                other_financing_activities DOUBLE,
                net_cash_financing_activities DOUBLE,
                
                -- Summary
                effect_of_exchange_rate DOUBLE,
                net_change_in_cash DOUBLE,
                cash_beginning_of_period DOUBLE,
                cash_end_of_period DOUBLE,
                
                -- Supplemental
                cash_paid_for_interest DOUBLE,
                cash_paid_for_taxes DOUBLE,

                -- True when 10-Q Q2/Q3 filing only provides YTD (cumulative) cash flows
                ytd_cashflow BOOLEAN DEFAULT FALSE,

                -- Primary Key Constraint
                PRIMARY KEY (ticker, filing_date, period_end_date)
            )
        """)
        self.conn.execute("""
            ALTER TABLE cash_flow_statements
            ADD COLUMN IF NOT EXISTS ytd_cashflow BOOLEAN DEFAULT FALSE
        """)
        
        # ====================================================================
        # EXTRACTION LOG TABLE - Track all extractions
        # ====================================================================
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS extraction_log_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_log (
                id INTEGER PRIMARY KEY DEFAULT nextval('extraction_log_seq'),
                ticker VARCHAR NOT NULL,
                filing_type VARCHAR NOT NULL,
                fiscal_year INTEGER,
                fiscal_quarter INTEGER,
                extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                statements_extracted VARCHAR,
                overall_coverage_pct DOUBLE,
                success BOOLEAN DEFAULT TRUE,
                error_message VARCHAR,
                execution_time_seconds DOUBLE
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS earnings_estimates (
                ticker VARCHAR NOT NULL,
                fiscal_date DATE NOT NULL,
                horizon VARCHAR NOT NULL,
                fetched_at TIMESTAMP NOT NULL,
                eps_avg DOUBLE,
                eps_high DOUBLE,
                eps_low DOUBLE,
                eps_count INTEGER,
                eps_avg_7d DOUBLE,
                eps_avg_30d DOUBLE,
                eps_avg_60d DOUBLE,
                eps_avg_90d DOUBLE,
                eps_rev_up_7d INTEGER,
                eps_rev_down_7d INTEGER,
                eps_rev_up_30d INTEGER,
                eps_rev_down_30d INTEGER,
                rev_avg DOUBLE,
                rev_high DOUBLE,
                rev_low DOUBLE,
                rev_count INTEGER,
                PRIMARY KEY (ticker, fiscal_date, horizon, fetched_at)
            )
        """)
        # Older DBs created this table with the column named "date" — dcf/estimates.py
        # (shared with historic_fundamentals.duckdb, which already uses "fiscal_date")
        # queries "fiscal_date" and 500s against the old name. Migrate in place.
        legacy_col = self.conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'earnings_estimates' AND column_name = 'date'"
        ).fetchone()
        if legacy_col:
            self.conn.execute('ALTER TABLE earnings_estimates RENAME COLUMN "date" TO "fiscal_date"')

        print("Database schema created/verified")

    # ========================================================================
    # INSERT METHODS
    # ========================================================================
    
    def insert_income_statement(self, df: pd.DataFrame) -> bool:
        """Insert or update income statement data. Raises on failure."""
        ticker = df.iloc[0]['Ticker']
        filing_date = pd.to_datetime(df.iloc[0]['Filing_Date']).date()
        period_end_date = pd.to_datetime(df.iloc[0]['Period_End_Date']).date()
        filing_type = df.iloc[0]['Filing_Type']
        fiscal_year = int(df.iloc[0]['Fiscal_Year']) if pd.notna(df.iloc[0]['Fiscal_Year']) else None
        fiscal_quarter = int(df.iloc[0]['Quarter']) if pd.notna(df.iloc[0]['Quarter']) else None
        period_type = df.iloc[0]['Period_Type']

        fields_extracted = int(df['Value'].notna().sum())
        total_fields = len(df)
        coverage_pct = (fields_extracted / total_fields) * 100

        data_dict = dict(zip(df['Field'], df['Value']))

        self.conn.execute("""
            INSERT OR REPLACE INTO income_statements (
                ticker, filing_date, period_end_date, filing_type, fiscal_year, fiscal_quarter,
                period_type, fields_extracted, total_fields, coverage_pct,
                revenue, cost_of_revenue, gross_profit,
                research_development, selling_general_admin, depreciation_amortization,
                restructuring_charges, other_operating_expenses, total_operating_expenses, operating_income,
                interest_income, interest_expense, equity_method_investments, investment_gains_losses,
                other_nonoperating_income, pretax_income, income_tax_expense, tax_rate,
                net_income_continuing_ops, discontinued_operations, net_income,
                net_income_attributable_to_nci, net_income_attributable_to_parent,
                other_comprehensive_income, comprehensive_income,
                basic_eps, diluted_eps, basic_shares, diluted_shares
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            ticker, filing_date, period_end_date, filing_type, fiscal_year, fiscal_quarter,
            period_type, fields_extracted, total_fields, coverage_pct,
            data_dict.get('revenue'), data_dict.get('cost_of_revenue'), data_dict.get('gross_profit'),
            data_dict.get('research_development'), data_dict.get('selling_general_admin'),
            data_dict.get('depreciation_amortization'), data_dict.get('restructuring_charges'),
            data_dict.get('other_operating_expenses'), data_dict.get('total_operating_expenses'),
            data_dict.get('operating_income'), data_dict.get('interest_income'),
            data_dict.get('interest_expense'), data_dict.get('equity_method_investments'),
            data_dict.get('investment_gains_losses'), data_dict.get('other_nonoperating_income'),
            data_dict.get('pretax_income'), data_dict.get('income_tax_expense'),
            data_dict.get('tax_rate'), data_dict.get('net_income_continuing_ops'),
            data_dict.get('discontinued_operations'), data_dict.get('net_income'),
            data_dict.get('net_income_attributable_to_nci'),
            data_dict.get('net_income_attributable_to_parent'),
            data_dict.get('other_comprehensive_income'), data_dict.get('comprehensive_income'),
            data_dict.get('basic_eps'), data_dict.get('diluted_eps'),
            data_dict.get('basic_shares'), data_dict.get('diluted_shares')
        ])

        self._update_company(ticker, filing_date)
        print(f"Inserted income statement: {ticker} {filing_type} {period_end_date} ({coverage_pct:.1f}% coverage)")
        return True
    
    def insert_balance_sheet(self, df: pd.DataFrame) -> bool:
        """Insert or update balance sheet data. Raises on failure."""
        ticker = df.iloc[0]['Ticker']
        filing_date = pd.to_datetime(df.iloc[0]['Filing_Date']).date()
        period_end_date = pd.to_datetime(df.iloc[0]['Period_End_Date']).date()
        filing_type = df.iloc[0]['Filing_Type']
        fiscal_year = int(df.iloc[0]['Fiscal_Year']) if pd.notna(df.iloc[0]['Fiscal_Year']) else None
        fiscal_quarter = int(df.iloc[0]['Quarter']) if pd.notna(df.iloc[0]['Quarter']) else None
        period_type = df.iloc[0]['Period_Type']

        fields_extracted = int(df['Value'].notna().sum())
        total_fields = len(df)
        coverage_pct = (fields_extracted / total_fields) * 100

        data_dict = dict(zip(df['Field'], df['Value']))

        self.conn.execute("""
            INSERT OR REPLACE INTO balance_sheets (
                ticker, filing_date, period_end_date, filing_type, fiscal_year, fiscal_quarter,
                period_type, fields_extracted, total_fields, coverage_pct,
                cash_and_equivalents, short_term_investments, accounts_receivable, inventory,
                prepaid_expenses, other_current_assets, total_current_assets,
                ppe_gross, accumulated_depreciation, ppe_net, goodwill, intangible_assets,
                long_term_investments, deferred_tax_assets, other_noncurrent_assets,
                total_noncurrent_assets, total_assets,
                accounts_payable, accrued_expenses, short_term_debt, current_portion_long_term_debt,
                deferred_revenue_current, other_current_liabilities, total_current_liabilities,
                long_term_debt, deferred_tax_liabilities, deferred_revenue_noncurrent,
                other_noncurrent_liabilities, total_noncurrent_liabilities, total_liabilities,
                common_stock, additional_paid_in_capital, retained_earnings, treasury_stock,
                accumulated_other_comprehensive_income, total_stockholders_equity,
                noncontrolling_interest, total_equity, total_liabilities_and_equity
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            ticker, filing_date, period_end_date, filing_type, fiscal_year, fiscal_quarter,
            period_type, fields_extracted, total_fields, coverage_pct,
            data_dict.get('cash_and_equivalents'), data_dict.get('short_term_investments'),
            data_dict.get('accounts_receivable'), data_dict.get('inventory'),
            data_dict.get('prepaid_expenses'), data_dict.get('other_current_assets'),
            data_dict.get('total_current_assets'), data_dict.get('ppe_gross'),
            data_dict.get('accumulated_depreciation'), data_dict.get('ppe_net'),
            data_dict.get('goodwill'), data_dict.get('intangible_assets'),
            data_dict.get('long_term_investments'), data_dict.get('deferred_tax_assets'),
            data_dict.get('other_noncurrent_assets'), data_dict.get('total_noncurrent_assets'),
            data_dict.get('total_assets'), data_dict.get('accounts_payable'),
            data_dict.get('accrued_expenses'), data_dict.get('short_term_debt'),
            data_dict.get('current_portion_long_term_debt'), data_dict.get('deferred_revenue_current'),
            data_dict.get('other_current_liabilities'), data_dict.get('total_current_liabilities'),
            data_dict.get('long_term_debt'), data_dict.get('deferred_tax_liabilities'),
            data_dict.get('deferred_revenue_noncurrent'), data_dict.get('other_noncurrent_liabilities'),
            data_dict.get('total_noncurrent_liabilities'), data_dict.get('total_liabilities'),
            data_dict.get('common_stock'), data_dict.get('additional_paid_in_capital'),
            data_dict.get('retained_earnings'), data_dict.get('treasury_stock'),
            data_dict.get('accumulated_other_comprehensive_income'),
            data_dict.get('total_stockholders_equity'), data_dict.get('noncontrolling_interest'),
            data_dict.get('total_equity'), data_dict.get('total_liabilities_and_equity')
        ])

        self._update_company(ticker, filing_date)
        print(f"Inserted balance sheet: {ticker} {filing_type} {period_end_date} ({coverage_pct:.1f}% coverage)")
        return True
    
    def insert_cash_flow(self, df: pd.DataFrame) -> bool:
        """Insert or update cash flow statement data. Raises on failure."""
        ticker = df.iloc[0]['Ticker']
        filing_date = pd.to_datetime(df.iloc[0]['Filing_Date']).date()
        period_end_date = pd.to_datetime(df.iloc[0]['Period_End_Date']).date()
        filing_type = df.iloc[0]['Filing_Type']
        fiscal_year = int(df.iloc[0]['Fiscal_Year']) if pd.notna(df.iloc[0]['Fiscal_Year']) else None
        fiscal_quarter = int(df.iloc[0]['Quarter']) if pd.notna(df.iloc[0]['Quarter']) else None
        period_type = df.iloc[0]['Period_Type']
        ytd_cashflow = bool(df.iloc[0]['YTD']) if 'YTD' in df.columns else False

        fields_extracted = int(df['Value'].notna().sum())
        total_fields = len(df)
        coverage_pct = (fields_extracted / total_fields) * 100

        data_dict = dict(zip(df['Field'], df['Value']))

        self.conn.execute("""
            INSERT OR REPLACE INTO cash_flow_statements (
                ticker, filing_date, period_end_date, filing_type, fiscal_year, fiscal_quarter,
                period_type, fields_extracted, total_fields, coverage_pct,
                net_income_starting_point, depreciation_amortization, stock_based_compensation,
                deferred_taxes, change_accounts_receivable, change_inventory, change_accounts_payable,
                change_accrued_expenses, change_deferred_revenue, other_operating_activities,
                net_cash_operating_activities, capital_expenditures, acquisitions,
                purchase_investments, sale_investments, other_investing_activities,
                net_cash_investing_activities, debt_issuance, debt_repayment,
                common_stock_issuance, stock_repurchase, dividends_paid, other_financing_activities,
                net_cash_financing_activities, effect_of_exchange_rate, net_change_in_cash,
                cash_beginning_of_period, cash_end_of_period, cash_paid_for_interest,
                cash_paid_for_taxes, ytd_cashflow
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            ticker, filing_date, period_end_date, filing_type, fiscal_year, fiscal_quarter,
            period_type, fields_extracted, total_fields, coverage_pct,
            data_dict.get('net_income_starting_point'), data_dict.get('depreciation_amortization'),
            data_dict.get('stock_based_compensation'), data_dict.get('deferred_taxes'),
            data_dict.get('change_accounts_receivable'), data_dict.get('change_inventory'),
            data_dict.get('change_accounts_payable'), data_dict.get('change_accrued_expenses'),
            data_dict.get('change_deferred_revenue'), data_dict.get('other_operating_activities'),
            data_dict.get('net_cash_operating_activities'), data_dict.get('capital_expenditures'),
            data_dict.get('acquisitions'), data_dict.get('purchase_investments'),
            data_dict.get('sale_investments'), data_dict.get('other_investing_activities'),
            data_dict.get('net_cash_investing_activities'), data_dict.get('debt_issuance'),
            data_dict.get('debt_repayment'), data_dict.get('common_stock_issuance'),
            data_dict.get('stock_repurchase'), data_dict.get('dividends_paid'),
            data_dict.get('other_financing_activities'), data_dict.get('net_cash_financing_activities'),
            data_dict.get('effect_of_exchange_rate'), data_dict.get('net_change_in_cash'),
            data_dict.get('cash_beginning_of_period'), data_dict.get('cash_end_of_period'),
            data_dict.get('cash_paid_for_interest'), data_dict.get('cash_paid_for_taxes'),
            ytd_cashflow,
        ])

        self._update_company(ticker, filing_date)
        print(f"Inserted cash flow: {ticker} {filing_type} {period_end_date} ({coverage_pct:.1f}% coverage)")
        return True
    
    def log_extraction(
        self,
        ticker: str,
        filing_type: str,
        fiscal_year: Optional[int],
        fiscal_quarter: Optional[int],
        statements_extracted: str,
        overall_coverage_pct: float,
        success: bool,
        error_message: Optional[str] = None,
        execution_time_seconds: Optional[float] = None,
    ):
        """Write one row to extraction_log per filing processed."""
        self.conn.execute("""
            INSERT INTO extraction_log (
                ticker, filing_type, fiscal_year, fiscal_quarter,
                statements_extracted, overall_coverage_pct, success,
                error_message, execution_time_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [ticker, filing_type, fiscal_year, fiscal_quarter,
              statements_extracted, overall_coverage_pct, success,
              error_message, execution_time_seconds])

    def insert_all_statements(
        self, 
        income_df: Optional[pd.DataFrame] = None,
        balance_df: Optional[pd.DataFrame] = None,
        cashflow_df: Optional[pd.DataFrame] = None
    ) -> Dict[str, bool]:
        """
        Insert all three statements at once
        
        Args:
            income_df: Income statement DataFrame
            balance_df: Balance sheet DataFrame
            cashflow_df: Cash flow DataFrame
        
        Returns:
            Dict with success status for each statement
        """
        results = {}
        
        if income_df is not None:
            results['income'] = self.insert_income_statement(income_df)
        
        if balance_df is not None:
            results['balance'] = self.insert_balance_sheet(balance_df)
        
        if cashflow_df is not None:
            results['cashflow'] = self.insert_cash_flow(cashflow_df)
        
        return results
    
    def _update_company(self, ticker: str, filing_date: date):
        """Update or create company record. total_filings is derived from actual rows."""
        total = self.conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT period_end_date FROM income_statements WHERE ticker = ?
                UNION
                SELECT period_end_date FROM balance_sheets WHERE ticker = ?
                UNION
                SELECT period_end_date FROM cash_flow_statements WHERE ticker = ?
            )
        """, [ticker, ticker, ticker]).fetchone()[0]

        existing = self.conn.execute(
            "SELECT ticker FROM companies WHERE ticker = ?", [ticker]
        ).fetchone()

        if existing:
            self.conn.execute("""
                UPDATE companies
                SET last_filing_date = GREATEST(last_filing_date, ?),
                    total_filings = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE ticker = ?
            """, [filing_date, total, ticker])
        else:
            self.conn.execute("""
                INSERT INTO companies (ticker, first_filing_date, last_filing_date, total_filings)
                VALUES (?, ?, ?, ?)
            """, [ticker, filing_date, filing_date, total])
    
    def filing_exists(self, ticker: str, period_end) -> bool:
        """Return True if all 3 statements are already stored for this ticker + period."""
        def _has(table: str) -> bool:
            return self.conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE ticker = ? AND period_end_date = ?",
                [ticker, period_end],
            ).fetchone()[0] > 0
        return _has("income_statements") and _has("balance_sheets") and _has("cash_flow_statements")

    # ========================================================================
    # QUERY METHODS
    # ========================================================================
    
    def get_company_statements(
        self, 
        ticker: str,
        statement_type: Optional[str] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Get all statements for a company
        
        Args:
            ticker: Company ticker
            statement_type: 'income', 'balance', 'cashflow', or None for all
        
        Returns:
            Dict of DataFrames for each statement type
        """
        results = {}
        
        if statement_type is None or statement_type == 'income':
            income = self.conn.execute("""
                SELECT * FROM income_statements 
                WHERE ticker = ? 
                ORDER BY period_end_date DESC
            """, [ticker]).df()
            results['income'] = income
        
        if statement_type is None or statement_type == 'balance':
            balance = self.conn.execute("""
                SELECT * FROM balance_sheets 
                WHERE ticker = ? 
                ORDER BY period_end_date DESC
            """, [ticker]).df()
            results['balance'] = balance
        
        if statement_type is None or statement_type == 'cashflow':
            cashflow = self.conn.execute("""
                SELECT * FROM cash_flow_statements 
                WHERE ticker = ? 
                ORDER BY period_end_date DESC
            """, [ticker]).df()
            results['cashflow'] = cashflow
        
        return results
    
    def get_time_series(
        self,
        ticker: str,
        statement_type: str,
        field_name: str,
        annual_only: bool = False
    ) -> pd.DataFrame:
        """
        Get time series for a specific field
        
        Args:
            ticker: Company ticker
            statement_type: 'income', 'balance', or 'cashflow'
            field_name: Field to retrieve
            annual_only: Only get annual (10-K) filings
        
        Returns:
            DataFrame with period_end_date and value
        """
        table_map = {
            'income': 'income_statements',
            'balance': 'balance_sheets',
            'cashflow': 'cash_flow_statements'
        }
        
        table = table_map.get(statement_type)
        if not table:
            raise ValueError(f"Invalid statement_type: {statement_type}")
        
        where_clause = "WHERE ticker = ?"
        params = [ticker]
        
        if annual_only:
            where_clause += " AND period_type = 'Annual'"
        
        df = self.conn.execute(f"""
            SELECT period_end_date, filing_date, fiscal_year, fiscal_quarter, 
                   {field_name} as value
            FROM {table}
            {where_clause}
            ORDER BY period_end_date ASC
        """, params).df()
        
        return df
    
    def query_companies(self) -> pd.DataFrame:
        """Get list of all companies in database"""
        return self.conn.execute("""
            SELECT * FROM companies 
            ORDER BY ticker
        """).df()
    
    def get_latest_filing(self, ticker: str, statement_type: str = 'income') -> pd.DataFrame:
        """Get the most recent filing for a company"""
        table_map = {
            'income': 'income_statements',
            'balance': 'balance_sheets',
            'cashflow': 'cash_flow_statements'
        }
        
        table = table_map.get(statement_type)
        return self.conn.execute(f"""
            SELECT * FROM {table}
            WHERE ticker = ?
            ORDER BY filing_date DESC
            LIMIT 1
        """, [ticker]).df()
    
    def get_data_quality_summary(self) -> pd.DataFrame:
        """Get data quality metrics across all companies"""
        return self.conn.execute("""
            SELECT 
                i.ticker,
                i.filing_type,
                i.period_end_date,
                i.coverage_pct as income_coverage,
                b.coverage_pct as balance_coverage,
                c.coverage_pct as cashflow_coverage,
                (i.coverage_pct + b.coverage_pct + c.coverage_pct) / 3 as avg_coverage
            FROM income_statements i
            LEFT JOIN balance_sheets b 
                ON i.ticker = b.ticker 
                AND i.filing_date = b.filing_date 
                AND i.period_end_date = b.period_end_date
            LEFT JOIN cash_flow_statements c 
                ON i.ticker = c.ticker 
                AND i.filing_date = c.filing_date 
                AND i.period_end_date = c.period_end_date
            ORDER BY i.ticker, i.period_end_date DESC
        """).df()
    
    # ========================================================================
    # EXPORT METHODS
    # ========================================================================
    
    def export_to_excel(self, ticker: str, output_path: str):
        """
        Export all statements for a company to Excel
        
        Args:
            ticker: Company ticker
            output_path: Path to save Excel file
        """
        statements = self.get_company_statements(ticker)
        
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            if not statements['income'].empty:
                statements['income'].to_excel(writer, sheet_name='Income Statements', index=False)
            
            if not statements['balance'].empty:
                statements['balance'].to_excel(writer, sheet_name='Balance Sheets', index=False)
            
            if not statements['cashflow'].empty:
                statements['cashflow'].to_excel(writer, sheet_name='Cash Flow', index=False)
        
        print(f"Exported {ticker} to {output_path}")
    
    def close(self):
        """Close database connection"""
        self.conn.close()
        print("Database connection closed")


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

if __name__ == "__main__":
    # Example usage
    db = FinancialStatementsDB('data/financial_statements.duckdb')
    
    print("\n" + "="*80)
    print("Database ready!")
    print("="*80)
    print("\nUsage:")
    print("  db.insert_income_statement(income_df)")
    print("  db.insert_balance_sheet(balance_df)")
    print("  db.insert_cash_flow(cashflow_df)")
    print("\nQuery:")
    print("  statements = db.get_company_statements('AAPL')")
    print("  revenue_ts = db.get_time_series('AAPL', 'income', 'revenue')")
    print("  companies = db.query_companies()")
    
    db.close()
