# PLAN — Analyst Dispersion & Estimate Staleness

Source: Barron's, "The Hidden Red Flag in Wall Street's Price Targets" (2026-08-13), reporting
Zhang et al. (2024) on price-target dispersion. The underlying anomaly is Diether, Malloy &
Scherbina (2002): dispersion in analyst forecasts predicts *low* forward returns, via Miller
(1977) — short-sale constraints let the optimists set the price.

## What this plan does and does not do

**Does not** build a dispersion trading factor. Alpha Vantage serves no per-analyst price targets
and no historical estimate snapshots, so there is nothing to backfill: `earnings_estimates` holds
2026-05-10 to 2026-08-12, roughly seven usable full-universe snapshots. A cross-sectional factor
needs 3+ years. Phases 1/2/6 make that test possible in ~2028 without re-deriving anything; they
do not attempt it now.

**Does** fix the presentation problem the article actually documents. Finview currently shows
`analyst_target_price` with a coloured upside figure and no qualification
(`web/components/FundamentalsViewer.tsx:263-274`, `:481`) — precisely the shorthand the Paycom case
study exists to discredit. The disqualifying context (EPS high/low band, coverage count, 30-day
revision counts) is **already in the database** and already rendered on a different tab
(`web/components/EstimatesViewer.tsx`). This plan puts it where the target price is.

## Metric definitions (fixed once, used everywhere)

Computed from `earnings_estimates` on the **FY1** horizon (`horizon = 'fiscal year'`, smallest
`fiscal_date > CURRENT_DATE`), which is the ~12-month analogue of the paper's price-target horizon.
Q1 (`horizon = 'fiscal quarter'`, smallest future `fiscal_date`) is stored too but not displayed.

| Metric | Formula | Null when |
| --- | --- | --- |
| `eps_dispersion` | `(eps_high - eps_low) / eps_avg` | `eps_avg` is null, or `eps_avg < 0.10` |
| `coverage` | `eps_count` | null |
| `net_revisions_30d` | `eps_rev_up_30d - eps_rev_down_30d` | both null |
| `eps_drift_30d` | `(eps_avg - eps_avg_30d) / abs(eps_avg_30d)` | either null, or `eps_avg_30d == 0` |
| `rev_dispersion` | `(rev_high - rev_low) / rev_avg` | `rev_avg` null or `<= 0` |

Note `eps_avg < 0.10` (not `abs(eps_avg) < 0.10`) — a single lower-bound comparison excludes
both near-zero AND negative consensus EPS in one guard, since a negative denominator flips the
ratio's sign just as badly as a near-zero one explodes it.

Two constraints that must not be relaxed:

1. **The 0.10 EPS floor is mandatory.** Near-zero or negative consensus EPS makes the ratio
   explode or flip sign. Without the floor, "highest dispersion" degenerates into "lowest EPS",
   which is a different (and already-known) factor.
2. **No hardcoded 30% red-flag threshold.** Zhang's 30% rule is for *price-target* dispersion; EPS
   dispersion has a different scale. Rank cross-sectionally instead: `eps_dispersion_pctile` =
   percentile within the same snapshot's universe, restricted to `coverage >= 5`. This is
   computable today — each snapshot carries ~2,300 tickers.

**Known bias, documented not corrected.** `(High - Low)` is a range statistic: its expectation
grows with the number of analysts even at constant true dispersion. The paper uses per-analyst
standard deviation, which AV does not provide. Consequence: raw dispersion partly proxies for
coverage. This is why `coverage` is always displayed alongside it, and why Phase 2 stores raw
components rather than derived ratios — a coverage-adjusted normalisation can be fitted later once
history exists.

---

## Phase 0 — Close the collection gap [x]

`scripts/estimates_update.py:17` documents a weekly Monday 06:00 cron. No such entry exists
(`crontab -l` has 65 lines, none matching). Same failure mode as the earnings-pipeline and
regime-monitor cron bugs. Snapshots are landing ad hoc, roughly monthly. The archive is the only
asset in this plan that cannot be bought back later, so this phase ships first and alone.

**Do**

