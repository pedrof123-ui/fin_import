"""
Balance Sheet Extractor
Downloads and extracts balance sheets from SEC EDGAR using comprehensive XBRL mapping
"""

import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd
from edgar import Company, set_identity
from typing import Optional, Literal
import asyncio

# Load environment variables
load_dotenv()

# Set SEC identity to avoid 403 blocks
sec_identity = os.getenv("SEC_ID")
if not sec_identity:
    raise ValueError("SEC_ID not found in .env file")

set_identity(sec_identity)

# Import the balance sheet mapping
try:
    from xbrl_mappings import BALANCE_SHEET_MAPPING
    print(f"✓ Loaded balance sheet XBRL mapping ({sum(len(v) for v in BALANCE_SHEET_MAPPING.values())} concepts, {len(BALANCE_SHEET_MAPPING)} fields)")
except ImportError as e:
    print("ERROR: Could not import from xbrl_mappings package")
    print("Please ensure xbrl_mappings/__init__.py exists and balance_sheet_xbrl_mapping.py is in the xbrl_mappings folder.")
    raise SystemExit(f"Import Error: {e}")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_date(date_str):
    """Parse a date string to datetime object."""
    if isinstance(date_str, str):
        try:
            return pd.to_datetime(date_str)
        except Exception:
            return None
    return date_str


