# ACTION_PLAN.md
## Fundamentals Alpha Model Implementation Plan

This plan converts the fundamentals-alpha notebook into a robust, point-in-time, investable stock-selection system.

The plan assumes the project already has an existing Python codebase. Do not create a new project structure. Adapt to the current repo layout.

---

## Executive goal

Improve the current fundamentals-alpha model so it can answer:

```text
Is the model good at picking stocks?
Does it outperform SPY and the investable universe?
Is it worth following?
Can it be run live with reproducible outputs?
```

The model should not be considered investable until it passes point-in-time, walk-forward, portfolio, benchmark, liquidity, risk, and review gates.

---

## Phase 0 — Repository Discovery & Integration Map

**Review needed:** Yes  
**Reviewer:** Code Reviewer Agent  
**Primary owner:** Orchestrator Agent

### Objective

Understand the existing project before writing code.

### Tasks

1. Inspect the repository structure.
2. Identify existing modules for:
   - database connections
   - price loading
   - fundamentals loading
   - feature engineering
   - model training
   - backtesting
   - notebooks
   - tests
   - configuration
3. Identify where `fundamentals_alpha.ipynb` logic currently lives.
4. Decide whether notebook logic should be:
   - left in notebook,
   - wrapped by scripts,
   - migrated to modules,
   - or partially refactored.
5. Produce an integration map.
6. Do not modify production code.

### Deliverables

```text
docs/integration_map.md or equivalent
```

### Acceptance criteria

```text
[ ] Existing structure inspected.
[ ] Relevant modules identified.
[ ] Implementation locations proposed.
[ ] No duplicate structure created.
[ ] No production code changed.
[ ] Code Reviewer approves.
```

---

## Phase 1 — Point-in-Time Data Audit

**Review needed:** Yes  
**Reviewer:** Quant Reviewer Agent  
**Primary owner:** Data Engineering Agent

### Objective

Ensure every model feature was available before the prediction date.

### Tasks

1. Identify prediction dates.
2. Identify fiscal period-end dates.
3. Identify SEC filing or accepted dates if available.
4. Create or validate `feature_available_date`.
5. Enforce:

```text
feature_available_date <= prediction_date
target_return_start_date > prediction_date
```

6. Add conservative fallback lags if filing dates are unavailable:
   - quarterly data: period end + 60 days
   - annual data: period end + 90 days
7. Log timing violations.
8. Add tests for alignment.

### Deliverables

```text
point_in_time_audit_report
timing alignment tests
feature availability logic
```

### Acceptance criteria

```text
[ ] No future fundamentals.
[ ] No future prices in features.
[ ] Feature dates are explicit.
[ ] Prediction dates are explicit.
[ ] Timing violations are logged.
[ ] Tests cover timing rules.
[ ] Quant Reviewer approves.
```

---

## Phase 2 — Investable Universe & Liquidity Filters

**Review needed:** Yes  
**Reviewer:** Quant Reviewer Agent  
**Primary owner:** Risk & Portfolio Agent

### Objective

Prevent the model from selecting uninvestable microcaps, low-priced stocks, or illiquid securities unintentionally.

### Tasks

1. Add configurable filters:
   - minimum market cap
   - minimum price
   - minimum average dollar volume if available
   - valid sector
   - valid price history
2. Run sensitivity tests:
   - market cap >= $300M
   - market cap >= $1B
   - market cap >= $5B
3. Produce monthly universe counts.
4. Ensure live scoring uses the same universe rules.
5. Prevent missing market cap from bypassing filters.

### Suggested defaults

```text
market_cap_min = 1_000_000_000
price_min = 5
min_avg_dollar_volume = configurable
```

### Acceptance criteria

```text
[ ] Filters are configurable.
[ ] Monthly counts are reported.
[ ] Missing values handled.
[ ] Live scoring cannot bypass filters.
[ ] Sensitivity analysis complete.
[ ] Quant Reviewer approves.
```

---

## Phase 3 — Feature Engineering Improvements

