# REVIEWER_APPROVAL_CRITERIA.md
## Reviewer Approval Criteria by Phase

Reviewer agents must read this file before approving any implementation phase.

---

## 1. Decision levels

Each review must return one of:

```text
APPROVE
REQUEST CHANGES
BLOCK
```

---

## 2. APPROVE criteria

Approve only when:

```text
[ ] All phase acceptance criteria are complete.
[ ] No blocker issues exist.
[ ] Tests pass or skipped tests are justified.
[ ] Implementation follows the existing project structure.
[ ] Methodology risk is addressed.
[ ] Results are reproducible.
[ ] The agent clearly documents what changed.
[ ] The next phase can safely begin.
```

---

## 3. REQUEST CHANGES criteria

Use `REQUEST CHANGES` when work is directionally correct but incomplete.

Examples:

```text
[ ] Missing unit tests.
[ ] Documentation incomplete.
[ ] Feature naming unclear.
[ ] Benchmark comparison incomplete.
[ ] Transaction costs not configurable.
[ ] Sector exposure report incomplete.
[ ] SHAP output lacks interpretation.
```

---

## 4. BLOCK criteria

Use `BLOCK` for serious methodology, data, or code-quality issues.

Blocker examples:

```text
[ ] Look-ahead bias exists.
[ ] Target leakage exists.
[ ] Future fundamentals are used before filing/availability date.
[ ] Future prices are used in features.
[ ] Random train/test split is used for final validation.
[ ] Overlapping forward returns are treated as a tradable equity curve.
[ ] SPY benchmark is misaligned.
[ ] Transaction costs are ignored in portfolio backtest.
[ ] Liquidity filters are missing.
[ ] Market-cap filter is not enforced.
[ ] Live scoring includes below-threshold stocks unintentionally.
[ ] Core tests fail.
[ ] Credentials are hard-coded.
[ ] Duplicate project structure created.
[ ] In-sample results are presented as final evidence.
```

---

# 5. Phase approval criteria

---

## Phase 0 — Repository Discovery

**Reviewer:** Code Reviewer Agent  
**Approval required:** Yes

Approve only if:

```text
[ ] Existing repo structure inspected.
[ ] Existing data modules identified.
[ ] Existing feature modules identified.
[ ] Existing model/notebook workflow identified.
[ ] Existing test framework identified.
[ ] Existing config/database utilities identified.
[ ] Proposed implementation locations are clear.
[ ] No duplicate project structure created.
[ ] No production code changed.
[ ] Integration map is understandable.
```

Block if:

```text
[ ] Agent writes implementation code before discovery.
[ ] Agent creates a parallel project structure.
[ ] Existing modules are ignored.
```

---

## Phase 1 — Point-in-Time Data Audit

**Reviewer:** Quant Reviewer Agent  
**Approval required:** Yes

Approve only if:

```text
[ ] Every feature has a valid feature date.
[ ] Every feature has availability date or conservative reporting lag.
[ ] feature_available_date <= prediction_date.
[ ] Target return starts after prediction_date.
[ ] No future fundamentals are used.
[ ] No future prices are used in features.
[ ] Filing date, accepted date, or reporting-lag policy documented.
[ ] Timing violations logged.
[ ] Tests cover timing alignment.
[ ] Remaining data-timing limitations documented.
```

Block if:

```text
[ ] Fiscal period-end data is used before filing availability.
[ ] Target-period data leaks into features.
[ ] Future prices are used to create features.
[ ] Prediction dates and feature dates are not explicitly aligned.
[ ] Point-in-time validation cannot be reproduced.
```

---

## Phase 2 — Investable Universe & Liquidity Filters

**Reviewer:** Quant Reviewer Agent  
**Approval required:** Yes

Approve only if:

```text
[ ] Market-cap filter enforced.
[ ] Price filter enforced.
[ ] Liquidity filter implemented if volume data exists.
[ ] Filters configurable.
[ ] Monthly universe counts reported.
[ ] Missing market cap, price, volume, or sector data handled.
[ ] Live scoring cannot include below-threshold stocks unless explicitly allowed.
[ ] Sensitivity runs produced for $300M, $1B, and $5B thresholds.
[ ] Investable universe documented.
```

Block if:

```text
[ ] Microcaps appear in live output unintentionally.
[ ] Missing market cap bypasses filter.
[ ] Liquidity is ignored in investable portfolio test.
[ ] Universe differs inconsistently between training, backtest, and live scoring.
```

---

## Phase 3 — Feature Engineering Improvements

**Reviewers:** Code Reviewer Agent and Quant Reviewer Agent  
**Approval required:** Yes

Approve only if:

```text
[ ] Feature formulas are correct.
[ ] Unit tests exist for each new formula or formula family.
[ ] Features are point-in-time safe.
[ ] Missing values handled.
[ ] Infinite values handled.
[ ] Extreme values handled or winsorized according to policy.
[ ] Feature names clear and consistent.
[ ] Sector-relative versions added where appropriate.
[ ] Expected direction of each feature documented.
[ ] Feature documentation updated.
```

Block if:

```text
[ ] Margin formulas are wrong.
[ ] Debt ratios are sign-inverted.
[ ] Features use future annual data.
[ ] Missing values are filled in a way that creates false signal.
[ ] New features break existing model or backtest pipeline.
```

---

## Phase 4 — Baseline Factor Models

**Reviewer:** Quant Reviewer Agent  
**Approval required:** Yes

Approve only if:

```text
[ ] Simple baselines implemented.
[ ] XGBoost compared against simple factor models.
[ ] Baselines use same universe as XGBoost.
[ ] Baselines use same dates as XGBoost.
[ ] Baselines use same return targets as XGBoost.
[ ] IC reported.
[ ] Quintile/decile spread reported.
[ ] Portfolio performance reported where applicable.
[ ] Results interpreted honestly.
```

