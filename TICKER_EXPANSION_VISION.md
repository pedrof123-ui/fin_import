GOAL:

The goal is to expand our universe of companies/tickers by adding IWM (Russell 2000) and MDY (S&P Midcap 400) to the av_financials database and fmp_financials database in trade_systems

Special instructions:
1) Use MCP AV MCP server to download the current IWM and MDY ticker constituents
2) Remove ADRs from the list
3) If the IWM and MDY constituents tickers (minus ADRs) are not in the av_financials and/or fmp_financials databases, add the new tickers to the databases. 
4) Backfill av_financials with AV data API with all available historical years from AV. 
5) Backfill fmp_financials with FMP data API with all available historical years from AV.
6) Also add the new tickers to all other supporting database for Finview and Fundamentals Alphas such as Overview, Analyst Estimates, beta and etc
7) Add the tickers to prices database prices.duckdb stock_prices in trade_systems/data and backfill with all available historical prices. FMP has the richest historical stock prices going back to the 1980s for some stocks
8. Please PLAN in phased approach with testing before deeming the phase complete and moving to the next phase.
9. Make sure that changes to break existing code, feature and investing strategies
10. Feel free to ask questions and make recommendations.
11. PLAN to include the new tickers in the Fundamental Strategy after the ingestion and backfill of the new tickers is complete.
