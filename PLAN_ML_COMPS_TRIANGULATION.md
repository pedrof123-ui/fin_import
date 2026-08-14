# PLAN — ML Comps in the AI Researcher Fair Value Triangulation

**Status: COMPLETE (2026-08-14).** All 4 original phases done, plus a same-day Phase 5 follow-up
(chief-narrative visibility fix + divergence tracking) — see below.

Source: user request 2026-08-14 — investigate adding the ML comps valuation
(`historic_fundamentals/ml_comps_model.py`, scored monthly by
`scripts/score_ml_comps_valuation.py` into `ml_comps_valuation`) to the AI Researcher's Fair
Value Triangulation (`_model_summary_table` in `api/research_router.py`).

## What this plan does and does not do

**Does not** retrain, revalidate, or change the ML comps model itself — it already cleared its
own pre-registered walk-forward go/no-go gate (`features/historic_fundamentals/ml_comps_valuation_plan.md`
Phase 3) and is live in production scoring (`--enable-ml-comps` cron). This plan only wires the
already-trusted output into a second consumer.

**Does not** touch `target_price_validation` / the Chief Analyst's "three-way triangulation"
language (`api/prompts/research_chief_narrative.md:99`). That section explicitly frames three
anchors (independent fair value, goal prices, analyst consensus) and folding in a fourth is a
separate prompt-design change with its own tradeoffs — tracked as a reminder, not bundled here.

**Does** add ML comps as a new, genuinely independent anchor to (a) the deterministic Model
Summary display table and (b) the Valuation Analyst sub-agent's input data, following the exact
precedent already set by the Agentic AI DCF Valuator (`features/ai_dcf/`) when it was added as a
second DCF source.

## Why this anchor is not redundant

