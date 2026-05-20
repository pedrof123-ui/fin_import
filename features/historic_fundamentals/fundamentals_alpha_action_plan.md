# Action Plan: Validate and Improve the Fundamental Stock Prediction Model

## Purpose

This plan is for a quant finance developer improving the current Python/XGBoost fundamental stock-selection model.

The model currently shows promising walk-forward stock-selection signal, especially versus the equal-weight universe. However, it should not yet be treated as a fully validated investable strategy until the methodology is made point-in-time safe, the backtest is converted into a true tradable portfolio simulation, and risk/liquidity controls are added.

## Current Assessment Snapshot

Based on the current walk-forward results:

| Horizon | ML Top 20% | Net After TC | Universe EW | SPY | vs Universe | vs SPY | Mean IC |
|---|---:|---:|---:|---:|---:|---:|---:|
| ret_1y | +23.03% | +22.99% | +16.04% | +14.90% | +6.99% | +8.13% | 0.0991 |
| ret_2y | +42.90% | +42.87% | +30.68% | +31.31% | +12.22% | +11.60% | 0.1493 |
| ret_3y | +61.90% | +61.87% | +44.26% | +48.82% | +17.64% | +13.07% | 0.2074 |
| ret_5y | +86.45% | +86.42% | +67.33% | +89.66% | +19.12% | -3.22% | 0.2131 |

### Interpretation

The model appears to have useful cross-sectional signal. It outperforms the equal-weight stock universe across horizons and outperforms SPY at 1-year, 2-year, and 3-year horizons. It does not outperform SPY at the 5-year horizon in the current results.

The current evidence is strong enough to continue development, but not strong enough to follow blindly with real capital.

---

# Guiding Principles

1. Preserve the existing project structure.
2. Do not create a parallel project layout.
3. Make the model point-in-time safe before trusting performance.
4. Evaluate stock-picking skill separately from tradable portfolio performance.
5. Compare against SPY, universe equal-weight, and simple factor baselines.
6. Add liquidity, sector, and quality controls before live use.
7. Treat model outputs as ranked candidates, not automatic buy orders.
8. Use walk-forward evaluation only; avoid random train/test splits.
9. Use adjusted prices and realistic availability dates.
10. Log every assumption.

---

# Phase 0 — Repository and Notebook Baseline

## Step 0.1 — Inspect Existing Project Structure

Review the current repository before modifying anything.

Identify:

- Existing data access modules
- Existing database connection utilities
- Existing feature engineering files
- Existing notebook dependencies
- Existing test framework
- Existing model-training scripts
- Existing output/reporting locations

Deliverable:

- Short `REPO_MAP.md` or inline notes describing where each major component lives.

Review needed: **Yes**

Reason: The project already has a structure. A human should confirm where new validation/backtest modules should be added.

---

## Step 0.2 — Freeze Current Notebook Results

Save the current notebook metrics as a baseline.

Capture:

- Walk-forward results table
- Mean IC by horizon
- SHAP importance table
- Top ranked stocks
- Current feature list
- Current universe filter logic
- Current transaction cost assumptions
- Current benchmark logic

Suggested output:

```text
reports/baseline_model_results_YYYYMMDD.md
reports/baseline_walk_forward_results_YYYYMMDD.csv
reports/baseline_shap_importance_YYYYMMDD.csv
```

Review needed: **Yes**

Reason: This establishes the benchmark that all later improvements must beat.

---

## Step 0.3 — Convert Notebook Logic into Reusable Modules

Move reusable logic out of the notebook where practical.

Candidate modules:

```text
data/
features/
models/
backtests/
reports/
tests/
```

Use existing project conventions instead of these names if the repository already has equivalent folders.

Deliverable:

- Notebook remains as a research/reporting layer.
- Core logic is available as importable Python functions.

Review needed: **Yes**

Reason: The developer should confirm that refactoring does not change baseline outputs.

---

# Phase 1 — Data Integrity and Point-in-Time Safety

## Step 1.1 — Audit Feature Date Alignment

Verify that every feature row uses only information that was available before the prediction date.

Required checks:

