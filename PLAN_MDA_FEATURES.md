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

## Phase 5 — Factor integration (future, not part of this implementation)

- [ ] 5.1 Point-in-time join on filing_date into monthly_pe universe
- [ ] 5.2 IC/quintile/walk-forward gauntlet incl. Profit Factor and R-Expectancy
- [ ] 5.3 Wire mda_features into guidance_mda_analyst / earnings_mda_historian context