1. Install the cron, matching the existing `cron_wrap.sh` convention used by
   `earnings_calendar_update` in the current crontab:
   ```
   # Analyst estimates snapshot — weekly, Monday 6:15 AM ET (after earnings_calendar at 5:45)
   15 6 * * 1 /home/pedro/projects/trade_systems/scripts/cron_wrap.sh estimates_update /home/pedro/.local/bin/uv run --project /home/pedro/projects/fin_import2 /home/pedro/projects/fin_import2/scripts/estimates_update.py >> /home/pedro/projects/fin_import2/logs/estimates_update.log 2>&1
   ```
   Absolute script path, so no `--directory` flag is needed here (that bug class applies to `-m
   module` invocations only). Verify the script is genuinely path-independent before relying on
   this — it resolves ROOT from `__file__`, so it should be.
2. Update the docstring at `scripts/estimates_update.py:17` to state 6:15, not 6:00.
3. Rate limiting is already correct — `historic_fundamentals/estimates.py:74` calls
   `limiter.wait()` on the shared 75-calls/min `RateLimiter`, one call per ticker. Just confirm the
   full run's wall clock lands near the expected ~31 min for ~2,300 tickers and shows no 429s.

**Test**

- `crontab -l | grep estimates_update` returns exactly one line.
- Dry run completes without error: `uv run scripts/estimates_update.py --ticker NVDA --dry-run`.
- Full manual run appends a new `fetched_at` date covering >2,000 distinct tickers:
  ```sql
  SELECT CAST(fetched_at AS DATE) d, COUNT(DISTINCT ticker) FROM earnings_estimates
  GROUP BY 1 ORDER BY 1 DESC LIMIT 3;
  ```
- Timed check: log shows elapsed time and no HTTP 429 / rate-limit messages.

**Done when** the cron is installed, one manual full run has landed, and the log is clean.

---

## Phase 1 — Dispersion metric module [x]

Pure computation, no I/O, so it is trivially testable and reusable by the API, the snapshot
builder, and the eventual factor script.

**Do**

Create `historic_fundamentals/dispersion.py`:

- `compute_metrics(row: dict) -> dict` — takes one `earnings_estimates` row, returns the five
  metrics above. Every guard from the table applies; return `None` per-metric, never raise.
- `select_horizons(rows: list[dict]) -> dict` — from a ticker's latest-snapshot rows, picks the
  FY1 and Q1 rows per the selection rule above. Returns `{"fy1": row|None, "q1": row|None}`.
- `percentile(value, population) -> float | None` — cross-sectional percentile rank, `None` if
  value is `None` or population has fewer than 50 valid entries.
- `MIN_EPS_ABS = 0.10` and `MIN_COVERAGE_FOR_PCTILE = 5` as module constants, not inline literals.

**Test** — `tests/test_dispersion.py`, no database:

- Normal case: `eps_high=16.0, eps_low=9.65, eps_avg=12.7644` → dispersion ≈ 0.4975.
- EPS floor: `eps_avg=0.05` → `None`. `eps_avg=-2.0` → `None`. `eps_avg=0.10` → computed (boundary
  is inclusive).
- Nulls: any missing input → `None` for that metric, other metrics still computed.
- `net_revisions_30d`: `up=1, down=4` → `-3`; both null → `None`; `up=0, down=0` → `0` (not `None`).
- `select_horizons` on a fixture mirroring the real NVDA rows (FY 2027-01-31 and 2028-01-31,
  quarters both past and future) picks 2027-01-31 as FY1 and the first future quarter as Q1.
- `select_horizons` returns `None` for both when every `fiscal_date` is in the past.
- `percentile` returns `None` on a 20-element population, a value on a 200-element one, and 1.0 for
  the maximum element.

**Done when** `uv run pytest tests/test_dispersion.py -q` is green.

---

## Phase 2 — Monthly dispersion snapshot table [x]

Freezes one point-in-time row per ticker-month so that a 2028 factor test has a clean, joinable
history. Stores **raw components only** — no derived ratios — so any future normalisation
(coverage-adjustment, winsorisation, log transform) can be recomputed from source.

**Do**

