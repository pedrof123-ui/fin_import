"""
Bulk 10-K Import Function
Downloads and imports multiple years of 10-K statements for a list of companies

Features:
- Imports last N years of 10-K filings
- Handles missing statements gracefully
- Comprehensive logging
- Progress tracking
- Summary reports
- Automatic retry logic

Usage:
    from bulk_import_10k import bulk_import_10k
    
    bulk_import_10k(
        ticker_csv='tickers.csv',
        periods=20,
        db_path='financial_statements.duckdb'
    )
"""

import pandas as pd
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import asyncio
from tqdm import tqdm

# Import extractors
from extractors.income_statement_extractor import get_filing, extract_income_statement
from extractors.balance_sheet_extractor import extract_balance_sheet
from extractors.cash_flow_extractor import extract_cash_flow
from financial_statements_db import FinancialStatementsDB

# Import edgar tools
from edgar import Company


class BulkImportLogger:
    """Handles logging for bulk import operations"""
    
    def __init__(self, log_file: str = 'bulk_import.log'):
        self.log_file = log_file
        self.entries = []
        
        # Clear log file
        with open(log_file, 'w') as f:
            f.write(f"Bulk Import Log - Started at {datetime.now()}\n")
            f.write("="*80 + "\n\n")
    
    def log(self, level: str, ticker: str, message: str, year: Optional[int] = None):
        """
        Log a message
        
        Args:
            level: INFO, SUCCESS, WARNING, ERROR
            ticker: Company ticker
            message: Log message
            year: Optional year
        """
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        year_str = f" {year}" if year else ""
        
        entry = f"{timestamp} | {level:7s} | [{ticker}{year_str}] {message}"
        
        # Store in memory
        self.entries.append({
            'timestamp': timestamp,
            'level': level,
            'ticker': ticker,
            'year': year,
            'message': message
        })
        
        # Write to file
        with open(self.log_file, 'a') as f:
            f.write(entry + "\n")
        
        # Print to console for ERROR and WARNING
        if level in ['ERROR', 'WARNING']:
            print(entry)
    
    def get_summary(self) -> Dict[str, int]:
        """Get summary statistics"""
        summary = {
            'total_entries': len(self.entries),
            'success': sum(1 for e in self.entries if e['level'] == 'SUCCESS'),
            'warnings': sum(1 for e in self.entries if e['level'] == 'WARNING'),
            'errors': sum(1 for e in self.entries if e['level'] == 'ERROR')
        }
        return summary
    
    def export_to_csv(self, output_path: str):
        """Export log to CSV"""
        df = pd.DataFrame(self.entries)
        df.to_csv(output_path, index=False)


def read_ticker_csv(csv_path: str) -> List[str]:
    """
    Read ticker list from CSV file
    
    Supports two formats:
    1. Single column 'ticker'
    2. Multiple columns with 'ticker' as one of them
    
    Args:
        csv_path: Path to CSV file
    
    Returns:
        List of ticker symbols
    """
    df = pd.read_csv(csv_path)
    
    # Find ticker column (case insensitive)
    ticker_col = None
    for col in df.columns:
        if col.lower() in ['ticker', 'symbol', 'stock']:
            ticker_col = col
            break
    
    if ticker_col is None:
        # If no ticker column, assume first column
        ticker_col = df.columns[0]
    
    tickers = df[ticker_col].dropna().unique().tolist()
    tickers = [str(t).strip().upper() for t in tickers]
    
    return tickers