```text
feature_available_date <= prediction_date
target_start_date >= prediction_date
target_end_date > target_start_date
```

For each fundamental record, identify the best available date field:

1. SEC accepted date
2. SEC filing date
3. Earnings release date
4. Fiscal period end plus conservative lag

Deliverable:

```text
reports/feature_date_alignment_audit.csv
```

Review needed: **Yes**

Reason: Point-in-time leakage is the most important risk in the current model.

---

## Step 1.2 — Implement Conservative Availability Lag

If exact filing dates are unavailable, enforce conservative lags.

Recommended fallback:

```text
Quarterly fundamentals: fiscal_period_end + 60 days
Annual fundamentals: fiscal_year_end + 90 days
```

If filing dates exist:

```text
feature_available_date = filing_date + 1 trading day
```

Deliverable:

- Updated feature-generation logic.
- Clear config setting for lag assumption.

Review needed: **Yes**

Reason: This may reduce apparent performance. The assumption should be explicitly approved.

---

## Step 1.3 — Add Leakage Unit Tests

Create tests that fail if any feature date is after the prediction date.

Example test cases:

- No feature row with `feature_available_date > prediction_date`
- No target period overlaps with the feature calculation period
- Rolling metrics use only historical data
- Valuation features use price and shares known on or before prediction date

Deliverable:

```text
tests/test_point_in_time_integrity.py
```

Review needed: **No**

Reason: This is a core engineering requirement. Review final test outputs only.

---

## Step 1.4 — Validate Forward Return Construction

Confirm that `ret_6m`, `ret_1y`, `ret_2y`, `ret_3y`, and `ret_5y` are calculated from adjusted prices and are not using future survivorship-filtered data incorrectly.

Required checks:

- Adjusted close used for return calculation
- Splits and dividends handled
- Missing future prices documented
- Delisting or acquisition cases flagged
- Failed return calculations not silently removed without logging

Deliverable:

```text
reports/forward_return_construction_audit.md
```

Review needed: **Yes**

Reason: Bad target construction can materially overstate model quality.

---

# Phase 2 — Universe and Liquidity Controls

## Step 2.1 — Define Investable Universe Rules

Create an explicit investable universe filter.

Recommended starting rules:

```text
market_cap >= 1_000_000_000
price >= 5
avg_daily_dollar_volume_60d >= 5_000_000
exchange in allowed_exchanges
sector is not null
has required fundamental coverage
```

Also preserve a looser research universe for comparison:

```text
market_cap >= 300_000_000
price >= 3
```

Deliverable:

```text
config/universe_rules.yaml
reports/universe_filter_summary.csv
```

Review needed: **Yes**

Reason: Universe choice can materially change the strategy’s performance and practicality.

---

## Step 2.2 — Fix Market Cap Filter Inconsistencies

Ensure the live scoring output cannot include companies below the configured market cap minimum unless explicitly allowed.

Required checks:

- Market cap field exists for live scoring
- Missing market cap rows are excluded or separately flagged
- Live ranking table displays market cap, price, and liquidity
- Unit test confirms the filter is applied

Deliverable:

```text
tests/test_universe_filters.py
```

Review needed: **Yes**

Reason: The current live output may include very small or missing-market-cap names.

---

## Step 2.3 — Add Missing Data Policy

Define how the model handles missing values.

Recommended approach:

- Do not auto-fill critical fields like market cap, price, or sector.
- Allow model-safe imputation for non-critical features.
- Add missing-value indicator columns for important fields.
- Log missingness by feature and month.

Deliverable:

```text
reports/missing_data_profile.csv
```

Review needed: **Yes**

Reason: Missing values may create hidden model signals or distort live ranks.

---

# Phase 3 — Feature Engineering Improvements

## Step 3.1 — Add Core Margin and Quality Features

Add the smaller, high-quality feature set first:

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

Definitions:

```text
gross_margin = gross_profit / revenue
operating_margin = operating_income / revenue
fcf_margin = free_cash_flow / revenue
debt_to_ebitda = total_debt / EBITDA
interest_coverage = EBIT / interest_expense
```

Deliverable:

```text
features/quality_margin_features.py
tests/test_quality_margin_features.py
```

