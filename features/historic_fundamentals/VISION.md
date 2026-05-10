VISION:

1. The goal is to create a robust hedge fund or investment industry grade framework or system to track historical fundamentals to use for reports, analysis, equity valuation and investing solutions

2. We will need to calculate, store, add and manipulate historical fundamentals data 
3. The access to the data will be from other python apps and ai agents.
4. The tickers will be all tickers in av_financials.duckdb

3. Intially for each company in av_financial.duckdb:
    1. For each month calculate the Monthly PE = Month-end share price / TTM EPS available (preferrable based on quarterly reported)
    2. Long term median PE (based on the monthly PE)
    3. 25th–75th percentile P/E range
    4. 10th–90th percentile range
    5. Rolling 5-year median P/E
    6. Current PE
    7. Forward 12M PE - based on analyst estimates

5. We will be adding additional fundamental metrics later

6. Create a script and/or functions:
    - Allow the user to query a ticker or a list of tickers and any of the fields of the database. 
    - Update the historical information and calculations. Most likely the script will be run at the end of each month.
    - Backfill all data if one or more tickers are added to the av_financials.duckdb

7. Stocks prices are availabe in /home/pedro/projects/trade_systems/data/prices.duckdb stock_prices

8. Please make recommendation in how to handle storing and the calculation the long term median PE, percentiles or rolling 5-year median PE. Do we store the values in the same database? 

9. We will also want to create a database or table with to store historical analyst estimates from the Alpha Vantage API function=EARNINGS_ESTIMATES more info at https://www.alphavantage.co/documentation/#earnings-estimates . For this Earnings Estimates, we will need script and functions for bulk download, update with latest on a monthly basis, query and bcakfill when a new ticker or tickers are added to tbe database.

10. Please make a recommendation how to organize the framework, data, code and system to meet our goal.

