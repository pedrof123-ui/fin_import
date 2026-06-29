GOAL: The goal is to create a database or table of stock ticker beta's based on the VTI ETF Vanguard Total Stock Market ETF (VTI) 

1. Backfill all historic VTI daily prices in the etf table in /trade_systems/data/prices.duckdb
2. Like the other tickers, yfinance script should handle daily udpates
3. Create scripts or functions to update, query and handle ticker additions and deletions
4. The beta table or database and scripts/functions need to flexible so that they can integrate with existing and future feature requiring beta values
5. We will replace the beta currently used in the WACC calculation of the dcf feature
6. Feel free to ask questions and make recommendations to improve
