# Walk-Forward Validation Report

**Features**: 33

**Target**: ret_1y

**Fold structure**: train=5y rolling, test=1y

**Universe**: min_market_cap=1000000000 | min_price=5.00

**Embargo**: 12 months (prevents ret_1y label leakage into test window)


## Aggregate OOS Metrics

```
Metric                    XGBoost  Composite
----------------------------------------------
Mean Rank IC               0.0443     0.0344
Std Rank IC                0.0963        N/A
ICIR                       1.0384     0.4008
NW-ICIR                    4.3411     2.7103
Hit Rate                   0.6719     0.6812
Mean OOS R²               -0.3789        N/A
Q5-Q1 Spread               0.0489        N/A
N folds                        16
```


## Per-Fold Results

```
Fold       Test period               N train  N test   RankIC     ICIR   NW-ICIR  HitRate   Q-Spread
----------------------------------------------------------------------------------------------------
fold_00    2010-03 – 2011-02          16,884   7,553   0.0527   2.0784    8.1548   1.0000     +5.08%
fold_01    2011-03 – 2012-02          23,275   8,332  -0.0180  -0.4187   -1.1770   0.4167     -2.10%
fold_02    2012-03 – 2013-02          28,173   8,825  -0.0377  -0.9603   -4.8386   0.1667     -2.15%
fold_03    2013-03 – 2014-02          28,126  10,194   0.0508   2.0107    6.6028   1.0000     -7.94%
fold_04    2014-03 – 2015-02          31,122  11,067   0.0495   0.7562    1.9145   0.8333     +6.66%
fold_05    2015-03 – 2016-02          34,904  11,469  -0.0552  -0.5391   -1.3152   0.2500     -2.08%
fold_06    2016-03 – 2017-02          38,418  11,991   0.1662   5.7085   29.0499   1.0000    +13.69%
fold_07    2017-03 – 2018-02          40,624  12,789   0.0907   2.3561    8.6301   0.9167     +7.98%
fold_08    2018-03 – 2019-02          44,721  13,244   0.0816   1.9852   14.5786   1.0000     +7.21%
fold_09    2019-03 – 2020-02          47,316  13,454   0.1318   2.1464    5.4422   1.0000    +16.03%
fold_10    2020-03 – 2021-02          49,493  13,356   0.1375   1.2148    2.9929   0.7500    +20.65%
fold_11    2021-03 – 2022-02          50,371  14,723  -0.1751  -3.2296  -14.8671   0.0000    -14.30%
fold_12    2022-03 – 2023-02          52,843  14,599   0.1697   2.7189   13.3859   1.0000    +24.20%
fold_13    2023-03 – 2024-02          54,777  14,693  -0.0311  -0.6646   -2.7638   0.2500     -2.66%
fold_14    2024-03 – 2025-02          56,132  15,015  -0.0367  -0.8882   -2.6143   0.1667     -1.33%
fold_15    2025-03 – 2026-02          56,142   3,722   0.1318   2.3391    6.2817   1.0000     +9.28%
```


## Yearly OOS Performance

```
  Year   Mean Rank IC   Hit Rate   Mean OOS R²
------------------------------------------------
  2010         0.0527     1.0000       -0.8402
  2011        -0.0180     0.4167       -0.3292
  2012        -0.0377     0.1667       -0.3271
  2013         0.0508     1.0000       -0.0096
  2014         0.0495     0.8333       -0.3360
  2015        -0.0552     0.2500       -1.8766
  2016         0.1662     1.0000       -0.7407
  2017         0.0907     0.9167       -0.2672
  2018         0.0816     1.0000       -0.2461
  2019         0.1318     1.0000        0.0009
  2020         0.1375     0.7500       -0.2814
  2021        -0.1751     0.0000       -0.5862
  2022         0.1697     1.0000       -0.0177
  2023        -0.0311     0.2500       -0.1242
  2024        -0.0367     0.1667       -0.0576
  2025         0.1318     1.0000       -0.0243
```


## Baseline Factor IC Comparison

```
Factor                     Mean IC     ICIR   NW-ICIR   Hit Rate
-----------------------------------------------------------------
low_ps                      0.0628   0.5084    2.7300     0.7336
high_fcf_yield              0.0454   0.4426    2.7951     0.6725
high_div_yield              0.0384   0.2883    1.6792     0.6157
low_evebitda                0.0427   0.3676    2.1744     0.6507
low_pe                      0.0386   0.3204    1.9263     0.5939
high_earnings_yield         0.0224   0.2193    1.3715     0.6114
composite (full-sample)     0.0344   0.4008    2.7103     0.6812
```

> Note: baseline ICs are computed on the full dataset (all dates at once). These are not OOS metrics and should only be used as a directional reference.


## Feature Importance (mean across folds)

```
Feature                                   Mean Importance
----------------------------------------------------------
momentum_12_1                                      0.0686
ptbv                                               0.0677
pbv                                                0.0647
ps_ratio                                           0.0572
fcf_yield                                          0.0508
interest_coverage                                  0.0474
earnings_yield                                     0.0451
roe                                                0.0404
roa                                                0.0399
roa_stability_5y                                   0.0318
ev_ebitda                                          0.0298
roic                                               0.0296
earnings_yield_norm                                0.0275
ps_ratio_norm                                      0.0258
dividend_yield                                     0.0254
roa_rolling_5yr_median                             0.0243
pe_ratio                                           0.0239
pfcf_ratio                                         0.0238
gross_margin_5y_median                             0.0232
fcf_margin_5y_median                               0.0226
```

## SHAP Feature Stability

```
Feature                                   Mean |SHAP|
------------------------------------------------------
roa                                            0.0300
momentum_12_1                                  0.0288
ps_ratio                                       0.0164
dividend_yield                                 0.0154
roe                                            0.0153
ptbv                                           0.0141
earnings_yield                                 0.0140
interest_coverage                              0.0131
operating_margin_slope_5y                      0.0129
earnings_yield_norm                            0.0117
fcf_yield                                      0.0101
operating_margin_change_3y                     0.0100
pbv                                            0.0096
roa_rolling_5yr_median                         0.0092
roa_stability_5y                               0.0075
roic                                           0.0072
pe_ratio                                       0.0070
pe_rolling_5yr_median                          0.0070
debt_to_ebitda                                 0.0067
pfcf_ratio                                     0.0066
```
