# Beta

Computes and stores rolling OLS betas for all tracked stocks against VTI (Vanguard Total Stock Market ETF).

## Design choices

| Decision | Choice | Reason |
|---|---|---|
| Market index | VTI | Total market captures small/mid caps over-represented in this universe vs. SPY |
| Window | 2-year daily (504 obs) | Matches common screener convention; more responsive than 5Y monthly |
| Returns | Log returns ln(P_t / P_{t-1}) | Handles compounding correctly for OLS |
| History | Monthly snapshots, full history | Enables point-in-time beta for ML backtesting without look-ahead bias |
| Storage | `ticker_betas` table in `prices.duckdb` | Co-located with source price data |
| Min observations | 126 (~6 months) | Returns None below this threshold; DCF falls back to beta=1.0 |

## Storage schema

Table `ticker_betas` in `/trade_systems/data/prices.duckdb`:

```
ticker        VARCHAR   -- stock ticker
computed_date DATE      -- last trading day of the regression window
window_days   INTEGER   -- 504
beta          DOUBLE    -- OLS slope (stock returns ~ VTI returns)
r_squared     DOUBLE    -- R² of the regression
n_obs         INTEGER   -- actual observations used
PRIMARY KEY (ticker, computed_date, window_days)
```

## Usage

```python
from features.beta.beta import get_beta

# Latest beta
get_beta("AAPL")                              # -> 1.115

# Point-in-time (for backtesting)
get_beta("AAPL", as_of_date=date(2023, 12, 31))  # -> 1.204
```

## CLI

```bash
# Full historical backfill (one-time, or after adding new tickers)
uv run features/beta/beta.py backfill

# Single ticker
uv run features/beta/beta.py backfill --ticker AAPL

# Current-month refresh (cron mode)
uv run features/beta/beta.py refresh

# Print latest beta for a ticker
uv run features/beta/beta.py show AAPL
```

## Daily cron

`update_betas.py` runs `refresh_betas()` daily after prices update. Add to crontab:

```
30 23 * * 1-5  cd /home/pedro/projects/fin_import2 && uv run features/beta/update_betas.py
```

## DCF integration

`dcf/wacc.py::get_beta()` queries the stored beta. The existing fallback to `beta=1.0` is preserved for tickers with no history. The `UserOverrides.beta` override path is unaffected.