Use existing project file locations if different.

Review needed: **Yes**

Reason: Confirm financial definitions and treatment of negative/zero denominators.

---

## Step 3.2 — Add Sector-Relative Feature Versions

For major valuation and quality features, create sector-relative forms.

Examples:

```text
ps_ratio_sector_rank
fcf_yield_sector_rank
dividend_yield_sector_rank
operating_margin_sector_rank
roa_sector_rank
debt_to_ebitda_sector_rank
```

Use monthly cross-sectional ranks within sector.

Deliverable:

```text
features/sector_relative_features.py
```

Review needed: **Yes**

Reason: Sector normalization can change model behavior and should be inspected.

---

## Step 3.3 — Add Price Momentum and Relative Strength Features

Add price-based confirmation signals.

Recommended features:

```text
ret_3m
ret_6m
ret_12m
ret_12m_ex_1m
relative_strength_vs_spy_6m
relative_strength_vs_spy_12m
relative_strength_percentile_6m
relative_strength_percentile_12m
distance_from_52w_high
volatility_adjusted_momentum_12m
```

Deliverable:

```text
features/momentum_features.py
tests/test_momentum_features.py
```

Review needed: **Yes**

Reason: Adding momentum may materially improve results but changes the model from pure fundamentals to multi-factor.

---

## Step 3.4 — Add Estimate Revision Features When Data Is Available

If analyst estimate history is available, add:

```text
forward_revenue_revision_3m
forward_eps_revision_3m
forward_revenue_growth_1y
forward_eps_growth_1y
analyst_count
revision_breadth
```

If historical point-in-time estimate data is not available, skip this step.

Deliverable:

```text
features/estimate_revision_features.py
```

Review needed: **Yes**

Reason: Estimate data is powerful but must be point-in-time safe.

---

# Phase 4 — Baseline Factor Models

## Step 4.1 — Build Simple Factor Baselines

Before trusting XGBoost, compare it against simple transparent models.

Create the following baseline scores:

```text
low_ps_score
high_fcf_yield_score
high_dividend_yield_score
low_ev_ebitda_score
value_composite_score
quality_composite_score
value_quality_score
value_momentum_score
```

Suggested value composite:

```text
Value Score =
  30% inverted P/S rank
+ 25% FCF yield rank
+ 20% inverted EV/EBITDA rank
+ 15% earnings yield rank
+ 10% dividend yield rank
```

Deliverable:

```text
models/baseline_factor_models.py
reports/baseline_factor_comparison.csv
```

Review needed: **Yes**

Reason: XGBoost should be used only if it beats simple, explainable alternatives.

---

## Step 4.2 — Compare XGBoost Against Baselines

Run the same walk-forward evaluation for:

- XGBoost
- Value composite
- Quality composite
- Value + momentum composite
- Low P/S only
- High FCF yield only
- Universe equal-weight
- SPY

Deliverable:

```text
reports/model_vs_baselines_walk_forward.csv
```

Review needed: **Yes**

Reason: This is a key go/no-go decision.

---

# Phase 5 — Walk-Forward Model Validation

## Step 5.1 — Rebuild Walk-Forward Training as a Reproducible Pipeline

Create a scripted walk-forward runner.

Requirements:

- No random train/test split
- Train on historical data only
- Test on future monthly cohorts
- Save model predictions for every test month
- Save realized returns for every test month
- Save IC and portfolio bucket results

Deliverable:

```text
models/train_walk_forward.py
outputs/predictions_walk_forward.parquet
```

Review needed: **No**

Reason: This is implementation plumbing. Review the outputs in later steps.

---

## Step 5.2 — Evaluate Monthly Rank IC

For each horizon, compute:

```text
mean_ic
median_ic
ic_std
ic_t_stat
newey_west_ic_t_stat
icir_raw
icir_newey_west
monthly_hit_rate
```

Expected signs:

- Higher predicted return should map to higher future return.
- IC should be positive and stable.

Deliverable:

```text
reports/ic_summary_by_horizon.csv
reports/monthly_ic_timeseries.csv
```

Review needed: **Yes**

Reason: IC stability is central to judging whether the model is real.

---

