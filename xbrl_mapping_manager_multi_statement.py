"""
Production XBRL Mapping Manager - Multi-Statement Version
Handles: Income Statement, Balance Sheet, Cash Flow Statement

Hybrid approach: Python files for core mappings + DuckDB for AI discoveries and analytics

Usage:
    mapper = XBRLMappingManager('data/xbrl_mappings_multi.duckdb')
    
    # Get concepts for any statement
    concepts = await mapper.get_concepts_for_field('AAPL', 'income', 'revenue')
    concepts = await mapper.get_concepts_for_field('AAPL', 'balance', 'total_assets')
    concepts = await mapper.get_concepts_for_field('AAPL', 'cashflow', 'net_cash_operating_activities')
    
    # Log extractions
    await mapper.log_extraction('AAPL', 'balance', 'total_assets', 'Assets', 365000000000, True)
    
    # Get analytics across all statements
    stats = await mapper.get_overall_quality('AAPL')
"""

import duckdb
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple, Literal
import asyncio

# Import mapping files using recommended structure
# Option 1: If using package structure (xbrl_mappings/)
try:
    from xbrl_mappings import (
        INCOME_STATEMENT_MAPPING,
        BALANCE_SHEET_MAPPING,
        CASH_FLOW_MAPPING,
    )
except ImportError:
    # Option 2: If using flat file structure (backward compatible)
    from income_statement_xbrl_mapping import INCOME_STATEMENT_MAPPING
    
    try:
        from balance_sheet_xbrl_mapping import BALANCE_SHEET_MAPPING
    except ImportError:
        print("⚠ balance_sheet_xbrl_mapping.py not found")
        BALANCE_SHEET_MAPPING = None
    
    try:
        from cash_flow_xbrl_mapping import CASH_FLOW_MAPPING
    except ImportError:
        print("⚠ cash_flow_xbrl_mapping.py not found")
        CASH_FLOW_MAPPING = None


StatementType = Literal['income', 'balance', 'cashflow']