The existing table has two paradigms: DCF (intrinsic, cash-flow-based — mechanical + AI-authored)
and Multiples (the ticker's own 5yr rolling history). Neither is peer-relative. ML comps predicts
the multiple *peers with similar fundamentals* actually trade at (cross-sectional XGBoost quantile
model, `historic_fundamentals/ml_comps_model.py`) — a third, structurally different signal.
Known limitation to carry into the prompt: it reflects fair value *relative to peers*, so it
inherits any sector-wide mispricing rather than correcting for it.

---

## Phase 0 — Data audit [x] Complete (2026-08-14)

No new code. Confirmed the ground this plan stands on, against `data/historic_fundamentals.duckdb`.

- [x] 0.1 Status distribution (2,656 rows / 2,656 distinct tickers): `ok` 2,521 (94.9%),
      `no_price_basis` 118, `error` 16 (all `"no monthly_pe data"` — e.g. CCEP, SNY, ERIC, HMC,
      ASND — non-US/ADR-style tickers this project doesn't carry fundamentals for), and a single
      `insufficient_peers` row: **BBBY** (the ticker already flagged in
      [[project_survivorship_bias_result]] as silently reassigned post-bankruptcy — its sector
      field is `NONE`, so it has zero peers by construction, not a coverage gap). Against the
      2,661-ticker `company_overview` universe, only **5 tickers have no row at all** (HEI, PAY,
      S, IOT, RBRK) — recently-onboarded names the monthly batch (last full run 2026-08-01)
      hasn't scored yet; Phase 1's "omit row if missing" design already handles this correctly,
      no special-casing needed.
- [x] 0.2 Spot-checked AAPL (large-cap, deep coverage), BBBY (`insufficient_peers`), ACHR
      (unprofitable/cash-burning, `ml_fair_price_basis='median(ps)'`), and the 5 missing-entirely
      tickers above.
      - AAPL: sane — `ml_fair_price_low/mid/high` = $202 / $280 / $401, basis
        `median(pe,pfcf,ps)`, all three passing multiples present.
      - **ACHR: a real finding, not a bug.** `ml_fair_ps_mid` = 135x, `ml_fair_ps_high` = 500x
        (hits `MAX_MULTIPLE`, the sanity cap in `score_ml_comps_valuation.py`) — already an
        extreme predicted multiple. But `ml_fair_price_mid` = **$0.33** (vs. an actual monthly
        price of $4.64-6.81) because ACHR's trailing revenue/share is near-zero
        (`rev_growth_1yr` = -79.8%, actual `ps_ratio` = **1,873-2,749x**). The model is
        directionally right (no peer trades anywhere near 1,900x+ sales) but the resulting
        dollar `ml_fair_price` is not a usable absolute anchor for narrative/pre-revenue names —
        it reads as "worth $0.33" when the real takeaway is "richly priced on trailing revenue,
        priced instead on a future the multiple can't see." **Actionable guardrail for Phase
        1/2**: treat a capped predicted multiple (`ml_fair_*_high == 500.0`, or `mid` within a
        few % of it) as a low-confidence signal — either suppress the display row or annotate it,
        and tell the Valuation Analyst explicitly not to read a capped-multiple fair price as a
        precise dollar figure.
- [x] 0.3 Staleness: `model_version` is almost entirely `2026-08-01` (2,655 rows, the last
      monthly batch), plus 1 row at `2026-08-14` (ACHR's own onboarding-time score, per the
      `score ML comps valuation on ticker onboarding` commit) — both within the expected monthly
      cadence.

**Test** (met): findings above, same format as `features/ai_dcf/PLAN.md` Phase 0.

---

## Phase 1 — Display row in the Model Summary table [x] Complete (2026-08-14)

- [x] 1.1 `api/research_router.py`: added `_ml_comps_row(ticker)` (mirrors
      `render_ai_dcf_triangulation_row` in `api/ai_dcf_router.py`) that queries
      `ml_comps_valuation WHERE ticker = ? AND status = 'ok'` and returns
      `["ML Comps (peer-relative)", low, base, high]` from `ml_fair_price_low/mid/high`, or
      `None` if the row is missing/not `status='ok'` — mirrors the existing `_multiples_row`
      omit-entirely-if-unavailable pattern (no "n/a" placeholder rows).
- [x] 1.1b Guardrail from Phase 0.2's ACHR finding: parses `ml_fair_price_basis` (e.g.
      `"median(pe,pfcf,ps)"`) to find exactly which multiples contributed, and omits the row if
      any *contributing* multiple's `_high` is within 1e-6 of `MAX_MULTIPLE` (500.0) — exact
      float equality doesn't hold since the cap round-trips through `log`/`exp` in the scoring
      script (verified empirically: capped values land at `499.99999999999983`, not `500.0`).
      Checking only the multiples named in `ml_fair_price_basis` (not all three unconditionally)
      avoids suppressing a good row when a *non-contributing* multiple happens to be capped
      (e.g. P/E capped but the basis used P/S only) — covered by
      `test_ml_comps_row_only_checks_contributing_multiples`.
- [x] 1.2 Wired into `_model_summary_table` (now takes `ticker` as its first argument),
      positioned after the two DCF rows (mechanical, then AI-authored) and before the Multiples
      rows.
- [x] 1.3 Threaded through `render_valuation_model_tables` — single extra DB read, no new LLM
      call, no change to the function's async shape.

**Test** (met): `tests/test_research_helpers.py` — 6 new unit tests for `_ml_comps_row` (present
& formatted, omitted on non-`'ok'` status, omitted when a contributing multiple is capped,
NOT omitted when a non-contributing multiple is capped, missing ticker, missing DB — all using
the `monkeypatch.setattr(rr, "_HIST_FUND_DB", ...)` fixture-DB pattern already established in
that file). Updated the 2 existing `_model_summary_table` tests in
`tests/test_research_ai_dcf_integration.py` for the new `ticker` parameter. Full
`tests/test_research_helpers.py` + `tests/test_research_ai_dcf_integration.py` suite: 37 passed.
Manual: rendered the live table for AAPL — `ML Comps (peer-relative) | $202.07 | $279.63 |
$400.62` appears between `DCF (scenario)` and the Multiples rows; confirmed `_ml_comps_row`
returns `None` for ACHR (capped) and BBBY (`insufficient_peers`) directly against the real DB.

---

## Phase 2 — Valuation Analyst input [x] Complete (2026-08-14)

- [x] 2.1 `api/research_router.py`: added `_format_ml_comps_summary(ticker)`, injected into
      `valuation_analyst_context` right after the peer comparison block. Refactored the shared
      DB read into `_get_ml_comps_data(ticker)` (used by both this and `_ml_comps_row`, Phase 1)
      so the capped-multiple detection logic lives in exactly one place. States predicted fair
      P/E, P/FCF, P/S (p10/p50/p90) and the blended `ml_fair_price_low/mid/high`, with the
      contributing bases named explicitly. Degrades to `[INFO] ML comps valuation unavailable
      for this run` when `status != 'ok'` or the row is missing — same shape as
      `format_ai_dcf_summary(None)`. Unlike the Phase 1 display row, a capped prediction is NOT
      hidden here — it's surfaced with an explicit `[CAPPED - LOW CONFIDENCE]` flag plus an
      explanatory sentence, since the LLM (unlike the static table) can use it as directional
      evidence rather than needing a precise number.
- [x] 2.2 `api/prompts/research_valuation.md`: added DATA PROVIDED item 5 "ML COMPS-BASED FAIR
      VALUE" (renumbered items 5-9 to 6-10), labeled peer-cross-sectional and validated only for
      P/E, P/FCF, P/S, with the capped-multiple caveat. Added ML comps as cross-check (c) in the
      fair_value_low/high methodology paragraph, plus a sentence that a meaningful disagreement
      between the historical-multiples and ML comps cross-checks is itself worth noting in
      valuation_methodology. Added `[ML comps]` to the source-tagging convention.
- [x] 2.3 Added `ml_comps_fair_value: Optional[float] = None` to `ValuationOutput` (echoes the
      p50 blended fair price for traceability, same pattern as `ai_dcf_intrinsic_value`),
      documented in the prompt's "Produce:" section, and added the same coercion validator.
      Threaded a ground-truth `ml_comps_ground_truth` value through `_build_post_subagent_tables`
      -> `_validate_report` (mirrors the existing `ai_dcf_intrinsic_value` check) so a hallucinated
      echo shows up as a QC finding, not silently.
- [x] 2.4 Done as part of 2.2.

**Test** (met): 4 new unit tests for `_format_ml_comps_summary` in `tests/test_research_helpers.py`
(unavailable placeholder, present + formatted, capped-flag surfaced with the p50 figure still
stated). Updated 2 pre-existing `_build_post_subagent_tables` unpacking tests in
`tests/test_research_ai_dcf_integration.py` for the new 5-tuple return. Full
`tests/test_research_helpers.py` + `tests/test_research_ai_dcf_integration.py` +
`tests/test_ai_dcf.py` + `tests/test_ai_dcf_orchestration.py` suite: 183 passed. Manual: rendered
`_format_ml_comps_summary` for AAPL (clean), ACHR (capped flag present, p50 still shown), and
BBBY (`[INFO] ... unavailable`) — all three match the designed degradation behavior.

---

## Phase 3 — Regression + latency check [x] Complete (2026-08-14)

- [x] 3.1 Full AI Researcher test suite re-run after Phases 1-2 (`tests/test_research_helpers.py`,
      `tests/test_research_ai_dcf_integration.py`, `tests/test_ai_dcf.py`,
      `tests/test_ai_dcf_orchestration.py`): 183 passed, no regressions to the AI DCF row/
      comparison table or anywhere else.
- [x] 3.2 Latency: decided by code-level reasoning rather than a live benchmark (user call,
      2026-08-14) — this plan adds zero new LLM agent calls and zero new network calls. The only
      additions are one cheap single-row DuckDB read (`_get_ml_comps_data`, reused for both the
      table and the context) and a few hundred extra tokens in the Valuation Analyst's prompt.
      Both are provably negligible against the report's dominant cost (multiple sequential/
      parallel LLM calls each tens of seconds) — a live 3-ticker benchmark was judged not worth
      the real OpenRouter API cost it would incur to confirm what the code already shows.