**Review needed:** Yes  
**Reviewer:** Code Reviewer Agent and Quant Reviewer Agent  
**Primary owner:** Feature Engineering Agent

### Objective

Add quality, margin, leverage, and stability features that may improve the fundamentals model.

### Initial feature set

```text
gross_margin_5y_median
gross_margin_slope_5y
operating_margin_5y_median
operating_margin_change_3y
operating_margin_slope_5y
fcf_margin_5y_median
fcf_margin_change_3y
roa_stability_5y
debt_to_ebitda
interest_coverage
```

### Formula guidance

```text
gross_margin = gross_profit / revenue
operating_margin = operating_income / revenue
fcf_margin = free_cash_flow / revenue
free_cash_flow = operating_cash_flow - capex_abs
debt_to_ebitda = total_debt / EBITDA
interest_coverage = EBIT / interest_expense_abs
roa_stability_5y = std(roa over 5 years), lower is more stable
margin_slope_5y = linear regression slope over 5 years
margin_change_3y = current margin - margin 3 years ago
```

### Tasks

1. Add selected features in existing feature module.
2. Add unit tests.
3. Handle missing, infinite, and extreme values.
4. Add sector-relative versions where appropriate.
5. Document expected direction of each feature.
6. Ensure point-in-time safety.

### Acceptance criteria

```text
[ ] Formulas tested.
[ ] Missing and infinite values handled.
[ ] Feature dates safe.
[ ] Expected signs documented.
[ ] Reviewers approve.
```

---

## Phase 4 — Baseline Factor Models

**Review needed:** Yes  
**Reviewer:** Quant Reviewer Agent  
**Primary owner:** Quant Research Agent

### Objective

Compare XGBoost against simple explainable factors.

### Required baselines

```text
low P/S
high FCF yield
high dividend yield
low EV/EBITDA
composite value score
value + quality score
value + momentum score if momentum exists
```

### Tasks

1. Build simple rank-based baseline models.
2. Use the same dates and universe as XGBoost.
3. Report:
   - IC
   - ICIR
   - hit rate
   - quintile/decile spread
   - top-bucket returns
4. Compare baseline performance to XGBoost.

### Acceptance criteria

```text
[ ] Baselines implemented.
[ ] Same universe and dates used.
[ ] XGBoost value-add assessed.
[ ] Quant Reviewer approves.
```

---

## Phase 5 — Walk-Forward Model Validation

**Review needed:** Yes  
**Reviewer:** Quant Reviewer Agent  
**Primary owner:** ML Engineering Agent

### Objective

Validate the model using time-based walk-forward splits.

### Primary target

```text
ret_1y
```

### Secondary diagnostics

```text
ret_6m
ret_2y
ret_3y
ret_5y
```

### Tasks

1. Use time-based walk-forward splits.
2. Do not use random splits for final results.
3. Report:
   - out-of-sample R²
   - rank IC
   - ICIR
   - Newey-West adjusted ICIR if available
   - hit rate
   - quintile/decile spreads
   - top-bucket returns
   - yearly performance
4. Report SHAP and feature stability by period.
5. Separate in-sample and out-of-sample results.

### Acceptance criteria

```text
[ ] Time-based validation.
[ ] OOS metrics reported.
[ ] Results shown by year/regime.
[ ] Feature stability reviewed.
[ ] Quant Reviewer approves.
```

---

## Phase 6 — True Monthly Portfolio Backtest

**Review needed:** Yes  
**Reviewer:** Quant Reviewer Agent  
**Primary owner:** Backtest Engineering Agent

### Objective

Build a tradable backtest using non-overlapping monthly portfolio returns.

### Tasks

1. Score stocks at month-end.
2. Construct portfolios:
   - top 20%
   - top 10%
   - top 50 names
   - top 25 names
3. Equal-weight by default.
4. Add optional capped-weight method.
5. Apply universe filters.
6. Include transaction costs and turnover.
7. Compute non-overlapping monthly returns.
8. Compare against:
   - SPY
   - equal-weight universe
   - baseline factors
