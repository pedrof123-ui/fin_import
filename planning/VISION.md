VISION:

Create a new database for financial statements to store financial statement from Alpha Vantage using API key.
The new database will be large supporting income statement, balance sheet and cash flow statements for potentially thousand of tickers for 20 years and 80 quarters or more depending on the stock. The database needs to be flexible to expand and support other types of data from Alpha Vantage. Make a recommendation for the type of database.

API key for Alpha Vantage is in .env

Documentation for the Alpah Vantage API is at https://www.alphavantage.co/documentation/ as well sample code and output formats.

Please write functions that will download and import into the new database the all financial statements for a user provided single ticker, list of tickers in a csv file or a set/list of tickers from prices.duckdb.

Also write a function for a user to query the database for any single ticker or ticker list with a start and end date. If the user doesn't provide a start and end date, use a default.

Create an update function that will download and update all the tickers in the database with the latest statements if available. We will ran this function routinely either manually or as a cron job.

In the future, we will use the financial data in the the database for our dcf valuation, fundamental valuations, historical fundamental research and investing strategies. The database might be accessed by ai agents as well.

Have the functions log errors, warnings and when sucessfully runs for troubleshooting if needed.

The solution should be production level for an hedge fund or an investment firm.

VERY IMPORTANT: IN BULK DOWNLOADS, THE ALPHA VANTAGE API HAS A LIMITS OF 75 CALLS/MINUTE. MAKE SURE THAT API CALLS DON"T EXCEED 75 CALLS/MINUTE

If you need clarification, feel free to ask questions.