1. Add to `historic_fundamentals/db.py` alongside the existing `CREATE TABLE IF NOT EXISTS`
   blocks (follow the `earnings_estimates` block at `:389` for style):
   ```sql
   CREATE TABLE IF NOT EXISTS estimates_dispersion (
       ticker           VARCHAR   NOT NULL,
       month_end_date   DATE      NOT NULL,
       horizon_slot     VARCHAR   NOT NULL,   -- 'FY1' | 'Q1'
       fiscal_date      DATE,
       snapshot_at      TIMESTAMP NOT NULL,   -- the source fetched_at
       eps_avg          DOUBLE,
       eps_high         DOUBLE,
       eps_low          DOUBLE,
       eps_count        INTEGER,
       eps_avg_30d      DOUBLE,
       eps_rev_up_30d   INTEGER,
       eps_rev_down_30d INTEGER,
       rev_avg          DOUBLE,
       rev_high         DOUBLE,
       rev_low          DOUBLE,
       rev_count        INTEGER,
       PRIMARY KEY (ticker, month_end_date, horizon_slot)
   )
   ```
2. Create `scripts/build_dispersion_snapshots.py`:
   - For each calendar month present in `earnings_estimates`, take each ticker's **last**
     `fetched_at` in that month, apply `select_horizons`, and upsert FY1/Q1 rows with
     `month_end_date` = last day of that month.
   - Idempotent: re-running produces identical rows (`ON CONFLICT ... DO UPDATE`).
   - `--month YYYY-MM` for one month, default all.
   - Skip months whose latest snapshot covers fewer than 500 tickers, and log the skip — the ad-hoc
     single-ticker runs visible in May/June/July must not become a "month".
3. Append to the Phase 0 cron a second weekly line running this immediately after
   `estimates_update`, so the current month's row is always refreshed to the newest snapshot.

**Test** — `tests/test_dispersion_snapshots.py`, in-memory DuckDB fixture:

- A synthetic `earnings_estimates` with two tickers and three `fetched_at` values in one month
  produces exactly two FY1 rows, both sourced from the latest `fetched_at`.
- Running the builder twice yields the same row count and identical values (idempotence).
- A month whose largest snapshot has 10 tickers is skipped; a 600-ticker month is not.
- A ticker with no future `fiscal_date` produces no row rather than an error.
- Against the real DB: `uv run scripts/build_dispersion_snapshots.py` then assert
  `SELECT month_end_date, COUNT(*) FROM estimates_dispersion WHERE horizon_slot='FY1' GROUP BY 1`
  shows the expected months (2026-06, 2026-07, 2026-08 at minimum) with >2,000 rows each.

**Done when** the table exists, is populated for every qualifying month, and re-running changes
nothing.

---

## Phase 3 — API surface [x]

**Do**

1. `api/av_router.py` — `GET /av-fundamentals/{ticker}` at `:207`, payload built at `:242-290`. The `est_df` query already
   pulls `eps_high/low/count`. Add to the returned payload:
   `eps_dispersion`, `eps_dispersion_pctile`, `coverage`, `net_revisions_30d`, `eps_drift_30d`,
   `dispersion_fiscal_date`, `dispersion_as_of` — all from `historic_fundamentals.dispersion`
   applied to the FY1 row. All nullable; a ticker with no estimates returns nulls, not an error.
2. Percentile source: the current month's `estimates_dispersion` FY1 population, filtered to
   `eps_count >= 5`. If `estimates_dispersion` is empty or missing, return `None` for the
   percentile and keep every other field — the endpoint must not hard-depend on Phase 2.
3. `api/estimates_router.py`: add `eps_dispersion` and `rev_dispersion` to each period dict in
   `_get_periods` (the raw high/low/count are already there).

**Test** — extend `tests/test_av_router.py` and add `tests/test_estimates_router.py`:

- `GET /av-fundamentals/NVDA` returns all seven new keys.
- A ticker with no `earnings_estimates` rows returns 200 with the new fields null.
- A ticker whose FY1 `eps_avg` is below the floor returns `eps_dispersion: null` but a non-null
  `coverage`.
