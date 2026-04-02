"""
Cash Flow Statement Extractor
Downloads and extracts cash flow statements from SEC EDGAR using comprehensive XBRL mapping
"""

import pandas as pd
from typing import Optional, Literal
import asyncio

from .filing import get_filing, parse_date

try:
    from xbrl_mappings import CASH_FLOW_MAPPING
    print(f"Loaded cash flow XBRL mapping ({sum(len(v) for v in CASH_FLOW_MAPPING.values())} concepts, {len(CASH_FLOW_MAPPING)} fields)")
except ImportError as e:
    print("ERROR: Could not import from xbrl_mappings package")
    print("Please ensure xbrl_mappings/__init__.py exists and cash_flow_xbrl_mapping.py is in the xbrl_mappings folder.")
    raise SystemExit(f"Import Error: {e}")



def extract_value_from_statement_df(
    statement_df: pd.DataFrame,
    field_name: str,
    year_column: str,
) -> tuple[Optional[float], Optional[str]]:
    """
    Extract a single value from the cash flow DataFrame using static mapping only.

    Args:
        statement_df: DataFrame from xbrl.statements.cash_flows().to_dataframe()
        field_name: Field to extract (e.g., 'net_cash_operating_activities')
        year_column: Column name for the period (e.g., '2024-12-31')

    Returns:
        Tuple of (value, concept_used) or (None, None) if not found
    """
    # Get concepts to try for this field
    concepts = CASH_FLOW_MAPPING.get(field_name)

    if concepts is None:
        print(f"  ERROR: Field '{field_name}' not found in mapping!")
        return None, None

    # Filter to main items (no dimensional breakdowns)
    main_items = statement_df[
        (statement_df['dimension'] == False) &
        (statement_df['abstract'] == False)
    ].copy()

    # Strip namespace prefix (e.g. us-gaap_, dei_, apo_) before matching
    main_items['bare_concept'] = main_items['concept'].apply(
        lambda c: c.split('_', 1)[1] if '_' in c else c
    )

    aggregation_fields = {
        'other_operating_activities',
        'other_investing_activities',
        'other_financing_activities',
    }

    should_aggregate = field_name in aggregation_fields

    found_values = []
    found_concepts = []

    for concept in concepts:
        rows = main_items[main_items['bare_concept'] == concept]

        if not rows.empty and year_column in rows.columns:
            value = rows.iloc[0][year_column]

            if pd.notna(value):
                if should_aggregate:
                    found_values.append(float(value))
                    found_concepts.append(concept)
                else:
                    return float(value), concept

    # Handle aggregation fields
    if should_aggregate and found_values:
        if len(found_values) == 1:
            return found_values[0], found_concepts[0]
        else:
            total = sum(found_values)
            concepts_used = ' + '.join(found_concepts)
            return total, concepts_used

    return None, None


