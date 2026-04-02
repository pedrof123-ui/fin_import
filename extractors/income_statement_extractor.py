"""
Financial Statement Extractor - Updated Version
Downloads and extracts income statements from SEC EDGAR using comprehensive XBRL mapping
"""

import pandas as pd
from typing import Optional, Literal
import asyncio

from .filing import get_filing, parse_date

try:
    from xbrl_mappings import INCOME_STATEMENT_MAPPING
    print(f"Loaded comprehensive XBRL mapping ({sum(len(v) for v in INCOME_STATEMENT_MAPPING.values())} concepts, {len(INCOME_STATEMENT_MAPPING)} fields)")
except ImportError as e:
    print("ERROR: Could not import from xbrl_mappings package")
    print("Please ensure xbrl_mappings/__init__.py exists and income_statement_xbrl_mapping.py is in the xbrl_mappings folder.")
    raise SystemExit(f"Import Error: {e}")



def extract_value_from_statement_df(
    statement_df: pd.DataFrame,
    field_name: str,
    year_column: str,
) -> tuple[Optional[float], Optional[str]]:
    """
    Extract a single value from the income statement DataFrame using static mapping only.

    This function handles two cases:
    1. Single concept (e.g., Revenue) - returns the value directly
    2. Multiple component concepts (e.g., Selling + G&A) - aggregates them

    Args:
        statement_df: DataFrame from xbrl.statements.income_statement().to_dataframe()
        field_name: Field to extract (e.g., 'revenue', 'net_income')
        year_column: Column name for the period (e.g., '2024-12-31')

    Returns:
        Tuple of (value, concept_used) or (None, None) if not found
    """
    # Get concepts to try for this field
    concepts = INCOME_STATEMENT_MAPPING.get(field_name)

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

    # Fields that should aggregate components (not take first match)
    aggregation_fields = {
        'selling_general_admin',
        'depreciation_amortization',
        'other_operating_expenses',
        'interest_expense',
        'interest_income',
    }

    should_aggregate = field_name in aggregation_fields

    # Track found values for aggregation
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


