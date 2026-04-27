VISION:

1. Create a discounted cash flow (DCF) valuation feature to valuate stocks in the database
2. The DCF feature should appear as a new tab in the web UI
3. The DCF should use the financials in financial_statements.duckdb
4. Display the an income statement, balance sheet and cash flow for the last five years and the proforma for the 5 years growth period. Include only the relevant line items for the valuation
5. Compare the valuation value with the latest closing stock price. Stock prices can be found in /trade_systems/data/prices.duckdb
6. If you recommendations to improve this VISION, please tell me.


DCF Model:
1. 5 year growth period followed by a perpetual terminal period
2. Use statsmodel time series models to forecast the next 8 quarters (2 years) needed income statement and balance sheet line items and linear regression for the following 3 years of the growth period. Use the last year for the steady state terminal value.
3. Allow user overwrite the model calculated growth rates, margins and ratios for the 5 year growth period and perpetual steady state if so the user desires.
4. Use yfinance to download stock beta
5. Use a defaul market risk premium but allow the user to overwrite in the UI if needed
6. Use financials to estimate the cost of debt, tax rate
7. Use US 10Y Treasure interest rate as risk free rate. The rate can be found /trade_systems/data/fred.duckdb and the indicator symbol is "DGS10"
8. Display the WACC calculations, company estimated cost of debt, tax rate and all other relevant assumptions 