async def extract_cash_flow(
    filing,
    ticker: str,
    filing_type: str,
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    use_ai_fallback: bool = True,
) -> pd.DataFrame:
    """
    Extract cash flow statement data from a SEC filing using comprehensive mapping.

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
    print("EXTRACTING CASH FLOW STATEMENT")
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

    # Get cash flow statement
    try:
        cash_flow_stmt = xbrl.statements.cashflow_statement()

        if cash_flow_stmt is None:
            alternative_names = [
                'CONDENSEDCONSOLIDATEDSTATEMENTSOFCASHFLOWS',
                'CONSOLIDATEDSTATEMENTSOFCASHFLOWS',
                'StatementsOfCashFlows',
                'CashFlowStatements'
            ]

            for name in alternative_names:
                try:
                    cash_flow_stmt = xbrl.get_statement(name)
                    if cash_flow_stmt is not None:
                        print(f"Found cash flow statement using alternative name: {name}")
                        break
                except Exception:
                    continue

        if cash_flow_stmt is None:
            raise ValueError("Cash flow statement not available in XBRL data")

        cashflow_df = cash_flow_stmt.to_dataframe()

        if cashflow_df.empty:
            raise ValueError("Cash flow statement DataFrame is empty")

    except Exception as e:
        raise ValueError(f"Error retrieving cash flow statement: {e}")

    # Find date columns (format: YYYY-MM-DD)
    date_columns = [
        col for col in cashflow_df.columns
        if isinstance(col, str) and len(col) == 10 and col[4] == '-' and col[7] == '-'
    ]

    if not date_columns:
        raise ValueError("No date columns found in cash flow statement")

    most_recent_period = sorted(date_columns, reverse=True)[0]

    print(f"\nAvailable periods: {', '.join(date_columns)}")
    print(f"Using most recent period: {most_recent_period}")

    if use_ai_fallback:
        print(f"AI fallback enabled (batch mode)")

    print(f"\nExtracting {len(CASH_FLOW_MAPPING)} line items...")

    # ==================================================================
    # PASS 1: Static mapping lookup
    # ==================================================================
    results = []
    found_count = 0
    unfound_fields = []

    for field_name in CASH_FLOW_MAPPING.keys():
        value, concept_used = extract_value_from_statement_df(
            cashflow_df,
            field_name,
            most_recent_period,
        )

        if value is not None:
            found_count += 1
            results.append({
                'Status': 'found',
                'Field': field_name,
                'Value': value,
                'Concept': concept_used
            })
        else:
            unfound_fields.append(field_name)
            results.append({
                'Status': 'not_found',
                'Field': field_name,
                'Value': None,
                'Concept': 'Not Found'
            })

    print(f"\n  Pass 1 (static): {found_count}/{len(CASH_FLOW_MAPPING)} fields found")

    # ==================================================================
    # PASS 2: Batch AI resolution for unfound fields
    # ==================================================================
    ai_discovered = []

    if use_ai_fallback and unfound_fields:
        print(f"  Pass 2 (AI): resolving {len(unfound_fields)} unfound fields...")

        mapping_manager = None
        try:
            from xbrl_mapping_manager_multi_statement import XBRLMappingManager
            mapping_manager = XBRLMappingManager('data/xbrl_mappings_multi.duckdb')
        except Exception as e:
            print(f"  DB lookup unavailable: {e}")

        try:
            from extractors.ai_batch_helper import batch_ai_resolve_unfound_fields

            ai_results = await batch_ai_resolve_unfound_fields(
                statement_df=cashflow_df,
                mapping_dict=CASH_FLOW_MAPPING,
                unfound_fields=unfound_fields,
                year_column=most_recent_period,
                statement_type='cashflow',
                ticker=ticker,
                mapping_manager=mapping_manager,
            )

            for r in results:
                if r['Field'] in ai_results:
                    value, concept_used = ai_results[r['Field']]
                    r['Status'] = 'found'
                    r['Value'] = value
                    r['Concept'] = concept_used
                    found_count += 1

                    clean_concept = concept_used.replace(" (AI-discovered)", "")
                    ai_discovered.append({
                        'field': r['Field'],
                        'concept': clean_concept
                    })
        except Exception as e:
            print(f"  Pass 2 failed: {e}")

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

    data_quality = found_count / len(CASH_FLOW_MAPPING)

    print(f"\nExtraction complete!")
    print(f"  Fields found: {found_count}/{len(CASH_FLOW_MAPPING)}")
    print(f"  Data quality score: {data_quality:.1%}")

    # Report AI-discovered concepts
    if ai_discovered:
        print(f"\nAI discovered {len(ai_discovered)} new concept(s)!")
        print("\n" + "="*80)
        print("NEW CONCEPTS DISCOVERED BY AI")
        print("="*80)
        print("\nConsider adding these to cash_flow_xbrl_mapping.py:")
        for item in ai_discovered:
            print(f"  '{item['concept']}',  # {item['field']}")
        print("\n" + "="*80)

        try:
            from xbrl_mapping_manager_multi_statement import XBRLMappingManager
            from datetime import date as date_type

            mapper = XBRLMappingManager('data/xbrl_mappings_multi.duckdb')

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
                        """, [ticker, 'cashflow', item['field'], item['concept'], float(value),
                              filing_date_obj, period_date_obj])
                        logged_count += 1
                    except Exception as e:
                        print(f"    Failed to log {item['concept']}: {e}")

            if logged_count > 0:
                print(f"  Logged {logged_count} AI discoveries to database")

            mapper.close()

        except Exception as e:
            print(f"  Failed to log to database: {e}")
            print(f"     (Discoveries still captured in output)")

    if data_quality < 0.5:
        print(f"  WARNING: Low data quality (<50%). Check if correct filing was retrieved.")

    return result_df


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def main():
        # Example: Extract Apple's cash flow statement
        filing = get_filing('AAPL', '10-K', 2024)
        df = await extract_cash_flow(filing, 'AAPL', '10-K', use_ai_fallback=True)
        
        print("\n" + "="*80)
        print("CASH FLOW STATEMENT RESULTS")
        print("="*80)
        print(df.to_string())
    
    asyncio.run(main())
