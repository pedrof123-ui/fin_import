# MD&A Feature Extraction Sweep — Specification

Status: implemented (see PLAN_MDA_FEATURES.md for per-phase status)
Date: 2026-08-09

## Goal

Extract five structured features from every post-2016 10-K MD&A filing pair (current year
+ prior year) in `data/mda_filings.duckdb` using a local LLM (Ollama, Qwen3 8B), running
nightly 23:00-03:00 local time, with a daily Telegram progress report. The resulting
feature table feeds (a) candidate factors for the monthly_pe gauntlet and (b) the
guidance_mda_analyst / earnings_mda_historian agents.

## Why local / why these parameters (measured 2026-08-09)

- OpenRouter DeepSeek V4 Flash would cost ~$185 per full sweep; rejected on budget.
- Qwen3 8B Q4 runs 100% on the RTX 4060 8GB only with OLLAMA_FLASH_ATTENTION=1,
  OLLAMA_KV_CACHE_TYPE=q8_0 and num_ctx 16384 (6.7 GB). Default config spills 24% to
  CPU and runs 3x slower.
- Thinking mode is mandatory. Without it the model scored PTON/LUMN/VFC disaster-year
  filings as guidance=raised. With it, PTON FY2022 correctly scores
  lowered/tone -2/new_risk 3/hedging +2. Cost: ~40s/pair vs ~12s.
- Volume: ~18,150 post-2016 10-K pairs. At ~40s/pair in a 4h window: ~340 pairs/night,
  ~53 nights. The window is configurable to shorten this later.

## Components

### 1. `scripts/mda_feature_sweep.py` — nightly extraction runner

Input pairs query (against `data/mda_filings.duckdb`, read-only, connection closed
immediately after fetching the work list to avoid holding a lock against the weekly
Sunday 20:30 mda_update job):

- form='10-K', status='ok', mda_text not null, filing_date >= 2016-01-01
- prior filing: same ticker, form='10-K', status='ok', fiscal_period_end between 330 and
  400 days before the current one; if multiple match, the closest to 365 days
- anti-join against already-extracted rows (same ticker + fiscal_period_end +
  prompt_version) in the output DB
- ordered by filing_date DESC (newest first: recent features become usable by the
  research agents before the backfill completes)

Per pair:

- Truncate each MD&A to 24,000 chars (fits 2 filings + instructions in num_ctx 16384).
- Call Ollama `/api/chat`: model qwen3:8b, think=true, temperature 0, num_ctx 16384,
  keep_alive 15m, `format` = the JSON schema below (schema-constrained decoding; a
  response that still fails to parse or violates enum/bounds is recorded as an error,
  never written as a feature row).
- Insert one row into the output table; update the status JSON.

Output DB `data/mda_features.duckdb`, table `mda_features`:

| column | type | notes |
|---|---|---|
| ticker | VARCHAR | PK part |
| form | VARCHAR | PK part ('10-K') |
| fiscal_period_end | DATE | PK part (current filing) |
| prompt_version | VARCHAR | PK part ('v1.1') |
| prior_fiscal_period_end | DATE | |
| filing_date | DATE | point-in-time key for any factor join |
| accession_no | VARCHAR | |
| guidance_direction | VARCHAR | raised/maintained/lowered/withdrawn/none_given |
| tone_delta | TINYINT | -2..+2 |
| new_risk_language | TINYINT | 0..3 |
| specificity | TINYINT | 0..3 |
| hedging_change | TINYINT | -2..+2 |
| rationale | VARCHAR | one sentence of evidence |
| model | VARCHAR | 'qwen3:8b' |
| cur_chars | INTEGER | pre-truncation length |
| prior_chars | INTEGER | pre-truncation length |
| elapsed_s | DOUBLE | |
| extracted_at | TIMESTAMP | |

Prompt v1.1 (the five features; full text lives in the script):

- guidance_direction is defined as the direction of managements forward-looking
  OUTLOOK LANGUAGE vs the prior filing (MD&A rarely contains formal guidance; v1.0
  scoring of literal guidance produced "raised" for deteriorating companies).
- tone_delta, new_risk_language, specificity, hedging_change as in the prototype.
- The model must base answers only on the supplied text.

Window/scheduling behavior:

- Started by cron at 23:00; before each pair the runner checks the clock and exits
  cleanly once past --window-end (default 03:00, i.e. next day). An in-flight call is
  allowed to finish (~1 min overshoot max).
- Resumable by construction: killing it at any point loses at most the in-flight pair.
  Laptop sleep/reboot just pauses progress.
