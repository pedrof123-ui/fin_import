VISION:

1. Create a module that uses Interactive Brokers TWS API to place trades, get account information, positions, portfolio information, news and other data available with throught the API

2. Initially the primary purpose is to place buy and sell orders of tickers for the fundamentals alpha stratgy end of month portfolio score list. However it needs to be flexible to accept orders from other strategies and even from a user command.

3. It needs to support different types of orders such as limit, market and MOC.

4. I would like you recommendation about in which folder to place the module because it will be used by different projects. For example, it will be used by fundementals alpha in fin_import2  or trade_systems

5. I have installed uv run ib_async and downloaded twsapi from https://interactivebrokers.github.io/# . I don't know what you will need. I leave it up to you to recommend how to implement

6. TWS API documentation can be found at https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/#api-introduction

7. While in development and testing will be using the IB paper accounts. We will also be using the paper account to test strategies before going live on the real brokerage account.

8. TWS desktop for the paper account is open and API connects with 127.0.0.1 7497.

9. Please develop an implmentation plan PLAN.md

10. Let me know if you have any questions or recommendations to improve the module

NEW FEATURE  - trading strategy portfolio tracker

1. The goal is develop a tracking feature or module to track trades (dates, open prices, closing prices, P&L per trade), total current value (equities + cash), P&L short term, P&L long term, realized gains Short term and long term,  short term capital gains tax (assume 24% tax rate), long term capital gains tax (assume 15% tax rate), open positions, weekly, monthly, ytd and 1 year and since inception performance, actual sharpe ratio, sortino, beta, strategy name and real performance versus predicted model performance.

2. The solution needs flexible to support Fundamentals Alpha, ibd 50 in trade_systems and as well as future strategies

3. Develop python functions for a user to query the tracking database from a jupyther notebook.

4. Create a function that performs a snapshot report of the strategy real performance

5. Let me know if you have any questions or recommendations to improve the module