def get_filing(
    ticker: str,
    filing_type: Literal["10-K", "10-Q"],
    year: Optional[int] = None,
    quarter: Optional[int] = None
):
    """
    Retrieve a specific SEC filing for a company.
    
    Args:
        ticker: Company ticker symbol
        filing_type: Either "10-K" (annual) or "10-Q" (quarterly)
        year: Fiscal year (if None, gets the most recent)
        quarter: Fiscal quarter (1-4, only for 10-Q)
        
    Returns:
        Filing object from edgartools
    """
    if filing_type == "10-Q" and quarter is not None:
        if not 1 <= quarter <= 4:
            raise ValueError("Quarter must be between 1 and 4")
    
    # Get company
    company = Company(ticker)
    print(f"✓ Retrieved company: {company.name} ({ticker})")
    
    # Get filings of the specified type
    filings = company.get_filings(form=filing_type)
    
    if filings.empty:
        raise FileNotFoundError(f"No {filing_type} filings found for {ticker}")
    
    # Filter by year if specified
    if year is not None:
        filings_filtered = []
        
        for f in filings:
            filing_date = parse_date(f.filing_date) if hasattr(f, 'filing_date') else None
            period_date = parse_date(f.period_of_report) if hasattr(f, 'period_of_report') else None
            
            filing_year_match = filing_date and filing_date.year == year
            period_year_match = period_date and period_date.year == year
            
            if filing_year_match or period_year_match:
                f._parsed_filing_date = filing_date
                f._parsed_period_date = period_date
                filings_filtered.append(f)
        
        if not filings_filtered:
            raise FileNotFoundError(f"No {filing_type} filings found for {ticker} in year {year}")
        
        # For 10-Q, filter by quarter
        if filing_type == "10-Q" and quarter is not None:
            quarter_filtered = []
            
            for f in filings_filtered:
                period_date = f._parsed_period_date
                if period_date:
                    file_quarter = ((period_date.month - 1) // 3) + 1
                    if file_quarter == quarter:
                        quarter_filtered.append(f)
            
            if not quarter_filtered:
                raise FileNotFoundError(f"No {filing_type} filings found for {ticker} in Q{quarter} {year}")
            
            filings_filtered = quarter_filtered
        
        filing = filings_filtered[0]
    else:
        filing = filings[0]
    
    filing_date = filing.filing_date if hasattr(filing, 'filing_date') else 'Unknown'
    period = filing.period_of_report if hasattr(filing, 'period_of_report') else 'Unknown'
    
    print(f"✓ Retrieved {filing_type} filing")
    print(f"  Filing Date: {filing_date}")
    print(f"  Period of Report: {period}")
    
    return filing


def extract_value_from_statement_df(
    statement_df: pd.DataFrame,
    field_name: str,
    year_column: str,
) -> tuple[Optional[float], Optional[str]]:
    """
    Extract a single value from the balance sheet DataFrame using static mapping only.

    Args:
        statement_df: DataFrame from xbrl.statements.balance_sheet().to_dataframe()
        field_name: Field to extract (e.g., 'total_assets', 'total_liabilities')
        year_column: Column name for the period (e.g., '2024-12-31')

    Returns:
        Tuple of (value, concept_used) or (None, None) if not found
    """
    # Get concepts to try for this field
    concepts = BALANCE_SHEET_MAPPING.get(field_name)

    if concepts is None:
        print(f"  ✗ ERROR: Field '{field_name}' not found in mapping!")
        return None, None

    # Filter to main items (no dimensional breakdowns)
    main_items = statement_df[
        (statement_df['dimension'] == False) &
        (statement_df['abstract'] == False)
    ]

    for concept in concepts:
        # Add us-gaap_ prefix if not company-specific
        if '_' in concept and not concept.startswith('us-gaap'):
            full_concept = concept
        else:
            full_concept = f"us-gaap_{concept}"

        # Look for this concept in the statement
        rows = main_items[main_items['concept'] == full_concept]

        if not rows.empty and year_column in rows.columns:
            value = rows.iloc[0][year_column]

            if pd.notna(value):
                return float(value), concept

    return None, None


async def extract_balance_sheet(
    filing,
    ticker: str,
    filing_type: str,
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    use_ai_fallback: bool = True,
) -> pd.DataFrame:
    """
    Extract balance sheet data from a SEC filing using comprehensive mapping.

    Uses two-pass extraction:
    - Pass 1: Static mapping lookup (fast, no AI)
    - Pass 2: Batch AI resolution for unfound fields (DB lookup + single batch call)

    Args:
        filing: Filing object from edgartools
        ticker: Company ticker symbol
        filing_type: Type of filing (10-K, 10-Q, 10-K/A, etc.)
        year: Fiscal year
        quarter: Fiscal quarter (1-4, only for 10-Q)
        use_ai_fallback: Whether to use AI agent for unmapped concepts (default: True)

    Returns:
        DataFrame with extracted line items and metadata
    """
    print("\n" + "="*80)
    print("EXTRACTING BALANCE SHEET")
    print("="*80)

    # Extract metadata from filing
    filing_date = filing.filing_date if hasattr(filing, 'filing_date') else None
    period_of_report = filing.period_of_report if hasattr(filing, 'period_of_report') else None
    form_type = filing.form if hasattr(filing, 'form') else filing_type

    # Determine if annual or quarterly
    is_annual = 'K' in form_type and 'Q' not in form_type
    period_type = 'Annual' if is_annual else 'Quarterly'

    # Calculate fiscal year from period_of_report if not provided
    if period_of_report and not year:
        period_date = parse_date(period_of_report)
        if period_date:
            year = period_date.year

    # Calculate quarter from period_of_report if quarterly and not provided
    if not is_annual and period_of_report and not quarter:
        period_date = parse_date(period_of_report)
        if period_date:
            quarter = ((period_date.month - 1) // 3) + 1

    # Get XBRL data
    try:
        xbrl = filing.xbrl()
        if xbrl is None:
            raise ValueError("Unable to extract XBRL data from filing")
    except Exception as e:
        raise ValueError(f"Error accessing XBRL data: {e}")

    # Get balance sheet
    try:
        balance_sheet = xbrl.statements.balance_sheet()

        if balance_sheet is None:
            alternative_names = [
                'CONDENSEDCONSOLIDATEDBALANCESHEETS',
                'CONSOLIDATEDBALANCESHEETS',
                'CONSOLIDATEDSTATEMENTSOFFINANCIALPOSITION',
                'StatementsOfFinancialPosition',
                'BalanceSheets'
            ]

            for name in alternative_names:
                try:
                    balance_sheet = xbrl.get_statement(name)
                    if balance_sheet is not None:
                        print(f"✓ Found balance sheet using alternative name: {name}")
                        break
                except:
                    continue

        if balance_sheet is None:
            raise ValueError("Balance sheet not available in XBRL data")

        balance_df = balance_sheet.to_dataframe()

        if balance_df.empty:
            raise ValueError("Balance sheet DataFrame is empty")

    except Exception as e:
        raise ValueError(f"Error retrieving balance sheet: {e}")

    # Find date columns (format: YYYY-MM-DD)
    date_columns = [
        col for col in balance_df.columns
        if isinstance(col, str) and len(col) == 10 and col[4] == '-' and col[7] == '-'
    ]

    if not date_columns:
        raise ValueError("No date columns found in balance sheet")

    most_recent_period = sorted(date_columns, reverse=True)[0]

    print(f"\n✓ Available periods: {', '.join(date_columns)}")
    print(f"✓ Using most recent period: {most_recent_period}")

    if use_ai_fallback:
        print(f"✓ AI fallback enabled (batch mode)")

    print(f"\nExtracting {len(BALANCE_SHEET_MAPPING)} line items...")

    # ==================================================================
    # PASS 1: Static mapping lookup
    # ==================================================================
    results = []
    found_count = 0
    unfound_fields = []

    for field_name in BALANCE_SHEET_MAPPING.keys():
        value, concept_used = extract_value_from_statement_df(
            balance_df,
            field_name,
            most_recent_period,
        )

        if value is not None:
            found_count += 1
            results.append({
                'Status': '✓',
                'Field': field_name,
                'Value': value,
                'Concept': concept_used
            })
        else:
            unfound_fields.append(field_name)
            results.append({
                'Status': '✗',
                'Field': field_name,
                'Value': None,
                'Concept': 'Not Found'
            })

    print(f"\n  Pass 1 (static): {found_count}/{len(BALANCE_SHEET_MAPPING)} fields found")

    # ==================================================================
    # PASS 2: Batch AI resolution for unfound fields
    # ==================================================================
    ai_discovered = []

    if use_ai_fallback and unfound_fields:
        print(f"  Pass 2 (AI): resolving {len(unfound_fields)} unfound fields...")

        mapping_manager = None
        try:
            from xbrl_mapping_manager_multi_statement import XBRLMappingManager
            mapping_manager = XBRLMappingManager('xbrl_mappings_multi.duckdb')
        except Exception as e:
            print(f"  ⚠ DB lookup unavailable: {e}")

        try:
            from extractors.ai_batch_helper import batch_ai_resolve_unfound_fields

            ai_results = await batch_ai_resolve_unfound_fields(
                statement_df=balance_df,
                mapping_dict=BALANCE_SHEET_MAPPING,
                unfound_fields=unfound_fields,
                year_column=most_recent_period,
                statement_type='balance',
                ticker=ticker,
                mapping_manager=mapping_manager,
            )

            for r in results:
                if r['Field'] in ai_results:
                    value, concept_used = ai_results[r['Field']]
                    r['Status'] = '✓'
                    r['Value'] = value
                    r['Concept'] = concept_used
                    found_count += 1

                    clean_concept = concept_used.replace(" (AI-discovered)", "")
                    ai_discovered.append({
                        'field': r['Field'],
                        'concept': clean_concept
                    })
        except Exception as e:
            print(f"  ⚠ Pass 2 failed: {e}")

        if mapping_manager:
            mapping_manager.close()

    # Create results DataFrame
    result_df = pd.DataFrame(results)

    result_df.insert(0, 'Ticker', ticker)
    result_df.insert(1, 'Fiscal_Year', year)
    result_df.insert(2, 'Period_End_Date', most_recent_period)
    result_df.insert(3, 'Filing_Date', filing_date)
    result_df.insert(4, 'Filing_Type', form_type)
    result_df.insert(5, 'Period_Type', period_type)
    result_df.insert(6, 'Quarter', quarter if not is_annual else None)

    data_quality = found_count / len(BALANCE_SHEET_MAPPING)

    print(f"\n✓ Extraction complete!")
    print(f"  Fields found: {found_count}/{len(BALANCE_SHEET_MAPPING)}")
    print(f"  Data quality score: {data_quality:.1%}")

    # Report AI-discovered concepts
    if ai_discovered:
        print(f"\n✓ AI discovered {len(ai_discovered)} new concept(s)!")
        print("\n" + "="*80)
        print("NEW CONCEPTS DISCOVERED BY AI")
        print("="*80)
        print("\nConsider adding these to balance_sheet_xbrl_mapping.py:")
        for item in ai_discovered:
            print(f"  '{item['concept']}',  # {item['field']}")
        print("\n" + "="*80)

        try:
            from xbrl_mapping_manager_multi_statement import XBRLMappingManager
            from datetime import date as date_type

            mapper = XBRLMappingManager('xbrl_mappings_multi.duckdb')

            filing_date_obj = date_type.fromisoformat(str(filing_date)) if filing_date else None
            period_date_obj = date_type.fromisoformat(str(most_recent_period)) if most_recent_period else None

            logged_count = 0
            for item in ai_discovered:
                field_row = result_df[result_df['Field'] == item['field']]
                value = field_row.iloc[0]['Value'] if not field_row.empty else None

                if value is not None:
                    try:
                        mapper.conn.execute("""
                            INSERT OR IGNORE INTO ai_discovery_queue
                            (ticker, statement_type, field_name, concept, value, filing_date, period_end_date)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, [ticker, 'balance', item['field'], item['concept'], float(value),
                              filing_date_obj, period_date_obj])
                        logged_count += 1
                    except Exception as e:
                        print(f"    ⚠ Failed to log {item['concept']}: {e}")

            if logged_count > 0:
                print(f"  ✓ Logged {logged_count} AI discoveries to database")

            mapper.close()

        except Exception as e:
            print(f"  ⚠ Failed to log to database: {e}")
            print(f"     (Discoveries still captured in output)")

    if data_quality < 0.5:
        print(f"  ⚠ WARNING: Low data quality (<50%). Check if correct filing was retrieved.")

    return result_df


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def main():
        # Example: Extract Apple's balance sheet
        filing = get_filing('AAPL', '10-K', 2024)
        df = await extract_balance_sheet(filing, 'AAPL', '10-K', use_ai_fallback=True)
        
        print("\n" + "="*80)
        print("BALANCE SHEET RESULTS")
        print("="*80)
        print(df.to_string())
    
    asyncio.run(main())