- With `estimates_dispersion` absent, the endpoint still returns 200 and `eps_dispersion_pctile:
  null`.
- `GET /estimates/NVDA` periods each carry `eps_dispersion` and it matches a hand-computed value
  for one period.

**Done when** `uv run pytest tests/test_av_router.py tests/test_estimates_router.py -q` is green
and a live `curl` against a running API returns sane numbers for NVDA, MSFT, and a small-cap with
thin coverage.

---

## Phase 4 — Finview UI [x]

**Do**

1. `web/components/FundamentalsViewer.tsx:263-274` — the header "Analyst target" chip. Append,
   after the upside figure:
   - `n analysts` (from `coverage`; omit the chip entirely if null).
   - A dispersion chip: `Spread 50%` with the percentile as a tooltip/subscript, e.g.
     `(78th pct)`. Colour by percentile, not by absolute value: top quintile amber, top decile red,
     everything else neutral zinc. Do **not** colour a 30% absolute threshold.
   - A revisions chip: `3↓ net 30d` in red when `net_revisions_30d < 0`, emerald when `> 0`,
     zinc when `0`. Omit if null.
2. `:481` — the Price Targets table, "Analyst Consensus" row. Add a muted second line under the
   label showing coverage and dispersion, so the consensus row is visibly different in kind from
   the four model-derived rows above it.
3. `web/components/EstimatesViewer.tsx` — add a `Spread` column beside the existing `eps_count`
   column at `:211`, rendering `eps_dispersion` as a percentage.
4. Add a one-sentence tooltip on the dispersion chip: wide spreads mean analysts disagree or some
   targets are stale, and historically correlate with weaker forward returns. No citation clutter
   in the UI.

**Test**

- `cd web && npx tsc --noEmit` clean, `npm run lint` clean, `npm run build` succeeds.
- Manual, against the running API — capture screenshots for the record:
  - NVDA: wide spread, high coverage, all three chips render.
  - A utility (e.g. SO or DUK): narrow spread, neutral colour — confirms the low end renders.
  - An unprofitable small-cap: dispersion chip absent (floor triggered), coverage chip still
    present — confirms graceful degradation rather than `NaN%` or `Infinity%`.
  - A ticker with no estimates at all: header renders exactly as it does today, no empty chips, no
    layout shift.

**Done when** all four tickers render correctly and no console errors appear.

---

## Phase 5 — AI Researcher chief integration [x]

The chief already triangulates three anchors in `target_price_validation`
(`api/prompts/research_chief_narrative.md:99-115`) and already asks "how many analysts cover the
stock". It currently has coverage from the *ratings* distribution only, and no dispersion or
revision-direction context. Goal: it should be able to write "consensus $314, but drawn from a
$180-743 band with 3 net downward revisions in 30 days" instead of treating consensus as one clean
number.

**Do**

1. `api/research_router.py:1122` `get_estimates_summary` — the table it builds already has
   `eps_avg`, `eps_avg_7d/30d`, and up/down counts. Add two columns: `Spread` (`eps_dispersion` as
   a percent) and `N` (`eps_count`). Add one summary line beneath the table:
   `FY1 dispersion: 49.8% (78th percentile of covered universe), 12 analysts, net revisions -3 over 30d`.
   Omit the percentile clause when it is null.
2. `api/research_router.py:1090-1117` — the analyst consensus block already reads
   `company_overview`. Leave it as is; do not attempt to synthesise a price-target range AV does
   not provide.
3. `api/prompts/research_chief_narrative.md`, the `**Analyst Consensus**` bullet: instruct the
   chief to state coverage and FY1 dispersion explicitly, and to **discount the consensus anchor
   when dispersion is in the top quintile or net 30-day revisions are negative** — naming which of
   the two applies. Add one sentence that a high spread often reflects stale un-updated targets
   rather than genuine disagreement, so a wide band plus negative revisions is the strongest
   discount case.
4. `api/prompts/research_chief_core.md:99` — leave `analyst_target_price` semantics unchanged. The
   header target still derives from independent fair value, as today.