async def extract_and_insert_filing(
    filing,
    ticker: str,
    year: int,
    db: FinancialStatementsDB,
    logger: BulkImportLogger,
    use_ai_fallback: bool = False
) -> Dict[str, Any]:
    """
    Extract all 3 statements and insert into database
    
    Args:
        filing: Filing object from edgartools
        ticker: Company ticker
        year: Fiscal year
        db: Database instance
        logger: Logger instance
        use_ai_fallback: Whether to use AI mapper
    
    Returns:
        Dict with results for each statement
    """
    results = {
        'income': {'success': False, 'coverage': 0.0, 'error': None},
        'balance': {'success': False, 'coverage': 0.0, 'error': None},
        'cashflow': {'success': False, 'coverage': 0.0, 'error': None}
    }
    
    # Extract income statement
    try:
        income_df = await extract_income_statement(
            filing, ticker, '10-K', year, use_ai_fallback=use_ai_fallback
        )
        
        # Calculate coverage
        fields_found = len(income_df[income_df['Status'] == '✓'])
        coverage = (fields_found / len(income_df)) * 100
        
        # Insert to database
        success = db.insert_income_statement(income_df)
        
        results['income'] = {
            'success': success,
            'coverage': coverage,
            'error': None
        }
        
        if success:
            logger.log('SUCCESS', ticker, f"Income statement: {coverage:.1f}% coverage", year)
        else:
            logger.log('ERROR', ticker, f"Failed to insert income statement", year)
        
    except Exception as e:
        results['income']['error'] = str(e)
        logger.log('ERROR', ticker, f"Income statement extraction failed: {e}", year)
    
    # Extract balance sheet
    try:
        balance_df = await extract_balance_sheet(
            filing, ticker, '10-K', year, use_ai_fallback=use_ai_fallback
        )
        
        fields_found = len(balance_df[balance_df['Status'] == '✓'])
        coverage = (fields_found / len(balance_df)) * 100
        
        success = db.insert_balance_sheet(balance_df)
        
        results['balance'] = {
            'success': success,
            'coverage': coverage,
            'error': None
        }
        
        if success:
            logger.log('SUCCESS', ticker, f"Balance sheet: {coverage:.1f}% coverage", year)
        else:
            logger.log('ERROR', ticker, f"Failed to insert balance sheet", year)
        
    except Exception as e:
        results['balance']['error'] = str(e)
        logger.log('ERROR', ticker, f"Balance sheet extraction failed: {e}", year)
    
    # Extract cash flow
    try:
        cashflow_df = await extract_cash_flow(
            filing, ticker, '10-K', year, use_ai_fallback=use_ai_fallback
        )
        
        fields_found = len(cashflow_df[cashflow_df['Status'] == '✓'])
        coverage = (fields_found / len(cashflow_df)) * 100
        
        success = db.insert_cash_flow(cashflow_df)
        
        results['cashflow'] = {
            'success': success,
            'coverage': coverage,
            'error': None
        }
        
        if success:
            logger.log('SUCCESS', ticker, f"Cash flow: {coverage:.1f}% coverage", year)
        else:
            logger.log('ERROR', ticker, f"Failed to insert cash flow", year)
        
    except Exception as e:
        results['cashflow']['error'] = str(e)
        logger.log('ERROR', ticker, f"Cash flow extraction failed: {e}", year)
    
    return results


async def process_ticker(
    ticker: str,
    periods: int,
    db: FinancialStatementsDB,
    logger: BulkImportLogger,
    use_ai_fallback: bool = False,
    skip_existing: bool = True,
    rate_limit_delay: float = 1.0
) -> Dict[str, Any]:
    """
    Process all 10-K filings for a single ticker
    
    Args:
        ticker: Company ticker symbol
        periods: Number of periods to extract
        db: Database instance
        logger: Logger instance
        use_ai_fallback: Whether to use AI mapper
        skip_existing: Skip filings already in database
        rate_limit_delay: Delay between requests (seconds)
    
    Returns:
        Dict with processing results
    """
    ticker_results = {
        'ticker': ticker,
        'filings_found': 0,
        'filings_processed': 0,
        'filings_skipped': 0,
        'filings_failed': 0,
        'statements_success': 0,
        'statements_failed': 0,
        'start_time': time.time()
    }
    
    try:
        # Get company
        company = Company(ticker)
        logger.log('INFO', ticker, f"Retrieved company: {company.name}")
        
        # Get all 10-K filings
        filings = company.get_filings(form='10-K')
        
        if filings.empty:
            logger.log('WARNING', ticker, "No 10-K filings found")
            return ticker_results
        
        # Limit to requested number of periods
        filings_list = list(filings)[:periods]
        ticker_results['filings_found'] = len(filings_list)
        
        logger.log('INFO', ticker, f"Found {len(filings_list)} 10-K filings")
        
        # Process each filing
        for filing in filings_list:
            # Extract year from filing
            try:
                period_date = pd.to_datetime(filing.period_of_report)
                year = period_date.year
            except:
                logger.log('WARNING', ticker, f"Could not parse period date: {filing.period_of_report}")
                ticker_results['filings_skipped'] += 1
                continue
            
            # Check if already in database
            if skip_existing:
                existing = db.conn.execute("""
                    SELECT COUNT(*) as count FROM income_statements 
                    WHERE ticker = ? AND fiscal_year = ?
                """, [ticker, year]).fetchone()
                
                if existing and existing[0] > 0:
                    logger.log('INFO', ticker, f"Already in database, skipping", year)
                    ticker_results['filings_skipped'] += 1
                    continue
            
            # Extract and insert
            try:
                results = await extract_and_insert_filing(
                    filing, ticker, year, db, logger, use_ai_fallback
                )
                
                # Count successes
                success_count = sum(1 for r in results.values() if r['success'])
                ticker_results['statements_success'] += success_count
                ticker_results['statements_failed'] += (3 - success_count)
                
                if success_count > 0:
                    ticker_results['filings_processed'] += 1
                else:
                    ticker_results['filings_failed'] += 1
                
                # Rate limiting
                await asyncio.sleep(rate_limit_delay)
                
            except Exception as e:
                logger.log('ERROR', ticker, f"Filing processing failed: {e}", year)
                ticker_results['filings_failed'] += 1
        
    except Exception as e:
        logger.log('ERROR', ticker, f"Ticker processing failed: {e}")
    
    ticker_results['end_time'] = time.time()
    ticker_results['duration_seconds'] = ticker_results['end_time'] - ticker_results['start_time']
    
    return ticker_results


