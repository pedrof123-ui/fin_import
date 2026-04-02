-- ============================================================================
-- XBRL CONCEPT MAPPING DATABASE SCHEMA - MULTI-STATEMENT VERSION
-- For Production Use at Scale (1,000+ tickers)
-- Supports: Income Statement, Balance Sheet, Cash Flow Statement
-- ============================================================================

-- ============================================================================
-- TABLE 1: Core Concept Mappings (All Statements)
-- High-confidence, manually curated mappings (synced from Python files)
-- ============================================================================

CREATE TABLE core_concept_mappings (
    statement_type VARCHAR NOT NULL,       -- 'income', 'balance', 'cashflow'
    field_name VARCHAR NOT NULL,           -- e.g., 'revenue', 'total_assets', 'operating_cash_flow'
    concept VARCHAR NOT NULL,              -- e.g., 'Revenues', 'Assets', 'NetCashProvidedByOperatingActivities'
    priority INTEGER NOT NULL DEFAULT 1,   -- Try order (1 = try first)
    added_date DATE DEFAULT CURRENT_DATE,
    source VARCHAR DEFAULT 'manual',       -- 'manual', 'promoted_from_ai'
    notes TEXT,
    PRIMARY KEY (statement_type, field_name, concept)
);

-- Index for fast lookups during extraction
CREATE INDEX idx_core_statement_field ON core_concept_mappings(statement_type, field_name, priority);

-- ============================================================================
-- TABLE 2: AI-Discovered Mappings (All Statements)
-- Dynamic mappings discovered by AI, with confidence tracking
-- ============================================================================

CREATE TABLE ai_discovered_mappings (
    id INTEGER PRIMARY KEY,
    statement_type VARCHAR NOT NULL,       -- 'income', 'balance', 'cashflow'
    field_name VARCHAR NOT NULL,
    concept VARCHAR NOT NULL,
    discovered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confidence_score FLOAT DEFAULT 0.0,    -- 0.0 to 1.0
    times_used INTEGER DEFAULT 0,          -- How many times successfully used
    times_failed INTEGER DEFAULT 0,        -- How many times failed
    success_rate FLOAT GENERATED ALWAYS AS (
        CASE 
            WHEN (times_used + times_failed) > 0 
            THEN times_used::FLOAT / (times_used + times_failed)
            ELSE 0.0 
        END
    ) VIRTUAL,
    promoted_to_core BOOLEAN DEFAULT FALSE,
    UNIQUE(statement_type, field_name, concept)
);

CREATE INDEX idx_ai_statement_field_success ON ai_discovered_mappings(statement_type, field_name, success_rate DESC);

-- ============================================================================
-- TABLE 3: Company-Specific Overrides (All Statements)
-- Special mappings for companies that use non-standard concepts
-- ============================================================================

CREATE TABLE company_specific_mappings (
    ticker VARCHAR NOT NULL,
    statement_type VARCHAR NOT NULL,       -- 'income', 'balance', 'cashflow'
    field_name VARCHAR NOT NULL,
    concept VARCHAR NOT NULL,
    priority INTEGER DEFAULT 1,
    added_date DATE DEFAULT CURRENT_DATE,
    added_by VARCHAR,                      -- Who added it
    reason TEXT,                           -- Why this override is needed
    PRIMARY KEY (ticker, statement_type, field_name, concept)
);

CREATE INDEX idx_company_statement_field ON company_specific_mappings(ticker, statement_type, field_name);

-- ============================================================================
-- TABLE 4: Extraction Usage Log (All Statements)
-- Tracks every extraction attempt for analytics
-- ============================================================================

CREATE TABLE extraction_log (
    id INTEGER PRIMARY KEY,
    ticker VARCHAR NOT NULL,
    statement_type VARCHAR NOT NULL,       -- 'income', 'balance', 'cashflow'
    field_name VARCHAR NOT NULL,
    concept VARCHAR,                       -- NULL if not found
    value DOUBLE,                          -- Extracted value
    filing_date DATE,
    period_end_date DATE,
    filing_type VARCHAR,                   -- '10-K', '10-Q'
    extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source VARCHAR NOT NULL,               -- 'core_mapping', 'ai_discovered', 'company_specific'
    success BOOLEAN NOT NULL,              -- Was value found?
    error_message TEXT                     -- If failed, why?
);