**Test** (met): 183 passed, 0 failed.

---

## Phase 5 — Chief-narrative visibility + divergence tracking [x] Complete (2026-08-14)

Follow-up conversation the same day (not a fourth anchor, not a consensus swap — both considered
and rejected on pseudo-independence / loss-of-external-check grounds; decisions recorded, not
repeated here).

- [x] 5.1 `api/prompts/research_chief_narrative.md`: one-line addition to the
      `target_price_validation` **Independent Fair Value** bullet — the chief must now name the
      ML comps figure explicitly and state which side it weighted more heavily whenever the
      Valuation Analyst's `valuation_methodology` flagged a material ML-comps-vs-DCF
      disagreement. Closes the "conditional visibility" gap (the data already reached the chief;
      it just wasn't required to surface it) without restructuring the three-way anchor set or
      creating the pseudo-independence problem a real fourth anchor would.
- [x] 5.2 Divergence tracking, to answer "should ML comps ever become a real fourth anchor" with
      data instead of guessing:
      - `api/ai_dcf_router.py`: added `compute_ml_comps_divergence_pct` (mirrors
        `compute_divergence_pct`); extended `dcf_reconciliation_log` with 3 nullable columns
        (`ml_comps_fair_value`, `ml_comps_ground_truth`, `ml_comps_divergence_pct`) via
        `ALTER TABLE ADD COLUMN IF NOT EXISTS` (the production file already had 35 rows —
        migration verified additive-only, applied live, all 35 preserved); `log_dcf_reconciliation`
        and `get_reconciliation_log` extended to carry the new fields.
      - `api/research_router.py`: the existing `log_dcf_reconciliation` call site now also
        passes `valuation_out.ml_comps_fair_value` and the ground-truth `ml_comps_ground_truth`
        (already computed in Phase 2).
      - `scripts/report_ml_comps_calibration.py`: new `build_ml_comps_triangulation_section`,
        appended to the existing monthly Telegram message (same cron slot, no new infra). Reports
        N logged / % materially diverging (reusing `_DIVERGENCE_WARN_THRESHOLD = 0.20`, the same
        bar already used for mechanical-vs-AI-DCF divergence). Gated on volume, not calendar
        time — `ML_COMPS_ANCHOR_REVIEW_COUNT = 30` — since AI Researcher reports are generated
        on demand, not on a batch schedule, so elapsed time alone doesn't guarantee a meaningful
        sample. Once 30 real reports have logged an ML comps comparison, the report flags
        "ready for a real conversation" — a trigger, not an auto-decision, same governance as the
        existing Phase 9 ml_comps-model gate.

**Test** (met): 5 new tests in `tests/test_ai_dcf.py` (divergence math, round-trip persistence,
null-default round-trip, and — critically — a pre-existing-DB migration test proving the
`ALTER TABLE` runs cleanly against a file created before these columns existed) and 4 new tests
in `tests/test_report_ml_comps_calibration.py` (no-file, zero-rows, divergence-rate math,
ready-for-review threshold). Full suite (`test_ai_dcf.py`, `test_ai_dcf_orchestration.py`,
`test_research_ai_dcf_integration.py`, `test_research_helpers.py`,
`test_report_ml_comps_calibration.py`): 144 passed. Manual: ran
`uv run scripts/report_ml_comps_calibration.py --dry-run` against the real DBs (after applying
the now-verified-safe migration to the production `dcf_reconciliation_log.duckdb`) — new section
renders correctly: "ML comps triangulation: 0 report(s) logged with an ML comps anchor yet"
(accurate — the 35 pre-existing rows predate this tracking, count grows from here).

---

## Explicitly out of scope (tracked as a reminder, not part of this plan)

- Promoting ML comps to a real fourth `target_price_validation` anchor, or swapping it in for
  Analyst Consensus — both considered 2026-08-14 and rejected (pseudo-independence with anchor
  #1; loss of the only externally-sourced anchor, respectively). Revisit once
  `ML_COMPS_ANCHOR_REVIEW_COUNT` (30 logged reports) is reached — `scripts/report_ml_comps_calibration.py`'s
  monthly Telegram report will flag it automatically.
- Any change to `ml_comps_model.py`, `score_ml_comps_valuation.py`, or the P/E-P/FCF-P/S
  `PASSING_MULTIPLES` gate.
