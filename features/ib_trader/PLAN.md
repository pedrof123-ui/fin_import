# IB Trader — Implementation Plan

## Decisions

| Item | Decision | Rationale |
|---|---|---|
| Library | `ib_async` | Maintained Python 3.12+ fork of ib_insync; already in pyproject.toml |
| Module location | `ib_trader/` at fin_import2 root | Importable by other projects via `uv pip install -e /path/to/fin_import2`; no separate repo needed now |
| Default order type | MOC (Market-on-Close) for buys and sells | Strategy returns are close-to-close; MOC matches the backtest reference for both legs |
| Interface | CLI (batch rebalance) + REPL (ad-hoc orders) | Batch for month-end automation; REPL for manual overrides and emergency exits |
| Rebalance workflow | Full rebalance | Fetch NAV + current positions from IB, diff vs target, place buy/sell orders |
| Config | `.env` + env vars | Consistent with all other scripts in the project |
| Fractional shares | No — `math.floor` to whole shares | IB account does not support fractional shares |
| LMT price (batch) | IB live mid-price | Auto-computed; per-ticker overrides only available in REPL |
| LMT price (REPL) | User-specified per ticker | `sell MSFT 30 LMT 450.00` |
| Auto-exit dropped positions | Yes | Required to match backtest; dry-run shows all exits before confirmation |
| Strategy tag | `orderRef` field on IB Order | Default `"fundamentals_alpha"`; overridable by other callers for multi-strategy auditing |

---

## Module Layout

```
ib_trader/
    __init__.py          # public re-exports: IBClient, rebalance, place_order
    client.py            # IB connection wrapper; account + position fetching
    orders.py            # order factory (market, limit, MOC) + order status
    portfolio.py         # diff current positions vs target → order list
    rebalance.py         # end-to-end rebalance: load scores → diff → submit
    interactive.py       # REPL loop with ad-hoc order commands

scripts/
    rebalance.py         # CLI entry point: --scores, --dry-run, --top, --order-type
```

---

## Configuration (.env additions)

```dotenv
IB_HOST=127.0.0.1
IB_PORT=7497          # paper: 7497 | live: 7496
IB_CLIENT_ID=1
IB_ACCOUNT=           # auto-detect from IB if empty
```

Switch to live by changing `IB_PORT=7496`. All other code is identical.

---

## Data Contract

The IB trader consumes output from `scripts/score_live.py` in two ways:

**Option A — direct import (preferred for scripts):**
```python
from scripts.score_live import score_universe
ranked = score_universe(hf_db_path, av_db_path, model_path=None)
# Use ranked DataFrame: ticker, alloc_pct (float 0–1 range... see note below)
```

**Option B — read the CSV:**
```python
df = pd.read_csv("docs/live_scores_YYYYMMDD_*.csv", comment="#")
portfolio = df[df["alloc_pct"].notna() & (df["alloc_pct"] != "")].copy()
# Parse formatted strings: portfolio["alloc_pct"] = portfolio["alloc_pct"].str.rstrip("%").astype(float) / 100
# Parse formatted prices: portfolio["price"] = portfolio["price"].astype(float)
```

> Note: `alloc_pct` in the raw DataFrame from `score_universe()` is already a float (0–100). In the CSV it is a formatted string like `"3.0%"`. The CLI will detect which format it is reading.

**Key fields consumed by the trader:**

| Field | Meaning | Trading use |
|---|---|---|
| `ticker` | Symbol | IB contract lookup |
| `alloc_pct` | Target % of NAV (post-regime) | `target_shares = floor(alloc_pct * NAV / price)` |
| `price` | Last known price | Initial share estimate; IB live price used to confirm |
| `weight_pct` | Pre-regime weight | Display / audit only |

Stocks not in the top-N portfolio have `alloc_pct = NaN` and are treated as target weight = 0 (exit position if held).

---

## Rebalancing Algorithm