-- Indexes for common queries
CREATE INDEX idx_log_ticker_statement_date ON extraction_log(ticker, statement_type, extraction_date);
CREATE INDEX idx_log_statement_field_success ON extraction_log(statement_type, field_name, success);
CREATE INDEX idx_log_concept ON extraction_log(concept) WHERE concept IS NOT NULL;

-- ============================================================================
-- TABLE 5: AI Discovery Queue (All Statements)
-- Raw AI discoveries before validation
-- ============================================================================

CREATE TABLE ai_discovery_queue (
    id INTEGER PRIMARY KEY,
    ticker VARCHAR NOT NULL,
    statement_type VARCHAR NOT NULL,       -- 'income', 'balance', 'cashflow'
    field_name VARCHAR NOT NULL,
    concept VARCHAR NOT NULL,
    discovered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    filing_date DATE,
    period_end_date DATE,
    value DOUBLE,                          -- The value that was extracted
    reviewed BOOLEAN DEFAULT FALSE,
    approved BOOLEAN DEFAULT FALSE,
    reviewer VARCHAR,
    review_date TIMESTAMP,
    review_notes TEXT
);

CREATE INDEX idx_queue_statement_unreviewed ON ai_discovery_queue(statement_type, reviewed) WHERE NOT reviewed;

-- ============================================================================
-- TABLE 6: Concept Metadata
-- Information about XBRL concepts themselves
-- ============================================================================

CREATE TABLE concept_metadata (
    concept VARCHAR PRIMARY KEY,
    concept_type VARCHAR,                  -- 'us-gaap', 'company-specific'
    company_prefix VARCHAR,                -- 'tsla', 'gm', 'aapl', etc.
    description TEXT,
    typical_statement VARCHAR,             -- 'income', 'balance', 'cashflow'
    typical_field VARCHAR,                 -- Which field is this usually mapped to?
    first_seen_date DATE,
    last_seen_date DATE,
    occurrence_count INTEGER DEFAULT 1,    -- How many filings have this?
    companies_using_count INTEGER DEFAULT 1 -- How many companies use this?
);

CREATE INDEX idx_concept_type ON concept_metadata(concept_type);
CREATE INDEX idx_concept_statement ON concept_metadata(typical_statement);
CREATE INDEX idx_concept_prefix ON concept_metadata(company_prefix) WHERE company_prefix IS NOT NULL;

-- ============================================================================
-- TABLE 7: Statement Coverage Statistics
-- Track data quality per ticker per statement
-- ============================================================================

CREATE TABLE statement_coverage_stats (
    ticker VARCHAR NOT NULL,
    filing_date DATE NOT NULL,
    filing_type VARCHAR NOT NULL,
    statement_type VARCHAR NOT NULL,       -- 'income', 'balance', 'cashflow'
    total_fields INTEGER NOT NULL,         -- Expected fields for this statement
    fields_found INTEGER NOT NULL,         -- How many were found
    coverage_pct FLOAT GENERATED ALWAYS AS (
        (fields_found::FLOAT / total_fields) * 100
    ) VIRTUAL,
    extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, filing_date, statement_type)
);

CREATE INDEX idx_coverage_ticker_statement ON statement_coverage_stats(ticker, statement_type, filing_date DESC);
CREATE INDEX idx_coverage_quality ON statement_coverage_stats(coverage_pct DESC);

-- ============================================================================
-- TABLE 8: Field Definitions
-- Central registry of all fields we extract from all statements
-- ============================================================================

CREATE TABLE field_definitions (
    statement_type VARCHAR NOT NULL,       -- 'income', 'balance', 'cashflow'
    field_name VARCHAR NOT NULL,
    display_name VARCHAR NOT NULL,         -- Human-readable name
    description TEXT,
    data_type VARCHAR DEFAULT 'numeric',   -- 'numeric', 'percentage', 'shares', 'text'
    is_required BOOLEAN DEFAULT FALSE,     -- Is this a critical field?
    calculation_formula TEXT,              -- e.g., 'gross_profit = revenue - cost_of_revenue'
    sort_order INTEGER,                    -- Display order in output
    category VARCHAR,                      -- e.g., 'revenue', 'assets', 'liabilities', 'operating_activities'
    PRIMARY KEY (statement_type, field_name)
);

