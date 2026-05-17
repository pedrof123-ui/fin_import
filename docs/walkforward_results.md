# Walk-Forward Validation Results

**Target**: `ret_1y` (primary — `ret_1y` per ACTION_PLAN.md Phase 5)

**Universe**: 1400 tickers | min_market_cap=1000000000 | min_price=5.00

**Folds**: 16 | Train 5yr | Test 1yr


> In-sample R² (`ins_r2_diagnostic`) is shown for diagnostic purposes only. It is NOT final evidence. OOS metrics are the valid results.


## Per-Fold OOS Results

```
Fold     Train end    Test start   Test end       OOS R2      IC    ICIR  ICIR_NW   Hit%   N_OBS
------------------------------------------------------------------------------------------------
fold_00  2010-02-28   2010-03-31   2011-02-28    -0.6042  0.0337  1.2828   7.6357 0.8333    7585
fold_01  2011-02-28   2011-03-31   2012-02-29    -0.3521 -0.0521 -1.1431  -3.0994 0.0000    8306
fold_02  2012-02-29   2012-03-31   2013-02-28    -0.3501 -0.0424 -1.9860 -10.4245 0.0000    8893
fold_03  2013-02-28   2013-03-31   2014-02-28    -0.0085  0.0524  1.1494   2.7243 0.8333   10244
fold_04  2014-02-28   2014-03-31   2015-02-28    -0.2819  0.0208  0.2614   0.6082 0.5000   10993
fold_05  2015-02-28   2015-03-31   2016-02-29    -2.8211 -0.0812 -1.1070  -2.7150 0.1667   11422
fold_06  2016-02-29   2016-03-31   2017-02-28    -0.7918  0.1566  5.6944  18.1108 1.0000   12100
fold_07  2017-02-28   2017-03-31   2018-02-28    -0.6189  0.0871  2.5138  13.2640 1.0000   12829
fold_08  2018-02-28   2018-03-31   2019-02-28    -0.9864  0.0434  1.0625   4.3196 0.8333   13162
fold_09  2019-02-28   2019-03-31   2020-02-29     0.0134  0.1926  4.3212  10.5283 1.0000   13196
fold_10  2020-02-29   2020-03-31   2021-02-28    -0.3202  0.0350  0.4631   1.1611 0.6667   13543
fold_11  2021-02-28   2021-03-31   2022-02-28    -0.6260 -0.1871 -3.2434 -16.1636 0.0000   14711
fold_12  2022-02-28   2022-03-31   2023-02-28    -0.0895  0.1682  2.8094  11.4363 1.0000   14625
fold_13  2023-02-28   2023-03-31   2024-02-29    -0.1331 -0.0107 -0.3084  -1.7634 0.4167   14847
fold_14  2024-02-29   2024-03-31   2025-02-28    -0.0580 -0.0088 -0.1911  -0.4441 0.4167   15332
fold_15  2025-02-28   2025-03-31   2026-02-28    -0.0221  0.1316  3.6702  14.0779 1.0000    5155
```


## Aggregate OOS Metrics

```
mean_oos_r2: -0.5032
std_oos_r2: 0.6883
mean_rank_ic: 0.0337
std_rank_ic: 0.1001
mean_rank_icir: 0.9531
std_rank_icir: 2.3910
mean_rank_icir_nw: 3.0785
std_rank_icir_nw: 9.1958
mean_hit_rate: 0.6042
std_hit_rate: 0.3926
mean_quintile_spread: 0.0348
n_folds: 16
```


## Yearly Mean IC

```
Year     Mean IC  N Folds
----------------------------
2010      0.0337        1
2011     -0.0521        1
2012     -0.0424        1
2013      0.0524        1
2014      0.0208        1
2015     -0.0812        1
2016      0.1566        1
2017      0.0871        1
2018      0.0434        1
2019      0.1926        1
2020      0.0350        1
2021     -0.1871        1
2022      0.1682        1
2023     -0.0107        1
2024     -0.0088        1
2025      0.1316        1
```


## Feature Importance (Top 20)

```
Feature                                   Mean Importance
------------------------------------------------------------
earnings_yield                                   0.077573
pbv                                              0.064486
ps_ratio                                         0.059267
ptbv                                             0.056068
interest_coverage                                0.047055
fcf_yield                                        0.044824
roa                                              0.044326
roic                                             0.042550
ps_rolling_5yr_median                            0.042389
roe                                              0.039172
ev_ebitda                                        0.036246
dividend_yield                                   0.034768
roa_rolling_5yr_median                           0.034293
roa_stability_5y                                 0.030547
operating_margin_slope_5y                        0.030354
pe_rolling_5yr_median                            0.028910
pe_ratio                                         0.028491
pfcf_ratio                                       0.028204
fcf_margin_5y_median                             0.027480
roic_rolling_5yr_median                          0.026658
```


## SHAP Stability (Top 20)

```
roa                                      0.029640
ps_ratio                                 0.024332
earnings_yield                           0.022012
roe                                      0.019564
dividend_yield                           0.014883
operating_margin_slope_5y                0.014712
ptbv                                     0.014582
interest_coverage                        0.013075
pbv                                      0.011802
roa_rolling_5yr_median                   0.011482
ps_rolling_5yr_median                    0.011417
fcf_yield                                0.010959
operating_margin_change_3y               0.010099
ev_ebitda                                0.008766
pe_rolling_5yr_median                    0.008565
roic                                     0.007199
pfcf_ratio                               0.007069
ev_ebitda_rolling_5yr_median             0.006874
pe_ratio                                 0.006873
roa_stability_5y                         0.006740
```
