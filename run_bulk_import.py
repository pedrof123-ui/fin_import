#!/usr/bin/env python3
"""
Bulk Import Runner Script
Standalone script to run bulk 10-K import with command line arguments

Usage:
    python run_bulk_import.py tickers.csv
    python run_bulk_import.py tickers.csv --periods 10
    python run_bulk_import.py tickers.csv --periods 20 --ai
    
    # With uv:
    uv run run_bulk_import.py tickers.csv
"""

import asyncio
import argparse
import sys
from pathlib import Path

from bulk_import_10k import bulk_import_10k


def main():
    """Main entry point with argument parsing"""
    
    parser = argparse.ArgumentParser(
        description='Bulk import 10-K statements from SEC EDGAR',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s tickers.csv
  %(prog)s tickers.csv --periods 10
  %(prog)s tickers.csv --periods 20 --ai --delay 0.5
  %(prog)s tickers.csv --no-skip --output my_results
        """
    )
    
    # Required argument
    parser.add_argument(
        'ticker_csv',
        help='Path to CSV file with ticker list'
    )
    
    # Optional arguments
    parser.add_argument(
        '--periods',
        type=int,
        default=20,
        help='Number of years to import per ticker (default: 20)'
    )
    
    parser.add_argument(
        '--db',
        default='data/financial_statements.duckdb',
        help='Database file path (default: financial_statements.duckdb)'
    )
    
    parser.add_argument(
        '--log',
        default='bulk_import.log',
        help='Log file path (default: bulk_import.log)'
    )
    
    parser.add_argument(
        '--output',
        default='./bulk_import_results',
        help='Output directory for reports (default: ./bulk_import_results)'
    )
    
    parser.add_argument(
        '--ai',
        action='store_true',
        help='Enable AI fallback for better coverage (slower)'
    )
    
    parser.add_argument(
        '--no-skip',
        action='store_true',
        help='Re-import existing filings (default: skip existing)'
    )
    
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay between requests in seconds (default: 1.0)'
    )
    
    args = parser.parse_args()
    
    # Validate ticker CSV exists
    if not Path(args.ticker_csv).exists():
        print(f"❌ Error: Ticker CSV not found: {args.ticker_csv}")
        sys.exit(1)
    
    # Display configuration
    print("="*80)
    print("BULK IMPORT CONFIGURATION")
    print("="*80)
    print(f"Ticker CSV:       {args.ticker_csv}")
    print(f"Periods:          {args.periods}")
    print(f"Database:         {args.db}")
    print(f"AI Fallback:      {'Enabled' if args.ai else 'Disabled'}")
    print(f"Skip Existing:    {'No' if args.no_skip else 'Yes'}")
    print(f"Rate Limit:       {args.delay}s")
    print(f"Output Dir:       {args.output}")
    print(f"Log File:         {args.log}")
    print("="*80)
    print()
    
    # Confirm before proceeding
    try:
        response = input("Proceed with import? [y/N]: ")
        if response.lower() not in ['y', 'yes']:
            print("❌ Import cancelled")
            sys.exit(0)
    except KeyboardInterrupt:
        print("\n❌ Import cancelled")
        sys.exit(0)
    
    print()
    
    # Run bulk import
    try:
        results = asyncio.run(bulk_import_10k(
            ticker_csv=args.ticker_csv,
            periods=args.periods,
            db_path=args.db,
            log_file=args.log,
            output_dir=args.output,
            use_ai_fallback=args.ai,
            skip_existing=not args.no_skip,
            rate_limit_delay=args.delay
        ))
        
        # Exit with appropriate code
        if results['total_filings_failed'] == 0:
            sys.exit(0)  # Success
        elif results['total_filings_processed'] > 0:
            sys.exit(0)  # Partial success
        else:
            sys.exit(1)  # Complete failure
            
    except KeyboardInterrupt:
        print("\n\n❌ Import interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