-- ============================================================================
-- TABLE 9: Statement Relationships
-- Track relationships between statements (e.g., net income flows to cash flow)
-- ============================================================================

CREATE TABLE statement_relationships (
    id INTEGER PRIMARY KEY,
    source_statement VARCHAR NOT NULL,     -- 'income'
    source_field VARCHAR NOT NULL,         -- 'net_income'
    target_statement VARCHAR NOT NULL,     -- 'cashflow'
    target_field VARCHAR NOT NULL,         -- 'net_income_starting_point'
    relationship_type VARCHAR NOT NULL,    -- 'equals', 'flows_to', 'reconciles'
    description TEXT,
    UNIQUE(source_statement, source_field, target_statement, target_field)
);

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- View: Best performing AI discoveries per statement (candidates for promotion)
CREATE VIEW ai_promotion_candidates AS
SELECT 
    statement_type,
    field_name,
    concept,
    times_used,
    success_rate,
    confidence_score,
    discovered_date
FROM ai_discovered_mappings
WHERE success_rate >= 0.90           -- 90%+ success rate
  AND times_used >= 10               -- Used at least 10 times
  AND NOT promoted_to_core           -- Not already promoted
ORDER BY statement_type, success_rate DESC, times_used DESC;

-- View: Company outliers per statement type
CREATE VIEW company_outliers_by_statement AS
SELECT 
    ticker,
    statement_type,
    AVG(coverage_pct) as avg_coverage,
    COUNT(*) as filings_count,
    MAX(filing_date) as latest_filing
FROM statement_coverage_stats
GROUP BY ticker, statement_type
HAVING AVG(coverage_pct) < 70.0      -- Less than 70% average coverage
ORDER BY statement_type, avg_coverage ASC;

-- View: Overall company data quality (across all statements)
CREATE VIEW company_overall_quality AS
SELECT 
    ticker,
    AVG(coverage_pct) as overall_coverage,
    COUNT(DISTINCT statement_type) as statements_extracted,
    COUNT(*) as total_filings,
    MAX(filing_date) as latest_filing
FROM statement_coverage_stats
GROUP BY ticker
ORDER BY overall_coverage DESC;

-- View: Concept usage by statement type
CREATE VIEW concept_usage_by_statement AS
SELECT 
    statement_type,
    concept,
    field_name,
    COUNT(DISTINCT ticker) as companies_using,
    COUNT(*) as total_uses,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_uses,
    (SUM(CASE WHEN success THEN 1 ELSE 0 END)::FLOAT / COUNT(*)) * 100 as success_rate_pct
FROM extraction_log
WHERE concept IS NOT NULL
GROUP BY statement_type, concept, field_name
ORDER BY statement_type, companies_using DESC, total_uses DESC;

-- View: Most difficult fields to extract per statement
CREATE VIEW difficult_fields_by_statement AS
SELECT 
    statement_type,
    field_name,
    COUNT(*) as extraction_attempts,
    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
    (SUM(CASE WHEN success THEN 1 ELSE 0 END)::FLOAT / COUNT(*)) * 100 as success_rate_pct,
    COUNT(DISTINCT ticker) as companies_attempted