9. Report:
   - CAGR
   - volatility
   - Sharpe
   - Sortino if available
   - max drawdown
   - beta to SPY
   - alpha
   - information ratio
   - tracking error
   - turnover
   - transaction cost drag

### Acceptance criteria

```text
[ ] Monthly returns are non-overlapping.
[ ] Strategy is tradable in principle.
[ ] Transaction costs included.
[ ] Benchmarks aligned.
[ ] Metrics reported.
[ ] Quant Reviewer approves.
```

---

## Phase 7 — Risk Diagnostics & Guardrails

**Review needed:** Yes  
**Reviewer:** Quant Reviewer Agent  
**Primary owner:** Risk & Portfolio Agent

### Objective

Identify hidden risks and prevent obvious value traps.

### Tasks

1. Add sector exposure report.
2. Add industry exposure report if data exists.
3. Add market-cap exposure.
4. Add beta and drawdown analysis.
5. Add position concentration report.
6. Add guardrail tests:
   - market cap threshold
   - price threshold
   - liquidity threshold
   - debt_to_ebitda threshold
   - interest_coverage threshold
   - severe negative margin flag
7. Compare performance with and without guardrails.

### Acceptance criteria

```text
[ ] Risk diagnostics generated.
[ ] Guardrails configurable.
[ ] Guardrail impact measured.
[ ] Quant Reviewer approves.
```

---

## Phase 8 — Live Scoring Pipeline

**Review needed:** Yes  
**Reviewer:** Code Reviewer Agent and Quant Reviewer Agent  
**Primary owner:** ML Engineering Agent

### Objective

Create a reproducible live scoring pipeline.

### Tasks

1. Load latest point-in-time safe features.
2. Apply universe filters.
3. Generate model scores and ranks.
4. Export ranked list.
5. Include:
   - ticker
   - company name if available
   - sector
   - market cap
   - price
   - liquidity
   - score
   - rank
   - percentile
   - key features
   - risk flags
   - missing-data flags
   - reason codes or SHAP-style explanations
6. Ensure script does not depend on notebook state.

### Acceptance criteria

```text
[ ] Live scoring reproducible.
[ ] Filters applied.
[ ] Output diagnostics complete.
[ ] No uninvestable stocks included unintentionally.
[ ] Reviewers approve.
```

---

## Phase 9 — Documentation & Runbook

**Review needed:** No, unless methodology changed  
**Reviewer:** Code Reviewer Agent  
**Primary owner:** Documentation Agent

### Objective

Make the pipeline understandable and repeatable.

### Tasks

1. Document how to run:
   - data refresh
   - feature build
   - model training
   - walk-forward validation
   - portfolio backtest
   - live scoring
2. Document assumptions.
3. Document limitations.
4. Document go/no-go criteria.
5. Document reviewer workflow.

### Acceptance criteria

```text
[ ] README or runbook updated.
[ ] Commands documented.
[ ] Assumptions documented.
[ ] Limitations documented.
```

---

## Go / No-Go Criteria

### Research pass

```text
[ ] Point-in-time validation passed.
[ ] Walk-forward IC positive and stable.
[ ] Top quintile beats universe.
[ ] Primary horizon beats SPY.
[ ] Baseline factor comparison completed.
```

### Portfolio pass

```text
[ ] Monthly investable backtest implemented.
[ ] CAGR above SPY.
[ ] Sharpe above SPY or risk-adjusted return is better.
[ ] Max drawdown acceptable.
[ ] Transaction-cost adjusted return remains positive.
[ ] Turnover manageable.
[ ] Sector exposure acceptable.
```

### Live scoring pass

```text
[ ] Live picks pass liquidity filters.
[ ] Live picks pass market-cap filters.
[ ] Risk flags shown.
[ ] Reason codes shown.
[ ] No missing critical fields.
```

If any blocker remains, the model is a research tool only.
