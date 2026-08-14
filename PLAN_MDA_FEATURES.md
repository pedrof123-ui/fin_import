# PLAN: MD&A Feature Extraction Sweep

Spec: docs/mda_feature_sweep_spec.md
Launch target: nightly cron starting 2026-08-09 23:00 EDT.

## Phase 1 — Sweep runner

- [x] 1.1 `scripts/mda_feature_sweep.py`: pairs query (post-2016 10-K pairs, closest
      prior within 330-400d, anti-join on extracted), newest-first ordering
- [x] 1.2 `data/mda_features.duckdb` `mda_features` table created per spec schema
- [x] 1.3 Ollama call: qwen3:8b, think=true, temp 0, num_ctx 16384, keep_alive 15m,
      schema-constrained JSON, prompt v1.1 (outlook-language redefinition)
- [x] 1.4 Window enforcement (--window-end, default 03:00), resume-safe inserts,
      5-consecutive-error abort, absolute paths only
- [x] 1.5 Auto-start `ollama serve` with OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0
      when not responding
- [x] 1.6 Status JSON written after every pair (data/mda_sweep_status.json)

## Phase 2 — Validation

- [x] 2.1 `--validate` mode: 8 fixed pairs, hard gates (PTON lowered & tone<=-1,
      VFC tone<=0, NVDA new_risk>=2, all parse in-bounds), exit non-zero on failure
- [x] 2.2 Validation gate passes with prompt v1.1
- [x] 2.3 `--limit 3` smoke test writes 3 real rows end-to-end

## Phase 3 — Telegram report

- [x] 3.1 `scripts/mda_sweep_report.py`: reads status JSON + DB count, sends via Bot API
      (token from ~/.claude/channels/telegram/.env, chat 8351706654), reports failure
      states explicitly, exits non-zero if send fails
- [x] 3.2 Manual test message delivered to Telegram

## Phase 4 — Scheduling and launch

- [x] 4.1 Cron: sweep 23:00 daily, report 03:10 daily (cron_wrap.sh, absolute uv path,
      no --lock)
- [x] 4.2 Crontab installed and verified (`crontab -l`)
- [ ] 4.3 First-night check: status JSON shows state=running after 23:00 tonight
      (verify tomorrow: pairs_tonight > 0 and Telegram report received ~03:10)

## Phase 5 — Factor integration

- [x] 5.1 Point-in-time join on filing_date into monthly_pe universe
      (`scripts/test_mda_features.py`, backward asof per ticker, 450-day tolerance)
- [x] 5.2 IC/quintile/walk-forward gauntlet incl. Profit Factor and R-Expectancy —
      **all 5 features + interaction REJECTED 2026-08-14**, see "Gauntlet result" below
      and [[project_mda_factors_result]]
- [ ] 5.3 Wire mda_features into guidance_mda_analyst / earnings_mda_historian context —
      **not proceeding**: no promotable factor came out of 5.2, nothing to wire in

## Gauntlet result (2026-08-14)

`scripts/test_mda_features.py`. IC test found `guidance_direction` and `specificity`
significantly *negative* — opposite of the literature that motivated the features —
confirmed not a data-quality artifact (the cleaner 30B subset showed a stronger negative
IC than the noisier 8B subset). A sign-flipped ("contrarian") composite looked attractive
in-sample (better Sharpe/MaxDD/PF than baseline). A genuine walk-forward split (sign
chosen on the early half only, tested on the untouched late half) killed it: no factor
held a stable sign in-sample vs out-of-sample — `guidance_direction`'s flip went to zero
OOS, `new_risk_language`'s sign flipped between halves (its "clean monotonic" full-sample
table was an artifact of asymmetric period weighting), and `specificity`'s sign fully
reversed with a much stronger effect OOS (t=-5.51) than the direction that was bet on.
The OOS composite backtest underperformed the no-MD&A baseline on CAGR, Sharpe, PF and
R-Expectancy. Full writeup: [[project_mda_factors_result]].

`historic_fundamentals/baselines.py` (`_VALUE_COLS`/`_QUALITY_COLS`) and
`scripts/score_live.py` untouched, as with every prior rejected-factor test.

## Backfill status (2026-08-13)

Full post-2016 10-K backfill done on a rented RunPod RTX 4090 (outside the nightly cron window).
`data/mda_features.duckdb` `mda_features`: **18,169 rows** — 7,107 on `qwen3:30b-a3b`, 11,062 on
`qwen3:8b`.

A 296-pair 8B-vs-30B comparison sample found `guidance_direction`'s "maintained" bucket
unreliable on 8B (28.9% agreement with 30B, vs. 86-94% when 8B committed to raised/lowered) —
8B defaults to "maintained" as a hedge when it can't ground the call in a concrete figure (50%
of maintained rationales cite a number, vs. 88% for 30B on the same cases). Re-extracted all
7,123 then-"maintained" rows on `qwen3:30b-a3b` (7,107 succeeded, 16 lost to isolated timeouts).
At full scale the re-judgment reclassified 74% of them (41.6% raised, 31.7% lowered, 25.6% stayed
maintained) — matches the comparison sample's predicted split.

**Known open gap, not fixed by the above:** `hedging_change` and `new_risk_language` had worse
8B/30B disagreement in the raised/lowered buckets than in maintained (e.g. hedging_change MAE
0.91 maintained vs. 1.13 raised / 1.52 lowered), so the maintained-only rerun did not address
their reliability problem in the 11,062 rows still on `qwen3:8b`. Before Phase 5: either weight
these two features with more skepticism in the gauntlet, or run a second scoped rerun targeting
them specifically.