FROM extraction_log
GROUP BY statement_type, field_name
HAVING COUNT(*) >= 10
ORDER BY statement_type, success_rate_pct ASC;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to get mapping for a field (tries all sources in priority order)
CREATE MACRO get_concept_mapping(ticker_param VARCHAR, statement_param VARCHAR, field_param VARCHAR) AS (
    -- 1. Try company-specific first
    SELECT concept, 1 as source_priority, 'company_specific' as source, priority
    FROM company_specific_mappings
    WHERE ticker = ticker_param 
      AND statement_type = statement_param 
      AND field_name = field_param
    
    UNION ALL
    
    -- 2. Try core mappings second
    SELECT concept, 2 as source_priority, 'core' as source, priority
    FROM core_concept_mappings
    WHERE statement_type = statement_param 
      AND field_name = field_param
    
    UNION ALL
    
    -- 3. Try AI-discovered with good track record
    SELECT concept, 3 as source_priority, 'ai_discovered' as source, 
           (success_rate * times_used) as priority
    FROM ai_discovered_mappings
    WHERE statement_type = statement_param 
      AND field_name = field_param
      AND success_rate >= 0.80
      AND times_used >= 3
    
    ORDER BY source_priority, priority DESC
);

-- ============================================================================
-- INITIAL FIELD DEFINITIONS
-- ============================================================================

-- Income Statement Fields (30 fields)
INSERT INTO field_definitions (statement_type, field_name, display_name, category, sort_order, is_required) VALUES
    ('income', 'revenue', 'Revenue', 'revenue', 1, TRUE),
    ('income', 'cost_of_revenue', 'Cost of Revenue', 'revenue', 2, TRUE),
    ('income', 'gross_profit', 'Gross Profit', 'revenue', 3, TRUE),
    ('income', 'research_development', 'Research & Development', 'operating_expenses', 4, FALSE),
    ('income', 'selling_general_admin', 'Selling, General & Administrative', 'operating_expenses', 5, TRUE),
    ('income', 'depreciation_amortization', 'Depreciation & Amortization', 'operating_expenses', 6, FALSE),
    ('income', 'operating_income', 'Operating Income', 'operating_income', 10, TRUE),
    ('income', 'interest_expense', 'Interest Expense', 'non_operating', 11, FALSE),
    ('income', 'pretax_income', 'Income Before Tax', 'income', 15, TRUE),
    ('income', 'income_tax_expense', 'Income Tax Expense', 'income', 16, TRUE),
    ('income', 'net_income', 'Net Income', 'income', 20, TRUE),
    ('income', 'basic_eps', 'Basic EPS', 'per_share', 23, TRUE),
    ('income', 'diluted_eps', 'Diluted EPS', 'per_share', 24, TRUE);