5. **Do not touch the AI DCF or the valuation sub-agent.** The valuation agent is deliberately
   blind to price and analyst targets (`AI_RESEARCHER_IMPROVEMENT_PLAN.md:97`); feeding it the EPS
   band would import analyst optimism into the one component built to avoid it. The band is used
   in the chief's reconciliation only.

**Test**

- `uv run pytest tests/test_research_helpers.py -q` green after extending it: assert
  `get_estimates_summary("NVDA")` contains `Spread`, a percentile clause, and a net-revision
  figure; assert a no-estimates ticker still returns the existing `[INFO] No analyst estimates`
  string unchanged.
- Generate one live report for a high-dispersion name (NVDA) and one for a low-dispersion name
  (a utility). Confirm by reading `target_price_validation` that the high-dispersion report
  actually discounts consensus and the low-dispersion one does not. This is a judgement check, not
  an assertion — record both outputs in `docs/`.
- Confirm no regression in `_validate_report` findings count for those two tickers.
- Record the token/cost delta on the header from `log_llm_usage`. The added lines are small;
  if cost moves more than ~2%, something else changed.

**Done when** both reports read correctly and the helper tests pass.

---

## Phase 6 — Dormant factor-test groundwork [x]

Write the test now while the reasoning is fresh; run it in ~2028. It must refuse to run on
insufficient history rather than produce a misleading result from seven snapshots.

**Do**

Create `scripts/test_dispersion_factor.py`, mirroring the structure of
`scripts/test_greenblatt_factors.py`:

1. **History guard first.** Count distinct `month_end_date` in `estimates_dispersion`. If fewer
   than 36, print the count, print the earliest month, print the projected ready-date, and exit 0
   without computing anything. This guard is the deliverable of this phase.
2. Behind the guard, the standard gauntlet used for every prior factor:
   - Spearman rank IC of `eps_dispersion` (sign-flipped: high dispersion is the *short*) against
     6m/12m forward returns, versus incumbent factors.
   - Quintile spread with the universe filters from `historic_fundamentals/universe.py`.
   - Composite A/B against `_VALUE_COLS`/`_QUALITY_COLS`, computed in-run, touching neither
     `baselines.py` nor `score_live.py`.
3. Three controls that must be in the script from day one, because the article's own numbers do not
   survive without them:
   - **Coverage control.** Report IC of dispersion after orthogonalising against `log(eps_count)`.
     If the raw IC survives but the residual IC does not, the signal is coverage, not disagreement.
   - **Size and idio-vol control.** Same, against market cap and trailing volatility. The DMS
     effect is documented to concentrate in small, high-vol, hard-to-borrow names.
   - **Long-only subsample.** Report the long leg alone. The literature puts most of the alpha in
     the short leg, which is the leg that borrow costs eat.
4. Per the standing metrics rule, report Profit Factor and R-Expectancy alongside Sharpe, MaxDD and
   turnover for every backtest in this script.
5. Do not import from or modify `baselines.py`'s factor lists.

**Test**

- Running it today prints the guard message and exits 0.
- Running it against a synthetic `estimates_dispersion` with 40 fabricated months proceeds past the
  guard and completes without error (correctness of the numbers is not asserted — only that the
  code path runs).
- `grep` confirms no write to `historic_fundamentals/baselines.py` or `scripts/score_live.py`.

**Done when** both runs behave as described.

---

## Sequencing and rollback

Phases 0-2 are backend-only and independently shippable; 3 depends on 1, 4 depends on 3, 5 depends
on 1. Phase 6 depends only on 2.

Ship Phase 0 on its own and merge it before starting anything else — every week it is delayed is a
week of history permanently lost.

Rollback is per-phase: Phases 1, 2 and 6 add new files and one new table, touching nothing existing.
Phase 3 adds nullable payload keys. Phases 4 and 5 are the only ones that change existing behaviour,
and both degrade to today's output when the new fields are null.

## Open item, deliberately deferred

Per-analyst price targets would allow the paper's actual metric (standard deviation across
analysts) rather than the coverage-biased range proxy. AV does not serve them; FMP, Benzinga and
Tipranks do. Revisit only if Phase 6 ever produces a residual IC that survives the coverage
control — paying for a data feed ahead of that evidence is backwards.
