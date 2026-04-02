"""
Financial Statement Extractor - Updated Version
Downloads and extracts income statements from SEC EDGAR using comprehensive XBRL mapping
"""

import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd
from edgar import Company, set_identity
from typing import Optional, Literal

# Load environment variables
load_dotenv()

# Set SEC identity to avoid 403 blocks
sec_identity = os.getenv("SEC_ID")
if not sec_identity:
    raise ValueError("SEC_ID not found in .env file")

set_identity(sec_identity)

# Import the new comprehensive mapping
try:
    from income_statement_xbrl_mapping import INCOME_STATEMENT_MAPPING
    print("✓ Loaded comprehensive XBRL mapping (148 concepts, 30 fields)")
except ImportError as e:
    print("ERROR: Could not import income_statement_xbrl_mapping.py")
    print("Please ensure the file is in the same directory as this script.")
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
    year_column: str
) -> tuple[Optional[float], Optional[str]]:
    """
    Extract a single value from the income statement DataFrame using the mapping.
    
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
        print(f"  ✗ ERROR: Field '{field_name}' not found in mapping!")
        return None, None
    
    # Filter to main items (no dimensional breakdowns)
    main_items = statement_df[
        (statement_df['dimension'] == False) & 
        (statement_df['abstract'] == False)
    ]
    
    # Fields that should aggregate components (not take first match)
    # These fields often have separate line items that should be summed
    aggregation_fields = {
        'selling_general_admin',      # May have separate Selling, Marketing, G&A
        'depreciation_amortization',  # May have separate D&A in different sections
        'other_operating_expenses',   # Various operating expenses
        'interest_expense',           # May have operating + non-operating
        'interest_income',            # May have multiple sources
    }
    
    should_aggregate = field_name in aggregation_fields
    
    # Track found values for aggregation
    found_values = []
    found_concepts = []
    
    # Try each concept in priority order
    for concept in concepts:
        # Add us-gaap_ prefix if not company-specific
        if '_' in concept and not concept.startswith('us-gaap'):
            # Company-specific concept (e.g., 'gm_...', 'tsla_...')
            full_concept = concept
        else:
            # Standard US-GAAP concept
            full_concept = f"us-gaap_{concept}"
        
        # Look for this concept in the statement
        rows = main_items[main_items['concept'] == full_concept]
        
        if not rows.empty and year_column in rows.columns:
            value = rows.iloc[0][year_column]
            
            # Check if value is not NaN
            if pd.notna(value):
                if should_aggregate:
                    # Collect all matching concepts for aggregation
                    found_values.append(float(value))
                    found_concepts.append(concept)
                else:
                    # Return first match for non-aggregation fields
                    return float(value), concept
    
    # Handle aggregation fields
    if should_aggregate and found_values:
        if len(found_values) == 1:
            # Only one component found, return it
            return found_values[0], found_concepts[0]
        else:
            # Multiple components found, aggregate them
            total = sum(found_values)
            concepts_used = ' + '.join(found_concepts)
            return total, concepts_used
    
    # Not found with any concept
    return None, None


def extract_income_statement(filing) -> pd.DataFrame:
    """
    Extract income statement data from a SEC filing using comprehensive mapping.
    
    Args:
        filing: Filing object from edgartools
    
    Returns:
        DataFrame with extracted line items
    """
    print("\n" + "="*80)
    print("EXTRACTING INCOME STATEMENT")
    print("="*80)
    
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
                        print(f"✓ Found income statement using alternative name: {name}")
                        break
                except:
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
    
    print(f"\n✓ Available periods: {', '.join(date_columns)}")
    print(f"✓ Using most recent period: {most_recent_period}")
    print(f"\nExtracting {len(INCOME_STATEMENT_MAPPING)} line items...")
    
    # Extract each field using the mapping
    results = []
    found_count = 0
    
    for field_name in INCOME_STATEMENT_MAPPING.keys():
        value, concept_used = extract_value_from_statement_df(
            income_df, 
            field_name, 
            most_recent_period
        )
        
        if value is not None:
            found_count += 1
            status = "✓"
        else:
            status = "✗"
            concept_used = "Not Found"
        
        results.append({
            'Status': status,
            'Field': field_name,
            'Value': value,
            'Concept': concept_used
        })
    
    # Create results DataFrame
    result_df = pd.DataFrame(results)
    
    # Calculate data quality score
    data_quality = found_count / len(INCOME_STATEMENT_MAPPING)
    
    print(f"\n✓ Extraction complete!")
    print(f"  Fields found: {found_count}/{len(INCOME_STATEMENT_MAPPING)}")
    print(f"  Data quality score: {data_quality:.1%}")
    
    if data_quality < 0.5:
        print(f"  ⚠ WARNING: Low data quality (<50%). Check if correct filing was retrieved.")
    
    return result_df


def format_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """
    Format the extracted data for better display.
    
    Args:
        df: Raw extraction results
    
    Returns:
        Formatted DataFrame for display
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
    
    formatted_df = df.copy()
    formatted_df['Formatted_Value'] = formatted_df.apply(format_value, axis=1)
    
    # Reorder columns for display
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
        print("\n⚠ No validations could be performed (missing required fields)")
        return
    
    print("\n" + "="*80)
    print("VALIDATION CHECKS")
    print("="*80)
    
    all_passed = True
    
    for check_name, result in validations.items():
        passed = result.get('passed', False)
        status = "✓ PASS" if passed else "✗ FAIL"
        
        if not passed:
            all_passed = False
        
        print(f"\n{status} - {check_name.replace('_', ' ').title()}")
        
        for key, value in result.items():
            if key != 'passed':
                print(f"  {key}: {value}")
    
    if all_passed:
        print("\n✓ All validation checks passed!")
    else:
        print("\n⚠ Some validation checks failed. Review the data carefully.")


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
        
        # Step 2: Extract income statement
        income_statement_df = extract_income_statement(filing)
        
        # Step 3: Format for display
        formatted_df = format_for_display(income_statement_df)
        
        # Step 4: Display results
        print("\n" + "="*80)
        print(f"INCOME STATEMENT - {TICKER}")
        print(f"Filing: {FILING_TYPE} | Year: {YEAR if YEAR else 'Most Recent'}")
        print("="*80 + "\n")
        
        # Print in sections for better readability
        print("REVENUE & COSTS:")
        revenue_section = formatted_df[
            formatted_df['Field'].isin(['revenue', 'cost_of_revenue', 'gross_profit'])
        ]
        print(revenue_section.to_string(index=False))
        
        print("\n\nOPERATING EXPENSES:")
        opex_section = formatted_df[
            formatted_df['Field'].isin([
                'research_development', 'selling_general_admin', 
                'depreciation_amortization', 'restructuring_charges',
                'other_operating_expenses', 'total_operating_expenses',
                'operating_income'
            ])
        ]
        print(opex_section.to_string(index=False))
        
        print("\n\nNON-OPERATING ITEMS:")
        nonop_section = formatted_df[
            formatted_df['Field'].isin([
                'interest_income', 'interest_expense', 
                'equity_method_investments', 'investment_gains_losses',
                'other_nonoperating_income'
            ])
        ]
        print(nonop_section.to_string(index=False))
        
        print("\n\nNET INCOME:")
        netincome_section = formatted_df[
            formatted_df['Field'].isin([
                'pretax_income', 'income_tax_expense', 
                'net_income_continuing_ops', 'discontinued_operations',
                'net_income', 'net_income_attributable_to_nci',
                'net_income_attributable_to_parent'
            ])
        ]
        print(netincome_section.to_string(index=False))
        
        print("\n\nPER SHARE DATA:")
        pershare_section = formatted_df[
            formatted_df['Field'].isin([
                'basic_eps', 'diluted_eps', 
                'basic_shares', 'diluted_shares'
            ])
        ]
        print(pershare_section.to_string(index=False))
        
        # Step 5: Validate
        validations = validate_income_statement(income_statement_df)
        print_validation_results(validations)
        
        # Step 6: Export option
        export_path = f"{TICKER}_{FILING_TYPE}_{YEAR}_income_statement.csv"
        income_statement_df.to_csv(export_path, index=False)
        print(f"\n✓ Data exported to: {export_path}")
        
    except Exception as e:
        print(f"\n✗ ERROR: {str(e)}")
        print("\nTroubleshooting tips:")
        print("  1. Check that the ticker symbol is correct")
        print("  2. Verify the year and quarter (if applicable)")
        print("  3. Ensure your SEC_ID is set in .env file")
        print("  4. Check your internet connection")
        print("  5. Try a different filing year or type")
        raise