class XBRLMappingManager:
    """
    Production-grade XBRL concept mapping manager for all financial statements
    
    Features:
    - Supports income statement, balance sheet, cash flow statement
    - Fast lookups using DuckDB
    - AI discovery tracking per statement
    - Company-specific overrides
    - Cross-statement analytics
    - Auto-promotion of successful AI discoveries
    """
    
    def __init__(self, db_path: str = 'data/xbrl_mappings_multi.duckdb'):
        """Initialize the mapping manager"""
        self.db_path = db_path
        self.conn = None
        self._initialize_db()
    
    def _initialize_db(self):
        """Initialize DuckDB and create schema if needed"""
        self.conn = duckdb.connect(self.db_path)
        
        # Check if schema exists
        tables = self.conn.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'main'
        """).fetchall()
        
        if not tables:
            print("Creating multi-statement database schema...")
            self._create_schema()
            self._sync_core_mappings()
    
    def _create_schema(self):
        """Create database schema directly (DuckDB-compatible)"""
        
        # Table 1: Core Concept Mappings
        self.conn.execute("""
            CREATE TABLE core_concept_mappings (
                statement_type VARCHAR NOT NULL,
                field_name VARCHAR NOT NULL,
                concept VARCHAR NOT NULL,
                priority INTEGER NOT NULL DEFAULT 1,
                added_date DATE DEFAULT CURRENT_DATE,
                source VARCHAR DEFAULT 'manual',
                notes TEXT,
                PRIMARY KEY (statement_type, field_name, concept)
            )
        """)
        
        # Table 2: AI-Discovered Mappings
        self.conn.execute("""
            CREATE SEQUENCE ai_discovered_mappings_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE ai_discovered_mappings (
                id INTEGER PRIMARY KEY DEFAULT nextval('ai_discovered_mappings_seq'),
                statement_type VARCHAR NOT NULL,
                field_name VARCHAR NOT NULL,
                concept VARCHAR NOT NULL,
                discovered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confidence_score FLOAT DEFAULT 0.0,
                times_used INTEGER DEFAULT 0,
                times_failed INTEGER DEFAULT 0,
                promoted_to_core BOOLEAN DEFAULT FALSE,
                UNIQUE(statement_type, field_name, concept)
            )
        """)
        
        # Table 3: Company-Specific Overrides
        self.conn.execute("""
            CREATE TABLE company_specific_mappings (
                ticker VARCHAR NOT NULL,
                statement_type VARCHAR NOT NULL,
                field_name VARCHAR NOT NULL,
                concept VARCHAR NOT NULL,
                priority INTEGER DEFAULT 1,
                added_date DATE DEFAULT CURRENT_DATE,
                added_by VARCHAR,
                reason TEXT,
                PRIMARY KEY (ticker, statement_type, field_name, concept)
            )
        """)
        
        # Table 4: Extraction Log
        self.conn.execute("""
            CREATE SEQUENCE extraction_log_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE extraction_log (
                id INTEGER PRIMARY KEY DEFAULT nextval('extraction_log_seq'),
                ticker VARCHAR NOT NULL,
                statement_type VARCHAR NOT NULL,
                field_name VARCHAR NOT NULL,
                concept VARCHAR,
                value DOUBLE,
                filing_date DATE,
                period_end_date DATE,
                filing_type VARCHAR,
                extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source VARCHAR NOT NULL,
                success BOOLEAN NOT NULL,
                error_message TEXT
            )
        """)
        
        # Table 5: AI Discovery Queue
        self.conn.execute("""
            CREATE SEQUENCE ai_discovery_queue_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE ai_discovery_queue (
                id INTEGER PRIMARY KEY DEFAULT nextval('ai_discovery_queue_seq'),
                ticker VARCHAR NOT NULL,
                statement_type VARCHAR NOT NULL,
                field_name VARCHAR NOT NULL,
                concept VARCHAR NOT NULL,
                discovered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                filing_date DATE,
                period_end_date DATE,
                value DOUBLE,
                reviewed BOOLEAN DEFAULT FALSE,
                approved BOOLEAN DEFAULT FALSE,
                reviewer VARCHAR,
                review_date TIMESTAMP,
                review_notes TEXT
            )
        """)
        
        # Table 6: Concept Metadata
        self.conn.execute("""
            CREATE TABLE concept_metadata (
                concept VARCHAR PRIMARY KEY,
                concept_type VARCHAR,
                company_prefix VARCHAR,
                description TEXT,
                typical_statement VARCHAR,
                typical_field VARCHAR,
                first_seen_date DATE,
                last_seen_date DATE,
                occurrence_count INTEGER DEFAULT 1,
                companies_using_count INTEGER DEFAULT 1
            )
        """)
        
        # Table 7: Statement Coverage Stats
        self.conn.execute("""
            CREATE TABLE statement_coverage_stats (
                ticker VARCHAR NOT NULL,
                filing_date DATE NOT NULL,
                filing_type VARCHAR NOT NULL,
                statement_type VARCHAR NOT NULL,
                total_fields INTEGER NOT NULL,
                fields_found INTEGER NOT NULL,
                extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker, filing_date, statement_type)
            )
        """)
        
        # Create indexes
        self.conn.execute("CREATE INDEX idx_core_statement_field ON core_concept_mappings(statement_type, field_name, priority)")
        self.conn.execute("CREATE INDEX idx_ai_statement_field ON ai_discovered_mappings(statement_type, field_name)")
        self.conn.execute("CREATE INDEX idx_log_ticker_statement ON extraction_log(ticker, statement_type, extraction_date)")
        
        print("✓ Database schema created successfully")
    
    def _sync_core_mappings(self):
        """Sync Python mapping files to database"""
        print("Syncing core mappings from Python files...")
        
        count = 0
        
        # Sync Income Statement
        if INCOME_STATEMENT_MAPPING:
            for field_name, concepts in INCOME_STATEMENT_MAPPING.items():
                for priority, concept in enumerate(concepts, start=1):
                    self.conn.execute("""
                        INSERT OR IGNORE INTO core_concept_mappings 
                        (statement_type, field_name, concept, priority, source)
                        VALUES ('income', ?, ?, ?, 'manual')
                    """, [field_name, concept, priority])
                    count += 1
            print(f"  ✓ Synced income statement: {len(INCOME_STATEMENT_MAPPING)} fields")
        
        # Sync Balance Sheet (if available)
        if BALANCE_SHEET_MAPPING:
            for field_name, concepts in BALANCE_SHEET_MAPPING.items():
                for priority, concept in enumerate(concepts, start=1):
                    self.conn.execute("""
                        INSERT OR IGNORE INTO core_concept_mappings 
                        (statement_type, field_name, concept, priority, source)
                        VALUES ('balance', ?, ?, ?, 'manual')
                    """, [field_name, concept, priority])
                    count += 1
            print(f"  ✓ Synced balance sheet: {len(BALANCE_SHEET_MAPPING)} fields")
        else:
            print("  ⊘ Balance sheet mapping not available yet")
        
        # Sync Cash Flow (if available)
        if CASH_FLOW_MAPPING:
            for field_name, concepts in CASH_FLOW_MAPPING.items():
                for priority, concept in enumerate(concepts, start=1):
                    self.conn.execute("""
                        INSERT OR IGNORE INTO core_concept_mappings 
                        (statement_type, field_name, concept, priority, source)
                        VALUES ('cashflow', ?, ?, ?, 'manual')
                    """, [field_name, concept, priority])
                    count += 1
            print(f"  ✓ Synced cash flow: {len(CASH_FLOW_MAPPING)} fields")
        else:
            print("  ⊘ Cash flow mapping not available yet")
        
        self.conn.commit()
        
        print(f"✓ Total: {count} core concept mappings synced")
        
        # Show what's available
        summary = self.conn.execute("""
            SELECT statement_type, COUNT(DISTINCT field_name) as fields, COUNT(*) as concepts
            FROM core_concept_mappings
            GROUP BY statement_type
        """).fetchall()
        
        if summary:
            print("\nAvailable statements:")
            for stmt_type, fields, concepts in summary:
                print(f"  • {stmt_type}: {fields} fields, {concepts} concepts")
    
    async def get_concepts_for_field(
        self, 
        ticker: str, 
        statement_type: StatementType,
        field_name: str,
        include_ai: bool = True
    ) -> List[Tuple[str, str]]:
        """
        Get concepts to try for a field, in priority order
        
        Args:
            ticker: Company ticker
            statement_type: 'income', 'balance', or 'cashflow'
            field_name: Field to extract
            include_ai: Whether to include AI-discovered concepts
        
        Returns:
            List of (concept, source) tuples in priority order
        """
        concepts = []
        
        # 1. Company-specific overrides (highest priority)
        company_specific = self.conn.execute("""
            SELECT concept, 'company_specific' as source
            FROM company_specific_mappings
            WHERE ticker = ? AND statement_type = ? AND field_name = ?
            ORDER BY priority
        """, [ticker, statement_type, field_name]).fetchall()
        
        concepts.extend(company_specific)
        
        # 2. Core mappings
        core = self.conn.execute("""
            SELECT concept, 'core' as source
            FROM core_concept_mappings
            WHERE statement_type = ? AND field_name = ?
            ORDER BY priority
        """, [statement_type, field_name]).fetchall()
        
        concepts.extend(core)
        
        # 3. High-quality AI discoveries (optional)
        if include_ai:
            ai = self.conn.execute("""
                SELECT concept, 'ai_discovered' as source
                FROM ai_discovered_mappings
                WHERE statement_type = ? AND field_name = ?
                  AND CASE 
                      WHEN (times_used + times_failed) > 0 
                      THEN times_used::FLOAT / (times_used + times_failed)
                      ELSE 0.0 
                  END >= 0.80
                  AND times_used >= 3
                ORDER BY 
                  CASE 
                      WHEN (times_used + times_failed) > 0 
                      THEN times_used::FLOAT / (times_used + times_failed)
                      ELSE 0.0 
                  END DESC,
                  times_used DESC
                LIMIT 5
            """, [statement_type, field_name]).fetchall()
            
            concepts.extend(ai)
        
        return concepts
    
    async def log_extraction(
        self,
        ticker: str,
        statement_type: StatementType,
        field_name: str,
        concept: Optional[str],
        value: Optional[float],
        success: bool,
        filing_date: Optional[date] = None,
        period_end_date: Optional[date] = None,
        filing_type: str = '10-K',
        source: str = 'core',
        error_message: Optional[str] = None
    ):
        """Log an extraction attempt for analytics"""
        
        self.conn.execute("""
            INSERT INTO extraction_log 
            (ticker, statement_type, field_name, concept, value, filing_date, 
             period_end_date, filing_type, source, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [ticker, statement_type, field_name, concept, value, filing_date, 
              period_end_date, filing_type, source, success, error_message])
        
        # Update AI mapping statistics if it was an AI discovery
        if source == 'ai_discovered' and concept:
            if success:
                self.conn.execute("""
                    UPDATE ai_discovered_mappings
                    SET times_used = times_used + 1
                    WHERE statement_type = ? AND field_name = ? AND concept = ?
                """, [statement_type, field_name, concept])
            else:
                self.conn.execute("""
                    UPDATE ai_discovered_mappings
                    SET times_failed = times_failed + 1
                    WHERE statement_type = ? AND field_name = ? AND concept = ?
                """, [statement_type, field_name, concept])
        
        self.conn.commit()
    
    async def add_ai_discovery(
        self,
        ticker: str,
        statement_type: StatementType,
        field_name: str,
        concept: str,
        value: float,
        filing_date: Optional[date] = None,
        period_end_date: Optional[date] = None
    ):
        """Add a new AI discovery to the queue"""
        
        # Add to discovery queue
        self.conn.execute("""
            INSERT INTO ai_discovery_queue
            (ticker, statement_type, field_name, concept, filing_date, period_end_date, value)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [ticker, statement_type, field_name, concept, filing_date, period_end_date, value])
        
        # Add to AI mappings table (or update if exists)
        self.conn.execute("""
            INSERT INTO ai_discovered_mappings (statement_type, field_name, concept, times_used)
            VALUES (?, ?, ?, 1)
            ON CONFLICT (statement_type, field_name, concept) 
            DO UPDATE SET times_used = times_used + 1
        """, [statement_type, field_name, concept])
        
        self.conn.commit()
        
        print(f"  ✓ AI discovery logged: {concept} → {statement_type}.{field_name}")

    def get_prior_discoveries(
        self,
        statement_type: StatementType,
        min_occurrences: int = 1
    ) -> Dict[str, str]:
        """
        Query ai_discovery_queue for concept→field pairs from prior AI classifications.

        When a concept maps to multiple fields, takes the one with the most occurrences.

        Args:
            statement_type: 'income', 'balance', or 'cashflow'
            min_occurrences: Minimum number of prior occurrences for a mapping to qualify

        Returns:
            Dict of {concept: field_name} for trusted prior discoveries
        """
        rows = self.conn.execute("""
            WITH ranked AS (
                SELECT
                    concept,
                    field_name,
                    COUNT(*) as occurrence_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY concept
                        ORDER BY COUNT(*) DESC
                    ) as rn
                FROM ai_discovery_queue
                WHERE statement_type = ?
                GROUP BY concept, field_name
                HAVING COUNT(*) >= ?
            )
            SELECT concept, field_name
            FROM ranked
            WHERE rn = 1
        """, [statement_type, min_occurrences]).fetchall()

        result = {row[0]: row[1] for row in rows}
        if result:
            print(f"  DB lookup: found {len(result)} prior AI discoveries for {statement_type}")
        return result

    async def update_statement_coverage(
        self,
        ticker: str,
        filing_date: date,
        filing_type: str,
        statement_type: StatementType,
        fields_found: int,
        total_fields: int
    ):
        """Update coverage statistics for a statement"""
        
        self.conn.execute("""
            INSERT OR REPLACE INTO statement_coverage_stats
            (ticker, filing_date, filing_type, statement_type, total_fields, fields_found)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [ticker, filing_date, filing_type, statement_type, total_fields, fields_found])
        
        self.conn.commit()
    
    async def get_overall_quality(self, ticker: str) -> Dict:
        """Get overall data quality stats for a ticker across all statements"""
        
        stats = self.conn.execute("""
            SELECT 
                AVG((fields_found::FLOAT / total_fields) * 100) as overall_coverage,
                COUNT(DISTINCT statement_type) as statements_extracted,
                COUNT(*) as total_filings,
                MAX(filing_date) as latest_filing
            FROM statement_coverage_stats
            WHERE ticker = ?
        """, [ticker]).fetchone()
        
        # Per-statement breakdown
        per_statement = self.conn.execute("""
            SELECT 
                statement_type,
                AVG((fields_found::FLOAT / total_fields) * 100) as avg_coverage,
                COUNT(*) as filings_count
            FROM statement_coverage_stats
            WHERE ticker = ?
            GROUP BY statement_type
        """, [ticker]).fetchall()
        
        if stats and stats[0] is not None:
            return {
                'overall_coverage': stats[0],
                'statements_extracted': stats[1],
                'total_filings': stats[2],
                'latest_filing': stats[3],
                'by_statement': {
                    row[0]: {'avg_coverage': row[1], 'filings_count': row[2]}
                    for row in per_statement
                }
            }
        else:
            return {
                'overall_coverage': 0,
                'statements_extracted': 0,
                'total_filings': 0,
                'latest_filing': None,
                'by_statement': {}
            }
    
    async def get_promotion_candidates(
        self, 
        statement_type: Optional[StatementType] = None,
        limit: int = 10
    ) -> List[Dict]:
        """Get AI discoveries that should be promoted to core mapping"""
        
        # Calculate success_rate in query since DuckDB virtual columns are different
        query = """
            SELECT 
                statement_type,
                field_name,
                concept,
                times_used,
                CASE 
                    WHEN (times_used + times_failed) > 0 
                    THEN times_used::FLOAT / (times_used + times_failed)
                    ELSE 0.0 
                END as success_rate,
                confidence_score,
                discovered_date
            FROM ai_discovered_mappings
            WHERE times_used >= 10
              AND promoted_to_core = FALSE
        """
        
        params = []
        if statement_type:
            query += " AND statement_type = ?"
            params.append(statement_type)
        
        query += """
            AND CASE 
                WHEN (times_used + times_failed) > 0 
                THEN times_used::FLOAT / (times_used + times_failed)
                ELSE 0.0 
            END >= 0.90
            ORDER BY success_rate DESC, times_used DESC
            LIMIT ?
        """
        params.append(limit)
        
        candidates = self.conn.execute(query, params).fetchall()
        
        return [
            {
                'statement_type': c[0],
                'field_name': c[1],
                'concept': c[2],
                'times_used': c[3],
                'success_rate': c[4],
                'confidence_score': c[5],
                'discovered_date': c[6]
            }
            for c in candidates
        ]
    
    async def promote_ai_to_core(
        self, 
        statement_type: StatementType,
        field_name: str, 
        concept: str
    ):
        """Promote an AI discovery to core mapping"""
        
        # Get next priority for this field
        max_priority = self.conn.execute("""
            SELECT COALESCE(MAX(priority), 0) + 1
            FROM core_concept_mappings
            WHERE statement_type = ? AND field_name = ?
        """, [statement_type, field_name]).fetchone()[0]
        
        # Add to core mappings
        self.conn.execute("""
            INSERT OR IGNORE INTO core_concept_mappings
            (statement_type, field_name, concept, priority, source)
            VALUES (?, ?, ?, ?, 'promoted_from_ai')
        """, [statement_type, field_name, concept, max_priority])
        
        # Mark as promoted
        self.conn.execute("""
            UPDATE ai_discovered_mappings
            SET promoted_to_core = TRUE
            WHERE statement_type = ? AND field_name = ? AND concept = ?
        """, [statement_type, field_name, concept])
        
        self.conn.commit()
        
        print(f"✓ Promoted: {concept} → {statement_type}.{field_name} (priority {max_priority})")
    
    async def get_statement_health(self) -> Dict:
        """Get system-wide health metrics across all statements"""
        
        health = self.conn.execute("""
            SELECT 
                statement_type,
                COUNT(DISTINCT ticker) as companies,
                AVG((fields_found::FLOAT / total_fields) * 100) as avg_coverage,
                MIN((fields_found::FLOAT / total_fields) * 100) as min_coverage,
                MAX((fields_found::FLOAT / total_fields) * 100) as max_coverage,
                COUNT(*) as total_extractions
            FROM statement_coverage_stats
            WHERE filing_date >= CURRENT_DATE - INTERVAL 90 DAY
            GROUP BY statement_type
            ORDER BY statement_type
        """).fetchall()
        
        return {
            row[0]: {
                'companies': row[1],
                'avg_coverage': row[2],
                'min_coverage': row[3],
                'max_coverage': row[4],
                'total_extractions': row[5]
            }
            for row in health
        }
    
    async def add_company_override(
        self,
        ticker: str,
        statement_type: StatementType,
        field_name: str,
        concept: str,
        reason: str,
        added_by: str = 'system'
    ):
        """Add a company-specific mapping override"""
        
        self.conn.execute("""
            INSERT OR IGNORE INTO company_specific_mappings
            (ticker, statement_type, field_name, concept, added_by, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [ticker, statement_type, field_name, concept, added_by, reason])
        
        self.conn.commit()
        
        print(f"✓ Added company override: {ticker} - {concept} → {statement_type}.{field_name}")
    
    async def get_difficult_fields(
        self,
        statement_type: Optional[StatementType] = None,
        min_attempts: int = 10
    ) -> List[Dict]:
        """Get fields that are hardest to extract"""
        
        query = """
            SELECT 
                statement_type,
                field_name,
                COUNT(*) as extraction_attempts,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                (SUM(CASE WHEN success THEN 1 ELSE 0 END)::FLOAT / COUNT(*)) * 100 as success_rate_pct,
                COUNT(DISTINCT ticker) as companies_attempted
            FROM extraction_log
        """
        
        params = []
        conditions = [f"COUNT(*) >= {min_attempts}"]
        
        if statement_type:
            query += " WHERE statement_type = ?"
            params.append(statement_type)
        
        query += " GROUP BY statement_type, field_name"
        query += " HAVING " + " AND ".join(conditions)
        query += " ORDER BY success_rate_pct ASC"
        
        difficult = self.conn.execute(query, params).fetchall()
        
        return [
            {
                'statement_type': d[0],
                'field_name': d[1],
                'extraction_attempts': d[2],
                'successes': d[3],
                'success_rate_pct': d[4],
                'companies_attempted': d[5]
            }
            for d in difficult
        ]
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# =============================================================================
# USAGE EXAMPLES
# =============================================================================

async def example_usage():
    """Example of how to use the multi-statement mapping manager"""
    
    # Initialize manager
    mapper = XBRLMappingManager('data/xbrl_mappings_multi.duckdb')
    
    print("\n" + "="*80)
    print("MULTI-STATEMENT XBRL MAPPING MANAGER")
    print("="*80)
    
    # Example 1: Get concepts for different statements
    print("\n1. Getting concepts for different statements:")
    
    income_concepts = await mapper.get_concepts_for_field('AAPL', 'income', 'revenue')
    print(f"   Income - revenue: {len(income_concepts)} concepts")
    
    # balance_concepts = await mapper.get_concepts_for_field('AAPL', 'balance', 'total_assets')
    # print(f"   Balance - total_assets: {len(balance_concepts)} concepts")
    
    # cashflow_concepts = await mapper.get_concepts_for_field('AAPL', 'cashflow', 'net_cash_operating_activities')
    # print(f"   Cash Flow - operating cash: {len(cashflow_concepts)} concepts")
    
    # Example 2: Log extractions from all statements
    print("\n2. Logging multi-statement extraction:")
    
    await mapper.log_extraction(
        'AAPL', 'income', 'revenue', 'Revenues', 
        394328000000, True, date(2024, 11, 1), date(2024, 9, 28)
    )
    
    # await mapper.log_extraction(
    #     'AAPL', 'balance', 'total_assets', 'Assets',
    #     364980000000, True, date(2024, 11, 1), date(2024, 9, 28)
    # )
    
    # Example 3: Update coverage for each statement
    print("\n3. Updating statement coverage:")
    
    await mapper.update_statement_coverage(
        'AAPL', date(2024, 11, 1), '10-K', 'income', 25, 30
    )
    
    # await mapper.update_statement_coverage(
    #     'AAPL', date(2024, 11, 1), '10-K', 'balance', 35, 40
    # )
    
    # Example 4: Get overall quality
    print("\n4. Getting overall data quality for AAPL:")
    quality = await mapper.get_overall_quality('AAPL')
    print(f"   Overall coverage: {quality.get('overall_coverage', 0):.1f}%")
    print(f"   Statements extracted: {quality.get('statements_extracted', 0)}")
    
    for stmt_type, stats in quality.get('by_statement', {}).items():
        print(f"   {stmt_type}: {stats['avg_coverage']:.1f}% avg coverage")
    
    # Example 5: System health
    print("\n5. System-wide health metrics:")
    health = await mapper.get_statement_health()
    for stmt_type, metrics in health.items():
        print(f"   {stmt_type}:")
        print(f"     Companies: {metrics['companies']}")
        print(f"     Avg coverage: {metrics['avg_coverage']:.1f}%")
    
    # Close connection
    mapper.close()


if __name__ == "__main__":
    asyncio.run(example_usage())