async def extract_income_statement(
    filing,
    ticker: str,
    filing_type: str,
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    use_ai_fallback: bool = True,
) -> pd.DataFrame:
    """
    Extract income statement data from a SEC filing using comprehensive mapping.

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
    print("EXTRACTING INCOME STATEMENT")
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

    # Get income statement
    try:
        income_stmt = xbrl.statements.income_statement()

        # If standard method doesn't work, try alternative statement names
        if income_stmt is None:
            alternative_names = [
                'CONDENSEDCONSOLIDATEDSTATEMENTSOFOPERATIONSUnaudited',
                'CONSOLIDATEDSTATEMENTSOFOPERATIONS',
                'CONSOLIDATEDSTATEMENTSOFEARNINGS',
                'StatementsOfIncome',
                'StatementsOfOperations'
            ]

            for name in alternative_names:
                try:
                    income_stmt = xbrl.get_statement(name)
                    if income_stmt is not None:
                        print(f"Found income statement using alternative name: {name}")
                        break
                except Exception:
                    continue

        if income_stmt is None:
            raise ValueError("Income statement not available in XBRL data")

        # Convert to DataFrame
        income_df = income_stmt.to_dataframe()

        if income_df.empty:
            raise ValueError("Income statement DataFrame is empty")

    except Exception as e:
        raise ValueError(f"Error retrieving income statement: {e}")

    # Find date columns (format: YYYY-MM-DD)
    date_columns = [
        col for col in income_df.columns
        if isinstance(col, str) and len(col) == 10 and col[4] == '-' and col[7] == '-'
    ]

    if not date_columns:
        raise ValueError("No date columns found in income statement")

    # Use the most recent period
    most_recent_period = sorted(date_columns, reverse=True)[0]

    print(f"\nAvailable periods: {', '.join(date_columns)}")
    print(f"Using most recent period: {most_recent_period}")

    if use_ai_fallback:
        print(f"AI fallback enabled (batch mode)")

    print(f"\nExtracting {len(INCOME_STATEMENT_MAPPING)} line items...")

    # ==================================================================
    # PASS 1: Static mapping lookup
    # ==================================================================
    results = []
    found_count = 0
    unfound_fields = []

    for field_name in INCOME_STATEMENT_MAPPING.keys():
        value, concept_used = extract_value_from_statement_df(
            income_df,
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

    print(f"\n  Pass 1 (static): {found_count}/{len(INCOME_STATEMENT_MAPPING)} fields found")

    # ==================================================================
    # PASS 2: Batch AI resolution for unfound fields
    # ==================================================================
    ai_discovered = []

    if use_ai_fallback and unfound_fields:
        print(f"  Pass 2 (AI): resolving {len(unfound_fields)} unfound fields...")

        # Get mapping manager for DB lookups
        mapping_manager = None
        try:
            from xbrl_mapping_manager_multi_statement import XBRLMappingManager
            mapping_manager = XBRLMappingManager('data/xbrl_mappings_multi.duckdb')
        except Exception as e:
            print(f"  DB lookup unavailable: {e}")

        try:
            from extractors.ai_batch_helper import batch_ai_resolve_unfound_fields

            ai_results = await batch_ai_resolve_unfound_fields(
                statement_df=income_df,
                mapping_dict=INCOME_STATEMENT_MAPPING,
                unfound_fields=unfound_fields,
                year_column=most_recent_period,
                statement_type='income',
                ticker=ticker,
                mapping_manager=mapping_manager,
            )

            # Merge AI results back into results list
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

    # Add metadata columns at the beginning
    result_df.insert(0, 'Ticker', ticker)
    result_df.insert(1, 'Fiscal_Year', year)
    result_df.insert(2, 'Period_End_Date', most_recent_period)
    result_df.insert(3, 'Filing_Date', filing_date)
    result_df.insert(4, 'Filing_Type', form_type)
    result_df.insert(5, 'Period_Type', period_type)
    result_df.insert(6, 'Quarter', quarter if not is_annual else None)

    # Calculate data quality score
    data_quality = found_count / len(INCOME_STATEMENT_MAPPING)

    print(f"\nExtraction complete!")
    print(f"  Fields found: {found_count}/{len(INCOME_STATEMENT_MAPPING)}")
    print(f"  Data quality score: {data_quality:.1%}")

    # Report AI-discovered concepts
    if ai_discovered:
        print(f"\nAI discovered {len(ai_discovered)} new concept(s)!")
        print("\n" + "="*80)
        print("NEW CONCEPTS DISCOVERED BY AI")
        print("="*80)
        print("\nConsider adding these to income_statement_xbrl_mapping.py:")
        for item in ai_discovered:
            print(f"  '{item['concept']}',  # {item['field']}")
        print("\n" + "="*80)

        # Log to database
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
                        """, [ticker, 'income', item['field'], item['concept'], float(value),
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


def format_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """
    Format the extracted data for better display.
    
    Args:
        df: Raw extraction results with metadata
    
    Returns:
        Formatted DataFrame for display (without metadata columns shown)
    """
    def format_value(row):
        """Format value based on field type"""
        val = row['Value']
        field = row['Field']
        
        if pd.isna(val):
            return "Not Found"
        
        # EPS fields - show 2 decimals
        if 'eps' in field.lower():
            return f"${val:,.2f}"
        
        # Share counts - show as whole numbers
        elif 'shares' in field.lower():
            return f"{val:,.0f}"
        
        # Everything else - show as dollars with no decimals
        else:
            return f"${val:,.0f}"
    
    # Create a copy for formatting
    formatted_df = df.copy()
    formatted_df['Formatted_Value'] = formatted_df.apply(format_value, axis=1)
    
    # Keep metadata columns but also add Field, Value, Concept for display
    # Metadata columns: Ticker, Fiscal_Year, Period_End_Date, Filing_Date, Filing_Type, Period_Type, Quarter
    display_df = formatted_df[['Status', 'Field', 'Formatted_Value', 'Concept']]
    display_df = display_df.rename(columns={'Formatted_Value': 'Value'})
    
    return display_df


def validate_income_statement(df: pd.DataFrame) -> dict:
    """
    Validate financial statement relationships.
    
    Args:
        df: Extracted data DataFrame
    
    Returns:
        Dictionary with validation results
    """
    # Convert to dictionary for easier access
    data = dict(zip(df['Field'], df['Value']))
    
    validations = {}
    
    # Check 1: Revenue - Cost of Revenue = Gross Profit
    if all(k in data and pd.notna(data[k]) for k in ['revenue', 'cost_of_revenue', 'gross_profit']):
        calculated_gp = data['revenue'] - data['cost_of_revenue']
        reported_gp = data['gross_profit']
        variance = abs(calculated_gp - reported_gp) / reported_gp if reported_gp != 0 else 0
        
        validations['gross_profit_calc'] = {
            'passed': variance < 0.02,  # 2% tolerance
            'variance': f"{variance:.1%}",
            'calculated': f"${calculated_gp:,.0f}",
            'reported': f"${reported_gp:,.0f}"
        }
    
    # Check 2: Operating Income < Gross Profit
    if all(k in data and pd.notna(data[k]) for k in ['gross_profit', 'operating_income']):
        validations['operating_income_logical'] = {
            'passed': data['operating_income'] <= data['gross_profit'],
            'operating_income': f"${data['operating_income']:,.0f}",
            'gross_profit': f"${data['gross_profit']:,.0f}"
        }
    
    # Check 3: Net Income < Pretax Income
    if all(k in data and pd.notna(data[k]) for k in ['pretax_income', 'net_income']):
        validations['tax_logical'] = {
            'passed': data['net_income'] <= data['pretax_income'],
            'net_income': f"${data['net_income']:,.0f}",
            'pretax_income': f"${data['pretax_income']:,.0f}"
        }
    
    return validations


def print_validation_results(validations: dict):
    """Print validation results in a readable format."""
    if not validations:
        print("\nNo validations could be performed (missing required fields)")
        return
    
    print("\n" + "="*80)
    print("VALIDATION CHECKS")
    print("="*80)
    
    all_passed = True
    
    for check_name, result in validations.items():
        passed = result.get('passed', False)
        status = "PASS" if passed else "FAIL"
        
        if not passed:
            all_passed = False
        
        print(f"\n{status} - {check_name.replace('_', ' ').title()}")
        
        for key, value in result.items():
            if key != 'passed':
                print(f"  {key}: {value}")
    
    if all_passed:
        print("\nAll validation checks passed!")
    else:
        print("\nSome validation checks failed. Review the data carefully.")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    
    # ===== USER CONFIGURATION =====
    # Modify these parameters to get the income statement you need
    
    TICKER = "AAPL"           # Company ticker symbol
    FILING_TYPE = "10-K"      # "10-K" for annual, "10-Q" for quarterly
    YEAR = 2024               # Fiscal year (set to None for most recent)
    QUARTER = None            # Fiscal quarter 1-4 (only for 10-Q, set to None)
    
    # ===== END USER CONFIGURATION =====
    
    print("\n" + "="*80)
    print("FINANCIAL STATEMENT EXTRACTOR")
    print("="*80)
    print("\nConfiguration:")
    print(f"  Ticker: {TICKER}")
    print(f"  Filing Type: {FILING_TYPE}")
    print(f"  Year: {YEAR if YEAR else 'Most Recent'}")
    if FILING_TYPE == "10-Q":
        print(f"  Quarter: Q{QUARTER if QUARTER else 'Most Recent'}")
    print()
    
    try:
        # Step 1: Get the filing
        filing = get_filing(
            ticker=TICKER,
            filing_type=FILING_TYPE,
            year=YEAR,
            quarter=QUARTER
        )
        
        # Step 2: Extract income statement with metadata
        income_statement_df = extract_income_statement(
            filing=filing,
            ticker=TICKER,
            filing_type=FILING_TYPE,
            year=YEAR,
            quarter=QUARTER
        )
        
        # Step 3: Format for display
        formatted_df = format_for_display(income_statement_df)
        
        # Step 4: Display metadata first
        print("\n" + "="*80)
        print(f"INCOME STATEMENT - {TICKER}")
        print("="*80)
        
        # Show metadata
        if not income_statement_df.empty:
            metadata = income_statement_df.iloc[0]
            print(f"\nFiling Metadata:")
            print(f"  Ticker:           {metadata['Ticker']}")
            print(f"  Fiscal Year:      {metadata['Fiscal_Year']}")
            print(f"  Period End Date:  {metadata['Period_End_Date']}")
            print(f"  Filing Date:      {metadata['Filing_Date']}")
            print(f"  Filing Type:      {metadata['Filing_Type']}")
            print(f"  Period Type:      {metadata['Period_Type']}")
            if metadata['Quarter']:
                print(f"  Quarter:          Q{metadata['Quarter']}")
        
        # Step 5: Display results in sections
        print("\n" + "-"*80)
        print("FINANCIAL DATA:")
        print("-"*80)
        
        print("\nREVENUE & COSTS:")
        revenue_section = formatted_df[
            formatted_df['Field'].isin(['revenue', 'cost_of_revenue', 'gross_profit'])
        ]
        print(revenue_section[['Status', 'Field', 'Value', 'Concept']].to_string(index=False))
        
        print("\n\nOPERATING EXPENSES:")
        opex_section = formatted_df[
            formatted_df['Field'].isin([
                'research_development', 'selling_general_admin', 
                'depreciation_amortization', 'restructuring_charges',
                'other_operating_expenses', 'total_operating_expenses',
                'operating_income'
            ])
        ]
        print(opex_section[['Status', 'Field', 'Value', 'Concept']].to_string(index=False))
        
        print("\n\nNON-OPERATING ITEMS:")
        nonop_section = formatted_df[
            formatted_df['Field'].isin([
                'interest_income', 'interest_expense', 
                'equity_method_investments', 'investment_gains_losses',
                'other_nonoperating_income'
            ])
        ]
        print(nonop_section[['Status', 'Field', 'Value', 'Concept']].to_string(index=False))
        
        print("\n\nNET INCOME:")
        netincome_section = formatted_df[
            formatted_df['Field'].isin([
                'pretax_income', 'income_tax_expense', 
                'net_income_continuing_ops', 'discontinued_operations',
                'net_income_attributable_to_nci', 'net_income',
                'net_income_attributable_to_parent'
            ])
        ]
        print(netincome_section[['Status', 'Field', 'Value', 'Concept']].to_string(index=False))
        
        print("\n\nPER SHARE DATA:")
        pershare_section = formatted_df[
            formatted_df['Field'].isin([
                'basic_eps', 'diluted_eps', 
                'basic_shares', 'diluted_shares'
            ])
        ]
        print(pershare_section[['Status', 'Field', 'Value', 'Concept']].to_string(index=False))
        
        # Step 6: Validate
        validations = validate_income_statement(income_statement_df)
        print_validation_results(validations)
        
        # Step 7: Export with metadata in filename
        fiscal_year = income_statement_df.iloc[0]['Fiscal_Year']
        filing_type_clean = income_statement_df.iloc[0]['Filing_Type'].replace('/', '-')
        quarter_str = f"_Q{income_statement_df.iloc[0]['Quarter']}" if income_statement_df.iloc[0]['Quarter'] else ""
        
        export_path = f"{TICKER}_{filing_type_clean}_{fiscal_year}{quarter_str}_income_statement.csv"
        income_statement_df.to_csv(export_path, index=False)
        print(f"\nData exported to: {export_path}")
        
    except Exception as e:
        print(f"\nERROR: {str(e)}")
        print("\nTroubleshooting tips:")
        print("  1. Check that the ticker symbol is correct")
        print("  2. Verify the year and quarter (if applicable)")
        print("  3. Ensure your SEC_ID is set in .env file")
        print("  4. Check your internet connection")
        print("  5. Try a different filing year or type")
        raise
