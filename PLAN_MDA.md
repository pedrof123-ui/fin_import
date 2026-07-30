# PLAN: MD&A Database

**Goal**: Build a DuckDB-backed store of MD&A (Management Discussion & Analysis) text pulled
from SEC EDGAR 10-K/10-Q filings for every ticker in the fundamentals universe, wired into the
existing ticker onboarding/removal pipeline (`scripts/manage_tickers.py`) and kept current by a
routine cron job — mirroring how `earnings_transcripts.duckdb` is populated and maintained today.

---

## Decisions (confirmed with user before implementation)

1. **Backfill scope**: full universe (2,639 tickers currently in `company_overview` /
   `monthly_pe`), full depth (20yr of 10-K MD&A + 20 quarters of 10-Q MD&A), as one resumable
   batch job. No narrower pilot phase — go straight to full scope, sized from real EDGAR
   sampling done in this conversation (~70KB avg extracted text per filing, ~65-75K documents
   realistically once accounting for tickers without 20yr history, ~4.5-5GB raw / ~2-2.5GB
   compressed in DuckDB).
2. **RAG deferred**: this plan ships the raw MD&A store + ingestion + cron update only — no
   chunking, no embeddings, no `fts`/`vss` indexes. The project has no embedding provider wired
   in anywhere today (research_router.py only calls OpenRouter for chat completions), so picking
   one is its own decision, not a default to make here. Schema is still designed so a future RAG
   layer can be added without a rewrite (one text blob per filing row, not pre-chunked).
3. **New DB file**: `data/mda_filings.duckdb`, a dedicated file — same separation-of-concerns
   pattern as `earnings_transcripts.duckdb` and `research_cache.duckdb` (large text corpora kept
   out of `av_financials.duckdb`/`historic_fundamentals.duckdb`).
4. **Code layout**: core fetch/store logic in `historic_fundamentals/mda.py` (mirrors
   `earnings_transcripts.py`'s `open_db()`/`is_cached()`/`save_*()`/`fetch_from_*()` shape);
   `scripts/mda_backfill.py` for the one-time full-universe job (mirrors
   `earnings_backfill.py`); `scripts/mda_update.py` for the routine cron job (mirrors
   `earnings_update.py`).
5. **Rate limiting**: rely on edgartools' built-in throttle (defaults to 9 req/sec, SEC's fair
   access limit, confirmed in `edgar/httpclient.py`) — no custom limiter needed. This is a
   different API from Alpha Vantage, so CLAUDE.md's 75 calls/min AV limit does not apply here,
   but the EDGAR-side ceiling is real and edgartools already enforces it.