async def bulk_import_10k(
    ticker_csv: str,
    periods: int = 20,
    db_path: str = 'financial_statements.duckdb',
    log_file: str = 'bulk_import.log',
    output_dir: str = './bulk_import_results',
    use_ai_fallback: bool = False,
    skip_existing: bool = True,
    rate_limit_delay: float = 1.0
) -> Dict[str, Any]:
    """
    Bulk import 10-K statements for multiple companies
    
    Args:
        ticker_csv: Path to CSV file with ticker list
        periods: Number of periods (years) to import per ticker
        db_path: Path to DuckDB database
        log_file: Path to log file
        output_dir: Directory for output reports
        use_ai_fallback: Whether to use AI mapper for unmapped concepts
        skip_existing: Skip filings already in database
        rate_limit_delay: Delay between requests in seconds (default 1.0)
    
    Returns:
        Dict with overall results and statistics
    
    Example:
        >>> results = await bulk_import_10k(
        ...     ticker_csv='tickers.csv',
        ...     periods=20,
        ...     use_ai_fallback=True
        ... )
    """
    
    print("="*80)
    print("BULK 10-K IMPORT")
    print("="*80)
    
    start_time = time.time()
    
    # Create output directory
    Path(output_dir).mkdir(exist_ok=True)
    
    # Initialize logger
    logger = BulkImportLogger(log_file)
    
    # Read tickers
    print(f"\n📋 Reading tickers from {ticker_csv}...")
    tickers = read_ticker_csv(ticker_csv)
    print(f"✓ Found {len(tickers)} tickers")
    logger.log('INFO', 'SYSTEM', f"Starting bulk import: {len(tickers)} tickers, {periods} periods each")
    
    # Initialize database
    print(f"\n💾 Connecting to database: {db_path}...")
    db = FinancialStatementsDB(db_path)
    
    # Process each ticker
    print(f"\n🚀 Starting bulk extraction...")
    print(f"   Rate limit: {rate_limit_delay}s between requests")
    print(f"   AI fallback: {'Enabled' if use_ai_fallback else 'Disabled'}")
    print(f"   Skip existing: {'Yes' if skip_existing else 'No'}")
    print()
    
    all_results = []
    
    for i, ticker in enumerate(tickers, 1):
        print(f"\n[{i}/{len(tickers)}] Processing {ticker}...")
        print("-" * 80)
        
        ticker_results = await process_ticker(
            ticker=ticker,
            periods=periods,
            db=db,
            logger=logger,
            use_ai_fallback=use_ai_fallback,
            skip_existing=skip_existing,
            rate_limit_delay=rate_limit_delay
        )
        
        all_results.append(ticker_results)
        
        # Print ticker summary
        print(f"\n✓ {ticker} complete:")
        print(f"  Filings found: {ticker_results['filings_found']}")
        print(f"  Filings processed: {ticker_results['filings_processed']}")
        print(f"  Filings skipped: {ticker_results['filings_skipped']}")
        print(f"  Filings failed: {ticker_results['filings_failed']}")
        print(f"  Statements success: {ticker_results['statements_success']}")
        print(f"  Statements failed: {ticker_results['statements_failed']}")
        print(f"  Duration: {ticker_results['duration_seconds']:.1f}s")
    
    # Close database
    db.close()
    
    # Calculate overall statistics
    end_time = time.time()
    total_duration = end_time - start_time
    
    overall_results = {
        'total_tickers': len(tickers),
        'total_filings_found': sum(r['filings_found'] for r in all_results),
        'total_filings_processed': sum(r['filings_processed'] for r in all_results),
        'total_filings_skipped': sum(r['filings_skipped'] for r in all_results),
        'total_filings_failed': sum(r['filings_failed'] for r in all_results),
        'total_statements_success': sum(r['statements_success'] for r in all_results),
        'total_statements_failed': sum(r['statements_failed'] for r in all_results),
        'total_duration_seconds': total_duration,
        'average_time_per_ticker': total_duration / len(tickers) if tickers else 0,
        'start_time': datetime.fromtimestamp(start_time).isoformat(),
        'end_time': datetime.fromtimestamp(end_time).isoformat()
    }
    
    # Generate reports
    print("\n" + "="*80)
    print("GENERATING REPORTS")
    print("="*80)
    
    # 1. Summary report
    summary_df = pd.DataFrame(all_results)
    summary_path = f"{output_dir}/summary_report.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"✓ Summary report: {summary_path}")
    
    # 2. Export log to CSV
    log_csv_path = f"{output_dir}/detailed_log.csv"
    logger.export_to_csv(log_csv_path)
    print(f"✓ Detailed log: {log_csv_path}")
    
    # 3. Failed filings report
    failures = []
    for entry in logger.entries:
        if entry['level'] == 'ERROR':
            failures.append(entry)
    
    if failures:
        failures_df = pd.DataFrame(failures)
        failures_path = f"{output_dir}/failures.csv"
        failures_df.to_csv(failures_path, index=False)
        print(f"✓ Failures report: {failures_path}")
    
    # 4. Overall statistics
    stats_path = f"{output_dir}/overall_statistics.txt"
    with open(stats_path, 'w') as f:
        f.write("BULK IMPORT STATISTICS\n")
        f.write("="*80 + "\n\n")
        f.write(f"Started:  {overall_results['start_time']}\n")
        f.write(f"Finished: {overall_results['end_time']}\n")
        f.write(f"Duration: {overall_results['total_duration_seconds']:.1f}s ({overall_results['total_duration_seconds']/60:.1f} minutes)\n")
        f.write(f"\n")
        f.write(f"Tickers processed: {overall_results['total_tickers']}\n")
        f.write(f"Filings found:     {overall_results['total_filings_found']}\n")
        f.write(f"Filings processed: {overall_results['total_filings_processed']}\n")
        f.write(f"Filings skipped:   {overall_results['total_filings_skipped']}\n")
        f.write(f"Filings failed:    {overall_results['total_filings_failed']}\n")
        f.write(f"\n")
        f.write(f"Statements success: {overall_results['total_statements_success']}\n")
        f.write(f"Statements failed:  {overall_results['total_statements_failed']}\n")
        f.write(f"\n")
        f.write(f"Average time per ticker: {overall_results['average_time_per_ticker']:.1f}s\n")
        
        # Success rate
        if overall_results['total_filings_found'] > 0:
            success_rate = (overall_results['total_filings_processed'] / overall_results['total_filings_found']) * 100
            f.write(f"Success rate: {success_rate:.1f}%\n")
    
    print(f"✓ Statistics: {stats_path}")
    
    # Print final summary
    print("\n" + "="*80)
    print("BULK IMPORT COMPLETE")
    print("="*80)
    print(f"\n📊 Overall Statistics:")
    print(f"   Tickers processed:  {overall_results['total_tickers']}")
    print(f"   Filings found:      {overall_results['total_filings_found']}")
    print(f"   Filings processed:  {overall_results['total_filings_processed']}")
    print(f"   Filings skipped:    {overall_results['total_filings_skipped']}")
    print(f"   Filings failed:     {overall_results['total_filings_failed']}")
    print(f"   Statements success: {overall_results['total_statements_success']}")
    print(f"   Statements failed:  {overall_results['total_statements_failed']}")
    print(f"\n⏱️  Duration: {overall_results['total_duration_seconds']:.1f}s ({overall_results['total_duration_seconds']/60:.1f} minutes)")
    print(f"   Average per ticker: {overall_results['average_time_per_ticker']:.1f}s")
    
    if overall_results['total_filings_found'] > 0:
        success_rate = (overall_results['total_filings_processed'] / overall_results['total_filings_found']) * 100
        print(f"   Success rate: {success_rate:.1f}%")
    
    print(f"\n📁 Reports saved to: {output_dir}/")
    print()
    
    return overall_results


# ============================================================================
# USAGE EXAMPLE
# ============================================================================

if __name__ == "__main__":
    import asyncio
    
    # Example usage
    results = asyncio.run(bulk_import_10k(
        ticker_csv='tickers.csv',
        periods=20,
        use_ai_fallback=False,  # Set to True for better coverage
        skip_existing=True,
        rate_limit_delay=1.0
    ))