## Step 5.3 — Evaluate Quintile and Decile Spreads

Each month, sort stocks by predicted score and create buckets.

Measure:

```text
top_decile_return
bottom_decile_return
top_minus_bottom
top_quintile_return
bottom_quintile_return
top_minus_bottom_quintile
monotonicity_score
```

Deliverable:

```text
reports/prediction_bucket_returns.csv
```

Review needed: **Yes**

Reason: A good model should produce ordered return buckets, not just a high average top bucket.

---

## Step 5.4 — Evaluate by Regime

Break performance into market regimes.

Suggested regimes:

```text
bull market
bear market
high inflation
low inflation
rising rates
falling rates
recession window
post-recession recovery
value-led market
growth-led market
```

At minimum, evaluate by calendar year.

Deliverable:

```text
reports/performance_by_year.csv
reports/performance_by_regime.csv
```

Review needed: **Yes**

Reason: A model that only works in one regime should not be followed blindly.

---

# Phase 6 — True Investable Portfolio Backtest

## Step 6.1 — Build Monthly Rebalanced Portfolio Simulator

Create a true monthly portfolio backtest, separate from forward-return ranking analysis.

Portfolio rules:

```text
rebalance_frequency = monthly
selection = top N stocks or top X percentile
holding_period = 1 month
weighting = equal weight initially
transaction_cost_bps = configurable
slippage_bps = configurable
max_position_weight = configurable
```

Test portfolios:

```text
top_20_percent
top_10_percent
top_50_names
top_25_names
top_10_names
```

Deliverable:

```text
backtests/monthly_portfolio_backtest.py
```

Review needed: **Yes**

Reason: This determines whether the model is actually tradable.

---

## Step 6.2 — Add Overlapping 12-Month Sleeve Backtest

Because the primary target is `ret_1y`, test a 12-sleeve portfolio.

Each month:

- Create a new top-ranked portfolio sleeve.
- Hold that sleeve for 12 months.
- Portfolio return equals average of active sleeves.

Deliverable:

```text
backtests/overlapping_sleeve_backtest.py
```

Review needed: **Yes**

Reason: This better aligns the 1-year forecast horizon with portfolio construction.

---

## Step 6.3 — Compare Against Benchmarks

Benchmark against:

```text
SPY
S&P 500 Equal Weight if available
Russell 1000 Value proxy
Russell 2000 Value proxy
Universe equal-weight
Simple value composite portfolio
Simple value + momentum portfolio
```

Deliverable:

```text
reports/portfolio_benchmark_comparison.csv
```

Review needed: **Yes**

Reason: Beating SPY alone is not enough if the model is really a value or small-cap strategy.

---

## Step 6.4 — Report Portfolio Performance Metrics

For each portfolio, calculate:

```text
CAGR
annualized volatility
Sharpe ratio
Sortino ratio
max drawdown
Calmar ratio
beta_to_spy
alpha_to_spy
tracking_error
information_ratio
monthly_win_rate_vs_spy
monthly_win_rate_vs_universe
turnover
average_number_of_holdings
largest_position_weight
sector_exposure
```

Deliverable:

```text
reports/portfolio_performance_summary.csv
reports/equity_curves.csv
```

Review needed: **Yes**

Reason: This is the main investment decision report.

---

# Phase 7 — Risk Controls and Portfolio Guardrails

## Step 7.1 — Add Sector Exposure Constraints

Add configurable sector caps.

Example:

```text
max_sector_weight = 25%
max_industry_weight = 15%
```

Alternative:

```text
sector_neutral = true
```

Deliverable:

```text
portfolio/constraints.py
```

Review needed: **Yes**

Reason: Constraints may reduce returns but improve robustness.

---

## Step 7.2 — Add Quality and Distress Filters

Add optional portfolio guardrails.

Recommended filters:

```text
debt_to_ebitda <= 4
interest_coverage >= 2
operating_margin not severely negative
fcf_margin not severely negative
revenue_growth not collapsing
price >= 5
market_cap >= 1B
```

Also test less restrictive versions to avoid over-filtering.

Deliverable:

```text
portfolio/quality_filters.py
reports/filter_impact_analysis.csv
```