Block if:

```text
[ ] XGBoost declared successful without simple-factor comparison.
[ ] Baselines use a different universe or test period.
[ ] Baseline implementation contains look-ahead bias.
```

---

## Phase 5 — Walk-Forward Model Validation

**Reviewer:** Quant Reviewer Agent  
**Approval required:** Yes

Approve only if:

```text
[ ] Time-based walk-forward splits are used.
[ ] No random train/test split used for final results.
[ ] In-sample and out-of-sample metrics separated.
[ ] OOS R² reported.
[ ] Rank IC reported.
[ ] ICIR reported.
[ ] Hit rate reported.
[ ] Quintile/decile spread reported.
[ ] Results shown by year or regime.
[ ] Feature importance stability reviewed.
[ ] SHAP results directionally plausible.
[ ] Primary target clearly identified.
```

Block if:

```text
[ ] Random splits used for final validation.
[ ] In-sample R² presented as final evidence.
[ ] Walk-forward dates are unclear.
[ ] Training data overlaps improperly with test target periods.
[ ] Target construction inconsistent across horizons.
```

---

## Phase 6 — True Monthly Portfolio Backtest

**Reviewer:** Quant Reviewer Agent  
**Approval required:** Yes

Approve only if:

```text
[ ] Portfolio returns are non-overlapping monthly returns.
[ ] Rebalance schedule explicit.
[ ] Portfolio construction method explicit.
[ ] Top 20%, top 10%, top 50, and top 25 portfolios tested.
[ ] Equal-weight portfolio included.
[ ] Capped-weight portfolio included or explicitly deferred.
[ ] Transaction costs included.
[ ] Turnover calculated.
[ ] SPY benchmark aligned to same dates.
[ ] Equal-weight universe benchmark included.
[ ] Simple factor baselines included.
[ ] CAGR reported.
[ ] Annualized volatility reported.
[ ] Sharpe ratio reported.
[ ] Sortino ratio reported if available.
[ ] Max drawdown reported.
[ ] Beta to SPY reported.
[ ] Information ratio reported.
```

Block if:

```text
[ ] Overlapping 1-year forward returns are compounded as portfolio equity curve.
[ ] Transaction costs ignored.
[ ] SPY dates do not match model test dates.
[ ] Portfolio cannot be realistically traded.
[ ] Universe filters not applied consistently.
```

---

## Phase 7 — Risk Diagnostics & Guardrails

**Reviewer:** Quant Reviewer Agent  
**Approval required:** Yes

Approve only if:

```text
[ ] Sector exposure reported.
[ ] Industry exposure reported if available.
[ ] Market-cap exposure reported.
[ ] Portfolio beta to SPY reported.
[ ] Drawdown reported.
[ ] Position concentration reported.
[ ] Factor exposure reported where possible.
[ ] Guardrails configurable.
[ ] Performance with and without guardrails compared.
[ ] Live value-trap risk flagged.
```

Block if:

```text
[ ] Portfolio concentrated in one sector without disclosure.
[ ] Live picks include obvious distressed value traps without flags.
[ ] Risk controls hard-coded and not configurable.
[ ] Drawdown or beta not reported.
```

---

## Phase 8 — Live Scoring Pipeline

**Reviewers:** Code Reviewer Agent and Quant Reviewer Agent  
**Approval required:** Yes

Approve only if:

```text
[ ] Live scoring uses latest point-in-time safe data.
[ ] Universe filters are applied.
[ ] Scores are reproducible.
[ ] Output includes ticker, score, rank, sector, market cap, liquidity, key features.
[ ] Output includes risk flags.
[ ] Output includes missing-data flags.
[ ] Output includes reason codes or SHAP-style explanations.
[ ] No below-threshold stocks appear unless explicitly allowed.
[ ] Script does not depend on notebook state.
```

Block if:

```text
[ ] Live output includes uninvestable stocks unintentionally.
[ ] Feature dates are not validated.
[ ] Scoring script depends on notebook state.
[ ] Results are not reproducible.
[ ] Live scoring bypasses risk filters.
```

---

## Phase 9 — Documentation & Runbook

**Reviewer:** Code Reviewer Agent  
**Approval required:** No, unless methodology changed

Approve only if:

```text
[ ] README or runbook explains how to run pipeline.
[ ] Data requirements documented.
[ ] Model assumptions documented.
[ ] Feature definitions documented.
[ ] Backtest methodology documented.
[ ] Live scoring process documented.
[ ] Known limitations documented.
[ ] Go/no-go criteria documented.
```

Block only if:

```text
[ ] Documentation falsely represents model readiness.
[ ] Documentation hides known methodology limitations.
```

---

## 6. Required reviewer output format

```markdown
## Review Result

### Decision
APPROVE / REQUEST CHANGES / BLOCK

### Severity
blocker / major / minor

### Phase reviewed
-

### Files reviewed
-

### Evidence reviewed
-

### Findings
-

### Required fixes
-

### Optional improvements
-

### Can the next phase proceed?
Yes/No
```

---

## 7. Simple escalation rule

```text
If the issue can distort backtest results -> BLOCK.
If the issue weakens confidence but does not invalidate results -> REQUEST CHANGES.
If the issue is cosmetic or documentation-level -> MINOR / APPROVE WITH NOTES.
```

---

## 8. Ten most important approval criteria

```text
1. No look-ahead bias.
2. No target leakage.
3. True walk-forward validation.
4. True monthly portfolio backtest.
5. Liquidity and market-cap filters.
6. Transaction costs.
7. Benchmark alignment versus SPY.
8. Baseline factor comparison.
9. Risk exposure diagnostics.
10. Reproducible live scoring.
```
