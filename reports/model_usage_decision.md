# Fundamentals Alpha — Model Usage Decision

Closes the Phase 11 gate (`features/historic_fundamentals/fundamentals_alpha_action_plan.md`).
Decided 2026-07-20, based on `reports/model_acceptance_checklist.md`.

Categories, per the original plan:

```
Category 1: Research only
Category 2: Idea generation
Category 3: Paper trading
Category 4: Live portfolio support
```

## Composite factor score (value + quality + momentum): Category 3 — Paper Trading

This is already what's running: the live strategy `vw_gr_top_n_25` (guardrails +
vol-weighting + regime filter, on `ib_tracker_paper.duckdb`) is composite-scored.
This decision formally ratifies that as the correct choice — it wasn't previously
based on a documented comparison; it now is.

**Conditions attached, not blanket approval:**
- **Not yet Category 4 (live portfolio support / real capital).** The paper track
  record is 13 trading days old (inception 2026-07-01) — far too short to
  corroborate the backtest. Revisit after at minimum 3-6 completed rebalance
  cycles, with enough closed trades to compute realized Profit Factor and Van
  Tharp R-Multiple (both currently N/A — zero closed trades so far).
- **Disclose the sector-concentration finding** (checklist #8) to anyone
  reviewing this strategy: a real share of the edge is sector positioning, not
  purely stock selection. This affects how the strategy should be described and
  what correlation to expect against other sector-driven positions.
- **Drawdown is a portfolio-manager judgment call, not resolved here**
  (checklist #9): the risk-managed live variant's backtested MaxDD is -35.4%;
  the unguarded top_n_25 variant used for cross-model comparison runs -50% to
  -54%. Confirm the guardrailed/vol-weighted variant is what continues to be
  used live, not the more aggressive raw version.
- **The top/bottom-bucket non-monotonicity is an open question** (checklist #5)
  worth investigating further — it doesn't block this decision, but it means
  the composite score should not be marketed or relied on as a broadly monotonic
  quality signal beyond the top ~25-50 names.

## XGBoost `ret_1y` model: Category 1 — Research Only (downgraded from de facto live status)

**Retired from trading consideration.** It fails the central acceptance
criterion (OOS rank IC = -0.017, essentially flat) and underperforms the
composite score on every risk-adjusted metric once evaluated under a genuine
walk-forward methodology (`docs/walk_forward_portfolio_backtest.md`) instead of
the single-static-model backtest that had made it look competitive
(20-25% CAGR headline numbers in `docs/backtest_results_model*.md` — now known
to be a methodology artifact, not skill).

This is a downgrade in name only, not in practice: the live pipeline has never
actually scored with this model (`score_live.py` defaults to composite;
`run_pipeline.py` never passes `--use-model`), so no live behavior changes as a
result of this decision. The model, training/scoring scripts
(`scripts/train_model.py`, `scripts/score_live.py --use-model`,
`scripts/run_backtest.py --model`), and the train/serve normalization fix
applied to it (2026-07-20) are retained in the codebase for research purposes
and in case future feature engineering changes the picture — they should not
be wired into any live or paper-trading path without a new walk-forward
comparison repeating this evaluation.

## Next review trigger

Revisit this decision when either:
1. The paper track record accumulates enough history (3-6+ rebalance cycles,
   closed trades) to compare realized vs. backtested performance, or
2. Someone proposes reintroducing XGBoost or a new ML variant — any such
   proposal should be required to clear the same walk-forward portfolio
   backtest bar (`scripts/walk_forward_portfolio_backtest.py`) that
   disqualified this one, not just a single-static-model backtest.