Review needed: **Yes**

Reason: These rules may remove both value traps and successful turnarounds.

---

## Step 7.3 — Add Momentum Confirmation Option

Create a version of the portfolio that only buys model-ranked stocks with acceptable price momentum.

Example:

```text
relative_strength_percentile_12m >= 40
or
ret_12m_ex_1m > 0
or
price_above_200dma = true
```

Deliverable:

```text
reports/momentum_filter_impact.csv
```

Review needed: **Yes**

Reason: Momentum confirmation may reduce value traps, but can also remove early turnaround winners.

---

# Phase 8 — Model Explainability and Stability

## Step 8.1 — Add Grouped SHAP Analysis

Group features into economic families:

```text
valuation
cash_flow_yield
earnings_yield
dividend_income
growth
quality
margin_trend
leverage
momentum
sector_relative
```

Calculate grouped SHAP importance by horizon.

Deliverable:

```text
reports/grouped_shap_importance.csv
```

Review needed: **Yes**

Reason: Group-level explainability is more useful than individual feature importance.

---

## Step 8.2 — Add SHAP Direction Checks

For key features, confirm that SHAP direction is economically sensible.

Expected behavior:

```text
lower ps_ratio -> higher predicted return
higher fcf_yield -> higher predicted return
higher dividend_yield -> higher predicted return up to a point
higher debt_to_ebitda -> lower predicted return, generally
higher interest_coverage -> higher predicted return, generally
higher operating_margin_slope -> higher predicted return
```

Deliverable:

```text
reports/shap_direction_checks.md
reports/shap_dependence_plots/
```

Review needed: **Yes**

Reason: Wrong-direction feature relationships may indicate leakage or unstable fitting.

---

## Step 8.3 — Add Feature Stability Report

For each walk-forward training window, save:

- Top 20 SHAP features
- Feature importance rank changes
- Feature correlation matrix
- Missingness by feature
- IC by feature

Deliverable:

```text
reports/feature_stability_by_window.csv
```

Review needed: **Yes**

Reason: A model whose important features change wildly may not be robust.

---

# Phase 9 — Robustness and Sensitivity Testing

## Step 9.1 — Test Different Universes

Run the full evaluation for:

```text
market_cap >= 300M
market_cap >= 1B
market_cap >= 5B
ex-financials
ex-biotech
S&P 500-like universe
Russell 1000-like universe
```

Deliverable:

```text
reports/universe_sensitivity_results.csv
```

Review needed: **Yes**

Reason: If results only work in illiquid small caps, the strategy is less practical.

---

## Step 9.2 — Test Transaction Cost Sensitivity

Run costs at:

```text
0 bps
10 bps
25 bps
50 bps
100 bps
```

Include slippage assumptions separately if possible.

Deliverable:

```text
reports/transaction_cost_sensitivity.csv
```

Review needed: **Yes**

Reason: High turnover strategies can lose their edge after costs.

---

## Step 9.3 — Test Portfolio Size Sensitivity

Evaluate:

```text
top 10 names
top 25 names
top 50 names
top 100 names
top 10%
top 20%
```

Deliverable:

```text
reports/portfolio_size_sensitivity.csv
```

Review needed: **Yes**

Reason: Strong results only in top 10 names may be unstable; broad top 20% may be less actionable.

---

## Step 9.4 — Test Model Hyperparameter Stability

Run a small hyperparameter grid or randomized search with walk-forward validation.

Track:

```text
performance consistency
feature stability
turnover
overfitting behavior
```

Deliverable:

```text
reports/xgboost_hyperparameter_sensitivity.csv
```

Review needed: **Yes**

Reason: A model that only works with one parameter setting may be fragile.

---

# Phase 10 — Live Scoring and Research Workflow

## Step 10.1 — Build Live Scoring Pipeline

Create a reproducible script that scores the current investable universe.

Required output columns:

```text
ticker
company_name
sector
industry
market_cap
price
avg_dollar_volume
model_score
score_percentile
rank
top_feature_contributions
ps_ratio
fcf_yield
dividend_yield
debt_to_ebitda
interest_coverage
relative_strength_12m
data_quality_flag
```