- If the Ollama server is not responding, the runner starts `ollama serve` itself with
  the required env vars (laptop reboots leave no server running: there is no enabled
  systemd unit).
- 5 consecutive per-pair errors abort the night (protects against a wedged server);
  isolated errors are logged and skipped.
- All paths are absolute, derived from `Path(__file__)` — never cwd-relative (cron jobs
  in this repo have failed twice on cwd/PATH assumptions).

Flags: `--window-end HH:MM` (default 03:00), `--limit N` (smoke tests),
`--validate` (run the 8 fixed validation pairs, print a table, write nothing, exit
non-zero if the discrimination gate fails).

### 2. Status file `data/mda_sweep_status.json`

Rewritten after every pair. Single source of truth for "is it working right now":

```json
{
  "run_started": "...", "last_update": "...", "window_end": "03:00",
  "pairs_total": 18151, "pairs_done_total": 123, "pairs_tonight": 123,
  "errors_tonight": 0, "avg_s_per_pair": 39.7,
  "eta_nights": 52, "eta_date": "2026-09-30",
  "last_pair": "NVDA 2026-01-25", "state": "running|finished|aborted"
}
```

### 3. `scripts/mda_sweep_report.py` — daily Telegram report

Cron at 03:10, after the window closes. Reads the status JSON + a count from
`mda_features.duckdb`, sends one message via the Telegram Bot API:

- token: sourced from `~/.claude/channels/telegram/.env` (TELEGRAM_BOT_TOKEN); never
  hardcoded, never logged
- chat_id: 8351706654 (from `~/.claude/channels/telegram/access.json` allowFrom)
- content: pairs tonight, errors, cumulative done/total with %, avg s/pair, ETA date,
  state
- Failure states are reported, not silenced: if the status file shows no run tonight,
  or state=aborted, the message says so explicitly. If the Telegram send itself fails,
  the script exits non-zero so cron_wrap.sh logs it and raises a desktop notification.

### 4. Cron entries (local time, EDT)

```
0 23 * * * cron_wrap.sh mda_feature_sweep <uv> run --project <repo> <repo>/scripts/mda_feature_sweep.py >> <repo>/logs/mda_feature_sweep.log 2>&1
10 3 * * * cron_wrap.sh mda_sweep_report <uv> run --project <repo> <repo>/scripts/mda_sweep_report.py >> <repo>/logs/mda_sweep_report.log 2>&1
```

with `<uv>` = /home/pedro/.local/bin/uv (absolute, cron has no PATH),
`<repo>` = /home/pedro/projects/fin_import2. The sweep job deliberately has no --lock:
it must not queue behind (or block) the ib_tracker jobs; it touches only its own DB.

## Validation gates

1. `--validate` (8 fixed pairs: NVDA/UPS/KO/ENVA/ANET latest + PTON FY2022, LUMN FY2022,
   VFC FY2024). Hard assertions: PTON guidance_direction=lowered AND tone_delta <= -1;
   VFC tone_delta <= 0; NVDA new_risk_language >= 2; every response parses and is
   in-bounds. Must pass before the cron entries are installed.
2. `--limit 3` smoke test writes 3 real rows to `mda_features.duckdb` end-to-end.
3. One manual run of `mda_sweep_report.py` must deliver a Telegram message before
   relying on the 03:10 cron.

## How to verify (operations)

- Implementation status: PLAN_MDA_FEATURES.md (phases marked Complete).
- Tonight's progress, live: `cat data/mda_sweep_status.json`
- Cumulative rows: `select count(*), max(extracted_at) from mda_features` in
  `data/mda_features.duckdb`
- Logs: `logs/mda_feature_sweep.log`, `logs/mda_sweep_report.log`, and
  `~/projects/trade_systems/logs/cron_failures.log` for wrapper-caught failures.
- Daily Telegram message at ~03:10.

## Known limitations (accepted for v1)

- 10-K only (annual). 10-Qs would triple volume; revisit after the factor gauntlet.
- Corpus inherits the documented survivorship bias (delisted companies missing) — the
  factor backtest must be read with that caveat.
- 24,000-char truncation loses the tail of long MD&As (median 10-K section is ~82K
  chars). Acceptable for v1; the cap is a constant in the script.
- Single frozen model (qwen3:8b) by design: feature history stays internally
  consistent. Do not upgrade the model mid-backfill; a model change requires a new
  prompt_version and full re-sweep.

## Out of scope for this implementation (Phase 5, future)

Factor construction and testing: point-in-time join on filing_date into monthly_pe,
IC/quintile/walk-forward gauntlet with Profit Factor and R-Expectancy at the decision
gate; wiring the table into guidance_mda_analyst / earnings_mda_historian context.