```
1. Connect to IB (client.py)
2. Fetch NetLiquidation (account NAV) from accountSummary
3. Fetch current positions → Dict[ticker, current_shares]
4. Load target portfolio from CSV or score_universe()
   → Dict[ticker, alloc_pct]   (only non-NaN rows)
5. For each ticker in union(current, target):
     target_shares  = floor(alloc_pct * NAV / live_price)   if in target else 0
     current_shares = current positions map                   if in current else 0
     delta          = target_shares - current_shares
     if delta > 0:  generate BUY  order for delta shares
     if delta < 0:  generate SELL order for |delta| shares
     if delta == 0: no action
6. Preview order blotter (dry-run)
7. On confirmation, submit all orders
8. Log fills, rejections, and remaining open orders
```

> Live prices for step 5 are fetched from IB market data to get accurate share counts. If market data is unavailable (outside hours), the CSV `price` column is used as a fallback.

---

## Phase Plan

### Phase 1 — Client foundation (`ib_trader/client.py`)

**Goal:** Connect, fetch account info and positions.

Deliverables:
- `IBClient` class: `connect()`, `disconnect()`, context manager (`__enter__`/`__exit__`)
- `get_nav() -> float` — NetLiquidation from `accountSummary`
- `get_positions() -> dict[str, float]` — ticker → shares held
- `get_live_price(ticker) -> float | None` — snapshot market data; returns None on timeout
- `qualify_contract(ticker) -> Contract` — resolves US stock contract via `qualifyContracts`

Config loaded from env: `IB_HOST`, `IB_PORT`, `IB_CLIENT_ID`, `IB_ACCOUNT`.

Connection test: `uv run -c "from ib_trader.client import IBClient; ib = IBClient(); ib.connect(); print(ib.get_nav()); ib.disconnect()"`

---

### Phase 2 — Order factory (`ib_trader/orders.py`)

**Goal:** Generate and place IB orders for all three types.

Deliverables:
- `make_order(action, qty, order_type, limit_price=None, strategy="fundamentals_alpha") -> Order`
  - `order_type` in `{"MKT", "LMT", "MOC"}`
  - For LMT: `limit_price` required (REPL: user-specified; batch CLI: IB live mid-price)
  - For MOC: time-in-force = `"DAY"`, orderType = `"MOC"` (used for both buys and sells)
  - `strategy` written to IB `orderRef` field for blotter attribution
- `place_order(ib, ticker, action, qty, order_type, limit_price=None, strategy="fundamentals_alpha") -> Trade`
- `get_live_midprice(ib, contract) -> float | None` — used as auto limit price in batch LMT mode
- `cancel_all_open_orders(ib)` — safety utility
- `get_order_status(ib) -> list[dict]` — open orders summary

---

### Phase 3 — Portfolio reconciliation (`ib_trader/portfolio.py`)

**Goal:** Compute diff between current IB state and target portfolio.

Deliverables:
- `build_target(ranked_df, nav, price_override=None) -> dict[str, int]`
  - Input: raw DataFrame from `score_universe()` (or parsed CSV)
  - Computes target shares per ticker using `alloc_pct * nav / price`
  - `price_override`: dict of live IB prices (falls back to CSV price column)
- `diff_portfolio(current, target) -> list[OrderSpec]`
  - `OrderSpec = namedtuple("OrderSpec", ["ticker", "action", "qty"])`
  - Returns BUY specs (target > current) and SELL specs (target < current)
  - Tickers in `current` but not in `target` → target = 0 → full SELL (auto-exit dropped positions)
  - Excludes zero-delta positions
- `summarise_diff(specs, prices) -> pd.DataFrame` — human-readable blotter for preview

---

### Phase 4 — End-to-end rebalancer (`ib_trader/rebalance.py`)

**Goal:** Orchestrate the full rebalance: load scores → diff → submit.

Deliverables:
- `run_rebalance(scores_path, order_type="MOC", dry_run=True, top_n=25) -> pd.DataFrame`
  - Loads scores from CSV path (or calls `score_universe()` if path is None)
  - Connects to IB, fetches NAV + positions + live prices
  - Builds target, diffs, submits orders (or prints blotter if dry_run=True)
  - Returns filled blotter DataFrame for logging
- Prints: NAV, regime, current portfolio value, target portfolio, order blotter

---

### Phase 5 — CLI entry point (`scripts/rebalance.py`)

**Goal:** One command to do a full rebalance.