Deliverable:

```text
scripts/score_live_universe.py
outputs/live_model_scores_YYYYMMDD.csv
```

Review needed: **Yes**

Reason: Live rankings should be reviewed before any use.

---

## Step 10.2 — Add Candidate Review Report

Generate a human-readable report for top-ranked stocks.

For each top candidate, include:

```text
why model likes it
valuation summary
cash flow summary
quality summary
debt/risk summary
momentum summary
sector exposure
red flags
missing data warnings
```

Deliverable:

```text
reports/top_candidates_YYYYMMDD.md
```

Review needed: **Yes**

Reason: The model should produce candidates, not automatic buy decisions.

---

## Step 10.3 — Add Paper Trading Log

Track model recommendations over time before using real capital.

Each month save:

```text
top ranked stocks
selected portfolio
excluded stocks and reason
model version
feature version
universe version
benchmark prices
future realized returns when available
```

Deliverable:

```text
paper_trading/model_recommendations_log.csv
```

Review needed: **No**

Reason: The log should be automatic, but monthly results should be reviewed separately.

---

# Phase 11 — Go / No-Go Decision Framework

## Step 11.1 — Define Minimum Acceptance Criteria

Do not consider the model usable unless it passes most of these:

```text
No point-in-time leakage found
Investable backtest beats universe equal-weight after costs
Investable backtest beats SPY or has lower risk with acceptable alpha
Positive out-of-sample rank IC
Top bucket beats bottom bucket consistently
Results survive market-cap filters
Results survive transaction costs
Sector exposures are explainable and controlled
Drawdowns are acceptable
Live top names pass quality/liquidity checks
```

Deliverable:

```text
reports/model_acceptance_checklist.md
```

Review needed: **Yes**

Reason: This is the formal decision gate.

---

## Step 11.2 — Decide Model Usage Category

Classify the model into one of four categories:

```text
Category 1: Research only
Category 2: Idea generation
Category 3: Paper trading
Category 4: Live portfolio support
```

Suggested current classification:

```text
Category 2: Idea generation
```

Move to Category 3 only after a true investable portfolio backtest is completed.

Move to Category 4 only after paper trading and robustness testing.

Deliverable:

```text
reports/model_usage_decision.md
```

Review needed: **Yes**

Reason: This prevents premature live use.

---

# Recommended Implementation Order

## First 5 Actions

1. Freeze current notebook baseline.
   - Review needed: **Yes**

2. Audit point-in-time feature alignment.
   - Review needed: **Yes**

3. Fix universe and liquidity filters.
   - Review needed: **Yes**

4. Build true monthly investable backtest.
   - Review needed: **Yes**

5. Compare XGBoost against simple value, quality, and value + momentum baselines.
   - Review needed: **Yes**

## Then Add

6. Margin, quality, leverage, and momentum features.
   - Review needed: **Yes**

7. Grouped SHAP and feature stability reports.
   - Review needed: **Yes**

8. Portfolio risk constraints and quality filters.
   - Review needed: **Yes**

9. Live scoring and candidate review report.
   - Review needed: **Yes**

10. Paper trading log.
    - Review needed: **No**

---

# Suggested Codex Prompt

Use this prompt with OpenAI Codex inside VS Code:

```text
Read the existing repository structure and the attached action plan. Do not create a new project structure. Implement Phase 1 first: data integrity and point-in-time safety for the fundamentals alpha model. Reuse existing database utilities, feature-generation code, and test conventions. Add tests that prevent feature dates from occurring after prediction dates. After implementation, summarize files changed, tests run, tests not run and why, remaining risks, and next recommended step.
```

---

# Final Recommendation

The model is worth improving. It appears to contain real stock-selection signal, especially through valuation, cash-flow yield, dividend yield, and normalized fundamental features.

However, the model should not be followed directly until these items are complete:

```text
1. Point-in-time leakage audit
2. Investable monthly portfolio backtest
3. Liquidity and market-cap filters
4. Comparison against simple factor baselines
5. Sector and risk exposure analysis
6. Paper trading validation
```

Until then, use it as a ranked idea-generation engine, not as a live trading system.