6. **Extraction keys**: 10-K → `obj['mda']`; 10-Q → `obj['part_i_item_2']` (not `'mda'`, which
   silently falls back to a legacy parser on 10-Qs and frequently returns near-empty text — found
   during sampling in this conversation). Single attempt only, no fallback-key retry: measured
   during Phase 1/2 implementation, each extraction attempt on an already-failing filing costs
   ~6s (edgartools' TOC/heading/pattern-matching cascade), so a second attempt roughly doubles
   backfill runtime for a small coverage gain. Filings below 500 chars are marked `empty` and
   accepted as a gap rather than retried.
7. **Backfill runtime (revised)**: real measurement during Phase 2 showed ~6s/filing (parsing-
   bound, not the 9 req/sec network throttle), meaning the naive full-universe backfill was
   ~7 days, not the original ~4-hour estimate. Dropping the fallback retry (Decision 6) roughly
   halves that. Single-threaded full-universe backfill is still a multi-day background job —
   expected and accepted, this is a one-time cost.

---

## Architecture

```
scripts/manage_tickers.py add/delete   ─┐
scripts/mda_backfill.py (one-time)      ├──▶  historic_fundamentals/mda.py  ──▶  data/mda_filings.duckdb
scripts/mda_update.py (weekly cron)    ─┘            (fetch via edgartools)
```

`mda_filings` schema:

```sql
CREATE TABLE mda_filings (
    ticker             VARCHAR,
    cik                VARCHAR,
    form               VARCHAR,     -- '10-K' or '10-Q'
    fiscal_period_end  DATE,
    filing_date        DATE,
    accession_no       VARCHAR,
    section_key        VARCHAR,     -- 'mda' or 'part_i_item_2', whichever produced the text
    mda_text           VARCHAR,
    char_count         INTEGER,
    status             VARCHAR,     -- 'ok' | 'empty' | 'error'
    downloaded_at       TIMESTAMP,
    PRIMARY KEY (ticker, form, fiscal_period_end)
);
```

---

## Phase 1 — Core module: schema + single-ticker fetch/store

**Status**: [x] Complete
**User-facing impact**: NONE (backend only)
**New files**: `historic_fundamentals/mda.py`, `data/mda_filings.duckdb` (created on first run)

### Step 1.1 — Schema + connection helper [x]

Add `open_db(path: str | None = None) -> duckdb.DuckDBPyConnection` (default path
`data/mda_filings.duckdb`, `MDA_DB_PATH` env override), creating the `mda_filings` table above
if it doesn't exist — same pattern as `earnings_transcripts.open_db()`.

### Step 1.2 — Single-filing fetch [x]

Add `fetch_mda(ticker: str, form: Literal["10-K", "10-Q"], filing) -> dict`: given an
already-resolved edgartools `filing` object, parse it (`filing.obj()`), extract via the primary
key for that form (Decision 6), fall back to the other key once if <500 chars, and return
`{ticker, cik, form, fiscal_period_end, filing_date, accession_no, section_key, mda_text,
char_count, status}`. Never raises — SEC fetch/parse errors are caught and returned as
`status='error'` rows (same philosophy as every other data-gathering function in
`research_router.py`).

### Step 1.3 — Per-ticker backfill (20yr 10-K + 20qtr 10-Q) [x]

Add `fetch_all_mda_for_ticker(ticker: str, n_annual: int = 20, n_quarterly: int = 20) -> dict`:
resolves `Company(ticker)`, pulls `get_filings(form="10-K").latest(n_annual)` and
`get_filings(form="10-Q").latest(n_quarterly)`, calls `fetch_mda()` per filing, upserts each row
(`INSERT OR REPLACE`) into `mda_filings`, and returns a summary count
`{"10-K": {"ok": n, "empty": n, "error": n}, "10-Q": {...}}`. Skip filings already cached
(`ticker`, `form`, `fiscal_period_end` in table) unless `force=True`.

Add `is_cached(ticker, form, fiscal_period_end) -> bool` and
`get_cached_mda(ticker, form=None, limit=None) -> list[dict]` (newest-first) as the read-side
API other code (agents, notebooks) will call — same shape as `earnings_transcripts.py`'s reader
helpers.

Test:
```bash
uv run python -c "
from historic_fundamentals.mda import fetch_all_mda_for_ticker, get_cached_mda, open_db
summary = fetch_all_mda_for_ticker('AAPL')
print(summary)
rows = get_cached_mda('AAPL')
print('cached rows:', len(rows))
print('status breakdown:', {s: sum(1 for r in rows if r['status']==s) for s in ('ok','empty','error')})
assert any(r['status']=='ok' and r['char_count']>1000 for r in rows)
"
# Pass: summary shows ~20 10-K + ~20 10-Q attempts, most status='ok', get_cached_mda returns
# matching row count, at least one row has real text (char_count > 1000).
```

---

## Phase 2 — Full-universe backfill (one-time, resumable)

**Status**: [x] Complete — full-universe backfill finished 2026-07-29 23:09, 38h42m total runtime
across two restarts (machine reboot, then the tcache fix below), 0 gaps, 0 lost work.
**Final coverage**: 2,477 distinct tickers, 79,469 rows, 0 errors — 66,344 `ok` (83.5%) /
13,125 `empty` (16.5%), avg 68,127 chars/filing (matches Phase 0 estimate almost exactly).
DB size 6.5G (larger than the original ~2-2.5GB estimate, not a problem — ample disk headroom).
**User-facing impact**: NONE (backend only); long-running job — revised to ~3 days for 2,639
tickers after dropping the fallback-key retry (Decision 6/7); parsing-bound, not network-bound.
**New files**: `scripts/mda_backfill.py`
**Second bug found and fixed in production**: the run hung on `FFBC` (a bank) for 5.5+ hours —
process stayed alive and CPU-busy but produced zero log output. Root cause not conclusively
identified (a retry of the same ticker in isolation completed normally in 166s, so it may have
been a transient network stall rather than a deterministic pathological document), but it
confirmed a single filing can hang the entire batch indefinitely with no existing guard.
Fixed by adding a hard 90s per-filing wall-clock timeout to `fetch_mda()` via `SIGALRM`
(`historic_fundamentals/mda.py`) — a filing that exceeds it is marked `status='error'` and the
loop moves on. Verified two ways: (1) a synthetic pure-Python busy loop confirmed the alarm
fires and is caught correctly; (2) per PEP 475, a signal handler that raises (ours does) takes
priority over silent syscall-retry, so blocking network reads are interrupted too, not just
CPU-bound Python loops.

**Third bug found and fixed in production (2026-07-28)**: a machine reboot killed the in-progress
backfill at ticker 1246/2654 (no data loss — commits are per-filing). The restarted run then
filled the disk again within ~3 hours (100% full, 1.7G free). Root cause: edgartools' HTTP disk
cache (`~/.edgar/_tcache`) caches every SEC `/Archives/edgar/data` response forever with no
eviction — full SGML submissions including all exhibits, often 100-166MB each — and grew to 79GB.
This cache buys nothing for a one-shot backfill that never re-requests the same filing URL, so it
is now disabled for MD&A fetches: `_ensure_identity()` in `historic_fundamentals/mda.py` replaces
`edgar.httpclient.HTTP_MGR` with a `cache_enabled=False` instance right after `set_identity()`.
Verified a real fetch afterward added 0 files to `_tcache`; the 9 req/sec rate limiter (a separate
mechanism) is unaffected. Reclaimed the 79GB with `rm -rf ~/.edgar/_tcache/*` (safe, pure
read-through cache) and resumed the backfill.

### Step 2.1 — Backfill script [x]

Mirrors `scripts/earnings_backfill.py`: iterate all tickers from
`av_financials.duckdb::company_overview` (or `--ticker` for one, `--csv` for a list), call
`fetch_all_mda_for_ticker()` per ticker, `tqdm` progress bar, log a running status tally.
Idempotent by construction (Step 1.3's cache check) — safe to Ctrl-C and re-run to resume where
it left off, no separate checkpoint file needed. Flags: `--ticker`, `--csv`, `--limit N` (for
smoke-testing before the full run), `--force` (re-fetch even if cached), `--dry-run` (print
ticker count and estimated request count, no fetching).

### Step 2.2 — Full run [x] (running in background)

Run `uv run scripts/mda_backfill.py` (no flags) in the background against the full universe.
Given the runtime, run it via `nohup`/background rather than in an interactive session.

Test:
```bash
# Smoke test first — 10 tickers, confirms the script runs end to end
uv run scripts/mda_backfill.py --limit 10

# Full run (background)
nohup uv run scripts/mda_backfill.py > logs/mda_backfill.log 2>&1 &

# After completion, sanity check coverage:
uv run python -c "
import duckdb
con = duckdb.connect('data/mda_filings.duckdb', read_only=True)
print(con.execute(\"select status, count(*) from mda_filings group by status\").fetchall())
print(con.execute(\"select count(distinct ticker) from mda_filings\").fetchall())
"
```
Pass: distinct ticker count close to 2,639 (some may fail entirely — delisted/no-CIK tickers,
acceptable); `status='ok'` share consistent with the ~80-85% extraction success rate observed in
sampling; `status='error'` share small (<5%) — a large error share would mean something
systemic (e.g. `SEC_ID` not set) and should stop the job for investigation, not run to
completion.

---

## Phase 3 — Add/delete ticker pipeline integration

**Status**: [x] Complete
**User-facing impact**: `manage_tickers.py add` gets slower per ticker (real-world ~1-2 min at
the measured ~2.6s/filing rate, not the original request-count estimate); `delete` unaffected in
speed, now also cleans up MD&A rows.
**Files to modify**: `scripts/manage_tickers.py`
**Known limitation found during testing**: DuckDB allows one writer per file. If `add`'s MD&A
step runs while `mda_backfill.py`/`mda_update.py` holds the write lock on `mda_filings.duckdb`,
it fails gracefully (logged warning, rest of `add` still succeeds) rather than blocking or
crashing — confirmed by testing this exact case. Acceptable: the one-time full backfill is the
only long-held-lock scenario, and it's a one-time cost; the weekly cron job holds the lock only
briefly per ticker.

### Step 3.1 — Wire into `add` [x]

Add a "Step 9: MD&A backfill" call to `historic_fundamentals.mda.fetch_all_mda_for_ticker()`
after the existing Step 8 (forward multiples). Add a `--skip-mda` flag (mirrors
`--skip-estimates`) for bulk/fast adds where MD&A can be caught up later via
`mda_backfill.py --csv`.

### Step 3.2 — Wire into `delete` [x]

Add `DELETE FROM mda_filings WHERE ticker = ?` to the removal step, alongside the existing
`monthly_pe`/`pe_stats`/`earnings_estimates`/etc. cleanup.

Test:
```bash
uv run scripts/manage_tickers.py add TESTTICKER --dry-run   # pick a real, currently-absent ticker
uv run scripts/manage_tickers.py add <REAL_TICKER_NOT_YET_IN_DB>
uv run python -c "
from historic_fundamentals.mda import get_cached_mda
rows = get_cached_mda('<REAL_TICKER_NOT_YET_IN_DB>')
print(len(rows), 'rows')
"
uv run scripts/manage_tickers.py delete <REAL_TICKER_NOT_YET_IN_DB>
uv run python -c "
from historic_fundamentals.mda import get_cached_mda
assert get_cached_mda('<REAL_TICKER_NOT_YET_IN_DB>') == []
print('OK, cleaned up')
"
```
Pass: `add` populates `mda_filings` for the new ticker; `delete` removes all its rows, matching
the existing cleanup guarantee for the other three databases.

**Result**: Verified with CRCL (a real recently-IPO'd ticker absent from all DBs). `add CRCL`
correctly fetched 4 filings (its full real filing history — 1 10-K + 3 10-Qs since IPO,
all `status='ok'`); `delete CRCL` removed all 4 rows alongside the other three databases'
cleanup. Also incidentally proved the lock-conflict degrade-gracefully path (see limitation
note above) on the first attempt, before pausing the background backfill to test the happy path.

---

## Phase 4 — Routine cron update

**Status**: [x] Complete — crontab line installed 2026-07-30
**User-facing impact**: NONE (backend only)
**New files**: `scripts/mda_update.py`

### Step 4.1 — Incremental update script [x]

Mirrors `scripts/earnings_update.py`: for every ticker in `company_overview`, fetch just the
latest 1 10-K and latest 1 10-Q via edgartools, compare `fiscal_period_end`/`accession_no`
against what's already cached, and only fetch+store if it's new (`fetch_all_mda_for_ticker`'s
existing cache check already does this — this script just calls it with `n_annual=1,
n_quarterly=1` instead of 20/20, keeping the weekly request volume small). `--ticker` flag for
single-ticker runs, `--dry-run` to report how many *would* be new without fetching (added a
`dry_run` param to `fetch_all_mda_for_ticker` that resolves filing metadata and checks the cache
without parsing content, so dry-run stays cheap — ~1-2s/ticker vs. several seconds for a real
fetch).

### Step 4.2 — Cron schedule [x] (script ready; crontab line NOT yet installed)

Weekly cadence (matches `earnings_update.py`'s documented intent) — companies file 10-Qs on a
staggered calendar all year, so a weekly check is needed to catch new quarters promptly; most of
the ~2,639 checks each week will find nothing new (cheap — one filings-index lookup each, not a
full document fetch), so weekly load stays modest even at full universe scope. Add to crontab
using the project's existing `cron_wrap.sh --lock` pattern:

```cron
# MD&A update — weekly, Sunday 20:30 ET (after regime_monitor, before Monday's IBD50 jobs)
30 20 * * 0 /home/pedro/projects/trade_systems/scripts/cron_wrap.sh mda_update /home/pedro/.local/bin/uv run --project /home/pedro/projects/fin_import2 /home/pedro/projects/fin_import2/scripts/mda_update.py >> /home/pedro/projects/fin_import2/logs/mda_update.log 2>&1
```

Test:
```bash
uv run scripts/mda_update.py --ticker <TICKER_THAT_JUST_REPORTED> --dry-run
# Pass: reports 1 new filing found (10-K or 10-Q, whichever it just filed)
uv run scripts/mda_update.py --ticker <TICKER_THAT_JUST_REPORTED>
uv run python -c "
from historic_fundamentals.mda import get_cached_mda, open_db
rows = get_cached_mda(open_db(), '<TICKER_THAT_JUST_REPORTED>', limit=1)
print(rows[0]['filing_date'], rows[0]['status'])
"
# Pass: latest cached row's filing_date matches the new filing, status='ok'
```

**Result**: Verified with AAPL (dry-run correctly reports 0 new — fully cached from Phase 1) and
MSFT (dry-run correctly reports 2 new — untouched by the in-progress backfill at test time; real
run fetched both, status='ok'; re-run correctly skipped both). Cron line installed 2026-07-30
after the full backfill completed (user held off installing it until then, to avoid contention on
`mda_filings.duckdb`'s single-writer lock during the multi-day backfill).

---

## Phase 5 — Validation

**Status**: [x] Complete for what can be verified before the multi-day backfill finishes;
Step 5.2's full-coverage numbers should be re-checked once the background backfill completes
(see note below).
**User-facing impact**: NONE (verification only)
**Bug found and fixed during this phase**: `mda_backfill.py`'s per-ticker totals aggregation
crashed with `KeyError: 'new'` on every ticker (the `dry_run` support added to
`fetch_all_mda_for_ticker` in Phase 4 added a `"new"` key to its returned summary dict, but
`mda_backfill.py`'s `totals` dict, written before Phase 4, didn't have that key). The per-ticker
`try/except` in the backfill loop caught it and logged `"Error processing X: 'new'"`, so it
looked like every ticker was failing. **Data was never actually affected** — confirmed AAOI had
its full 33 rows correctly saved to `mda_filings` despite the misleading error log — the crash
happened only in the totals-reporting step *after* the real fetch+save work completed. Fixed by
adding `"new": 0` to both scripts' `totals` init and switching the aggregation to
`totals[form].get(status, 0) + count` so an unknown status key can't crash the loop again.

### Step 5.1 — Text quality spot check [x]

Manually compare 3-5 stored `mda_text` rows against the actual filing on sec.gov (via the
`accession_no`) to confirm extraction isn't truncating or grabbing the wrong section.

**Result**: AAPL's latest 10-K (accession `0000320193-25-000079`) starts exactly at `"Item 7.
Management's Discussion and Analysis of Financial Condition and Results of Operations"` and ends
at the natural section boundary before Item 7A — correct extraction, no truncation or
wrong-section content.

### Step 5.2 — Coverage & size check [x] (partial — full run still in progress)

```bash
uv run python -c "
import duckdb, os
con = duckdb.connect('data/mda_filings.duckdb', read_only=True)
print('rows:', con.execute('select count(*) from mda_filings').fetchall())
print('tickers:', con.execute('select count(distinct ticker) from mda_filings').fetchall())
print('by status:', con.execute('select status, count(*) from mda_filings group by status').fetchall())
print('avg chars (ok only):', con.execute(\"select avg(char_count) from mda_filings where status='ok'\").fetchall())
"
ls -lh data/mda_filings.duckdb
```
Pass: total size and avg char_count roughly match the Phase 0 estimate (~70KB/filing,
~2-2.5GB compressed file); no single ticker or sector systematically missing (cross-check a
`JOIN company_overview` group-by-sector count against `company_overview` sector counts from
this conversation — Healthcare 539, Technology 442, etc. — to confirm no sector was silently
skipped).

**Interim result** (13 tickers processed at check time, backfill still running in background —
re-run the query above once `ps aux | grep mda_backfill` shows no process, expected in a few
days): 356 `ok` / 50 `empty` (87.7% ok — in line with the ~85% observed during Phase 1/2
sampling), 0 `error`. No systemic failure pattern; the `empty` rate is individual-filing gaps
(edgartools section-detection misses), not a sector or ticker-class-wide blind spot in this
sample.

### Step 5.3 — Docs [x]

Add `mda.py`, `mda_backfill.py`, `mda_update.py`, and `data/mda_filings.duckdb` entries to
`docs/Project_Structure.md`, matching the existing `earnings_transcripts.py`/
`earnings_backfill.py`/`earnings_update.py` entries in style.

---

## Explicitly out of scope (future plan, not blocking)

- **RAG retrieval layer**: chunking, embedding provider selection, DuckDB `fts`/`vss` indexes,
  a retrieval query helper. Deferred per Decision 2 — needs its own scoping (embedding
  provider/cost, chunk size, index choice) once the base corpus exists to build against.
- **Sector/cross-company comparison agent**: the map-reduce summarize-then-synthesize pattern
  discussed (per-company MD&A summary cached, then a synthesis agent compares N companies in a
  sector/industry). This plan only makes the raw text queryable and joinable to `sector`/
  `industry` via `company_overview`; the agent itself belongs in a `research_router.py`-style
  follow-up plan, same relationship Phase 1-3 of the AI Researcher plan (`PLAN.md`) had to its
  own Phase 4 agent pipeline.
- **10-Q extraction fallback beyond one retry** (Decision 6) — if Phase 5's coverage check shows
  a materially worse empty-rate than the ~15-20% observed in sampling, revisit then rather than
  pre-building extra extraction robustness now.