-- Balance Sheet Fields (40+ fields)
INSERT INTO field_definitions (statement_type, field_name, display_name, category, sort_order, is_required) VALUES
    -- Current Assets
    ('balance', 'cash_and_equivalents', 'Cash & Cash Equivalents', 'current_assets', 1, TRUE),
    ('balance', 'short_term_investments', 'Short-term Investments', 'current_assets', 2, FALSE),
    ('balance', 'accounts_receivable', 'Accounts Receivable', 'current_assets', 3, TRUE),
    ('balance', 'inventory', 'Inventory', 'current_assets', 4, FALSE),
    ('balance', 'prepaid_expenses', 'Prepaid Expenses', 'current_assets', 5, FALSE),
    ('balance', 'other_current_assets', 'Other Current Assets', 'current_assets', 6, FALSE),
    ('balance', 'total_current_assets', 'Total Current Assets', 'current_assets', 10, TRUE),
    
    -- Long-term Assets
    ('balance', 'ppe_gross', 'Property, Plant & Equipment (Gross)', 'noncurrent_assets', 11, FALSE),
    ('balance', 'accumulated_depreciation', 'Accumulated Depreciation', 'noncurrent_assets', 12, FALSE),
    ('balance', 'ppe_net', 'Property, Plant & Equipment (Net)', 'noncurrent_assets', 13, TRUE),
    ('balance', 'goodwill', 'Goodwill', 'noncurrent_assets', 14, FALSE),
    ('balance', 'intangible_assets', 'Intangible Assets', 'noncurrent_assets', 15, FALSE),
    ('balance', 'long_term_investments', 'Long-term Investments', 'noncurrent_assets', 16, FALSE),
    ('balance', 'other_noncurrent_assets', 'Other Non-current Assets', 'noncurrent_assets', 17, FALSE),
    ('balance', 'total_noncurrent_assets', 'Total Non-current Assets', 'noncurrent_assets', 20, TRUE),
    ('balance', 'total_assets', 'Total Assets', 'assets', 30, TRUE),
    
    -- Current Liabilities
    ('balance', 'accounts_payable', 'Accounts Payable', 'current_liabilities', 31, TRUE),
    ('balance', 'short_term_debt', 'Short-term Debt', 'current_liabilities', 32, FALSE),
    ('balance', 'current_portion_long_term_debt', 'Current Portion of Long-term Debt', 'current_liabilities', 33, FALSE),
    ('balance', 'accrued_expenses', 'Accrued Expenses', 'current_liabilities', 34, FALSE),
    ('balance', 'deferred_revenue_current', 'Deferred Revenue (Current)', 'current_liabilities', 35, FALSE),
    ('balance', 'other_current_liabilities', 'Other Current Liabilities', 'current_liabilities', 36, FALSE),
    ('balance', 'total_current_liabilities', 'Total Current Liabilities', 'current_liabilities', 40, TRUE),
    
    -- Long-term Liabilities
    ('balance', 'long_term_debt', 'Long-term Debt', 'noncurrent_liabilities', 41, TRUE),
    ('balance', 'deferred_tax_liabilities', 'Deferred Tax Liabilities', 'noncurrent_liabilities', 42, FALSE),
    ('balance', 'deferred_revenue_noncurrent', 'Deferred Revenue (Non-current)', 'noncurrent_liabilities', 43, FALSE),
    ('balance', 'other_noncurrent_liabilities', 'Other Non-current Liabilities', 'noncurrent_liabilities', 44, FALSE),
    ('balance', 'total_noncurrent_liabilities', 'Total Non-current Liabilities', 'noncurrent_liabilities', 50, TRUE),
    ('balance', 'total_liabilities', 'Total Liabilities', 'liabilities', 60, TRUE),
    
    -- Equity
    ('balance', 'common_stock', 'Common Stock', 'equity', 61, TRUE),
    ('balance', 'additional_paid_in_capital', 'Additional Paid-in Capital', 'equity', 62, FALSE),
    ('balance', 'retained_earnings', 'Retained Earnings', 'equity', 63, TRUE),
    ('balance', 'treasury_stock', 'Treasury Stock', 'equity', 64, FALSE),
    ('balance', 'accumulated_other_comprehensive_income', 'Accumulated OCI', 'equity', 65, FALSE),
    ('balance', 'total_stockholders_equity', 'Total Stockholders Equity', 'equity', 70, TRUE),
    ('balance', 'noncontrolling_interest', 'Non-controlling Interest', 'equity', 71, FALSE),
    ('balance', 'total_equity', 'Total Equity', 'equity', 80, TRUE),
    ('balance', 'total_liabilities_and_equity', 'Total Liabilities & Equity', 'liabilities_equity', 90, TRUE);