```
uv run scripts/rebalance.py --scores docs/live_scores_20260519_rf_vw_gr_top_n_25.csv
uv run scripts/rebalance.py --dry-run
uv run scripts/rebalance.py --order-type LMT
uv run scripts/rebalance.py --top 10
uv run scripts/rebalance.py --cancel-all    # cancel all open orders
uv run scripts/rebalance.py --status        # show current positions + open orders
```

Flags:
| Flag | Default | Description |
|---|---|---|
| `--scores PATH` | None (runs scorer live) | Path to live_scores CSV |
| `--dry-run` | on | Preview only; no orders submitted |
| `--order-type` | MOC | MKT, LMT, or MOC |
| `--top N` | 25 | Portfolio size |
| `--cancel-all` | off | Cancel all open IB orders and exit |
| `--status` | off | Show positions + open orders and exit |
| `--verbose` | off | Debug logging |

Always defaults to `--dry-run`. Requires explicit `--no-dry-run` to submit real orders.

---

### Phase 6 — Interactive REPL (`ib_trader/interactive.py` + `scripts/ib_repl.py`)

**Goal:** Ad-hoc order placement and inspection without editing scripts.

Commands:
```
> status                        — show positions, NAV, open orders
> buy AAPL 50 MOC               — buy 50 shares of AAPL at MOC
> sell MSFT 30 LMT 450.00       — sell 30 MSFT with $450 limit
> cancel <order_id>             — cancel a specific open order
> cancel all                    — cancel all open orders
> preview                       — show rebalance diff without submitting
> rebalance                     — run full rebalance (dry-run by default)
> rebalance --confirm            — submit orders after preview
> quote AAPL                    — show live bid/ask/last
> help                          — list commands
> quit / exit
```

Launch: `uv run scripts/ib_repl.py`

---

## Safety Controls

1. **Dry-run by default** — no order is submitted unless `--no-dry-run` (CLI) or `--confirm` (REPL) is explicitly passed
2. **Paper vs live gate** — REPL prints a warning banner when `IB_PORT=7496` (live account)
3. **Max order size** — configurable `MAX_SINGLE_ORDER_SHARES` env var (default 10,000); orders above this require manual confirmation
4. **MOC cutoff warning** — warn if submitting MOC orders after 15:45 ET (IB cutoff is 15:50 ET)
5. **Cancel-before-rebalance** — `run_rebalance()` cancels any existing open orders for tickers in the target before submitting new ones

---

## Paper Testing Checklist (pre-live)

- [ ] Connect to paper TWS (127.0.0.1:7497) and verify `get_nav()` returns expected value
- [ ] Verify `get_positions()` matches TWS Portfolio tab
- [ ] Place a MOC order for 1 share of a liquid stock and confirm it fills at close
- [ ] Place a LMT order and verify cancel works
- [ ] Run full dry-run rebalance against last live_scores CSV; verify blotter is sensible
- [ ] Run full paper rebalance with `--no-dry-run`; verify fills match blotter
- [ ] Verify REPL `status` and `buy/sell` commands work end-to-end
- [ ] Verify REPL `cancel all` clears all open orders

---

## Open Questions (already answered)

| Question | Answer |
|---|---|
| Module location | `ib_trader/` at fin_import2 root |
| Primary workflow | Full rebalance |
| Default order type | MOC |
| Interface | CLI + REPL |

## All Decisions Resolved

| Question | Decision | Rationale |
|---|---|---|
| LMT price source | User-specified per ticker (REPL: `sell MSFT 30 LMT 450.00`); live mid-price auto-used in batch CLI `--order-type LMT` | Per-ticker control in REPL; mid-price is the only sensible batch fallback |
| Fractional shares | No — round down to whole shares (`math.floor`) | IB account does not use fractional shares |
| MOC for sells | Yes — use MOC for sells by default | Backtest returns are close-to-close; exiting at MOC matches the performance baseline. REPL allows `sell TICKER QTY MKT` for emergency overrides |
| Position exits | Auto-exit dropped positions (full rebalance) | The backtest exits anything not in top-N each month; deviating from this breaks strategy fidelity. Dry-run preview shows all exits before confirmation |
| Strategy tag | Yes — populate IB `orderRef` with strategy name | One field, zero cost, enables multi-strategy auditing in TWS blotter and account statements. Default: `"fundamentals_alpha"` |