-- Cash Flow Statement Fields (30+ fields)
INSERT INTO field_definitions (statement_type, field_name, display_name, category, sort_order, is_required) VALUES
    -- Operating Activities
    ('cashflow', 'net_income_starting_point', 'Net Income (Starting Point)', 'operating_activities', 1, TRUE),
    ('cashflow', 'depreciation_amortization', 'Depreciation & Amortization', 'operating_activities', 2, TRUE),
    ('cashflow', 'stock_based_compensation', 'Stock-based Compensation', 'operating_activities', 3, FALSE),
    ('cashflow', 'deferred_income_taxes', 'Deferred Income Taxes', 'operating_activities', 4, FALSE),
    ('cashflow', 'change_accounts_receivable', 'Change in Accounts Receivable', 'operating_activities', 5, FALSE),
    ('cashflow', 'change_inventory', 'Change in Inventory', 'operating_activities', 6, FALSE),
    ('cashflow', 'change_accounts_payable', 'Change in Accounts Payable', 'operating_activities', 7, FALSE),
    ('cashflow', 'change_accrued_expenses', 'Change in Accrued Expenses', 'operating_activities', 8, FALSE),
    ('cashflow', 'other_operating_activities', 'Other Operating Activities', 'operating_activities', 9, FALSE),
    ('cashflow', 'net_cash_operating_activities', 'Net Cash from Operating Activities', 'operating_activities', 10, TRUE),
    
    -- Investing Activities
    ('cashflow', 'capital_expenditures', 'Capital Expenditures', 'investing_activities', 11, TRUE),
    ('cashflow', 'acquisitions', 'Acquisitions', 'investing_activities', 12, FALSE),
    ('cashflow', 'purchases_investments', 'Purchases of Investments', 'investing_activities', 13, FALSE),
    ('cashflow', 'sales_investments', 'Sales/Maturities of Investments', 'investing_activities', 14, FALSE),
    ('cashflow', 'other_investing_activities', 'Other Investing Activities', 'investing_activities', 15, FALSE),
    ('cashflow', 'net_cash_investing_activities', 'Net Cash from Investing Activities', 'investing_activities', 20, TRUE),
    
    -- Financing Activities
    ('cashflow', 'debt_issuance', 'Debt Issuance', 'financing_activities', 21, FALSE),
    ('cashflow', 'debt_repayment', 'Debt Repayment', 'financing_activities', 22, FALSE),
    ('cashflow', 'stock_issuance', 'Stock Issuance', 'financing_activities', 23, FALSE),
    ('cashflow', 'stock_repurchase', 'Stock Repurchase', 'financing_activities', 24, FALSE),
    ('cashflow', 'dividends_paid', 'Dividends Paid', 'financing_activities', 25, FALSE),
    ('cashflow', 'other_financing_activities', 'Other Financing Activities', 'financing_activities', 26, FALSE),
    ('cashflow', 'net_cash_financing_activities', 'Net Cash from Financing Activities', 'financing_activities', 30, TRUE),
    
    -- Summary
    ('cashflow', 'net_change_in_cash', 'Net Change in Cash', 'summary', 40, TRUE),
    ('cashflow', 'cash_beginning_of_period', 'Cash at Beginning of Period', 'summary', 41, TRUE),
    ('cashflow', 'cash_end_of_period', 'Cash at End of Period', 'summary', 42, TRUE),
    
    -- Supplemental
    ('cashflow', 'cash_paid_for_interest', 'Cash Paid for Interest', 'supplemental', 50, FALSE),
    ('cashflow', 'cash_paid_for_taxes', 'Cash Paid for Taxes', 'supplemental', 51, FALSE);

-- ============================================================================
-- STATEMENT RELATIONSHIPS
-- ============================================================================

-- Net Income flows from Income Statement to Cash Flow Statement
INSERT INTO statement_relationships (source_statement, source_field, target_statement, target_field, relationship_type, description) VALUES
    ('income', 'net_income', 'cashflow', 'net_income_starting_point', 'equals', 'Net income is the starting point for operating cash flow'),
    ('balance', 'cash_and_equivalents', 'cashflow', 'cash_end_of_period', 'equals', 'Ending cash on balance sheet equals ending cash on cash flow statement'),
    ('income', 'depreciation_amortization', 'cashflow', 'depreciation_amortization', 'flows_to', 'D&A from income statement is added back in cash flow');

-- ============================================================================
-- MAINTENANCE QUERIES
-- ============================================================================

-- Promote AI discoveries to core mapping (per statement)
/*
INSERT INTO core_concept_mappings (statement_type, field_name, concept, source)
SELECT statement_type, field_name, concept, 'promoted_from_ai'
FROM ai_promotion_candidates
WHERE statement_type = 'balance'
LIMIT 10;

UPDATE ai_discovered_mappings
SET promoted_to_core = TRUE
WHERE (statement_type, field_name, concept) IN (
    SELECT statement_type, field_name, concept 
    FROM ai_promotion_candidates 
    WHERE statement_type = 'balance'
    LIMIT 10
);
*/

-- Get overall system health
/*
SELECT 
    statement_type,
    COUNT(DISTINCT ticker) as companies,
    AVG(coverage_pct) as avg_coverage,
    MIN(coverage_pct) as min_coverage,
    MAX(coverage_pct) as max_coverage
FROM statement_coverage_stats
WHERE filing_date >= CURRENT_DATE - INTERVAL 90 DAY
GROUP BY statement_type
ORDER BY statement_type;
*/
