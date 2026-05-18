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
Mean Rank IC               0.0303     0.0334
Std Rank IC                0.0994        N/A
ICIR                       0.7161     0.3474
NW-ICIR                    2.2663     2.1941
Hit Rate                   0.5521     0.6070
Mean OOS R²               -0.4709        N/A
Q5-Q1 Spread               0.0460        N/A
N folds                        16
```


## Per-Fold Results

```
Fold       Test period               N train  N test   RankIC     ICIR   NW-ICIR  HitRate   Q-Spread
----------------------------------------------------------------------------------------------------
fold_00    2010-03 – 2011-02          13,467   5,958  -0.0216  -0.7779   -5.2465   0.1667     +1.47%
fold_01    2011-03 – 2012-02          18,527   6,559  -0.0571  -1.0568   -4.7650   0.0833     -4.84%
fold_02    2012-03 – 2013-02          22,275   6,924  -0.0360  -0.8731   -3.7800   0.2500     -4.47%
fold_03    2013-03 – 2014-02          22,197   7,872   0.0711   1.1121    2.8108   0.7500     +6.76%
fold_04    2014-03 – 2015-02          24,522   8,547   0.0587   0.8041    2.0154   0.8333     +8.63%
fold_05    2015-03 – 2016-02          27,313   8,849  -0.0316  -0.3587   -0.9000   0.2500     +0.30%
fold_06    2016-03 – 2017-02          29,902   9,222   0.1411   5.2505   25.2349   1.0000    +12.36%
fold_07    2017-03 – 2018-02          31,475   9,799   0.0914   2.2254   13.2709   1.0000     +8.37%
fold_08    2018-03 – 2019-02          34,490  10,089   0.1070   3.6212   13.0906   1.0000     +9.40%
fold_09    2019-03 – 2020-02          36,417  10,263   0.1691   4.7844   14.3579   1.0000    +22.89%
fold_10    2020-03 – 2021-02          37,959  10,347   0.0977   1.0498    2.5402   0.6667    +16.98%
fold_11    2021-03 – 2022-02          38,524  11,238  -0.1796  -2.8942   -8.5123   0.0000    -14.02%
fold_12    2022-03 – 2023-02          40,498  11,204   0.1117   1.3353    4.5221   0.8333    +21.42%
fold_13    2023-03 – 2024-02          41,937  11,315  -0.0888  -1.8752   -9.0359   0.0000    -10.53%
fold_14    2024-03 – 2025-02          43,052  11,527  -0.0652  -2.9845  -14.8270   0.0000     -7.62%
fold_15    2025-03 – 2026-02          43,162   2,845   0.1163   2.0952    5.4854   1.0000     +6.50%
```


## Yearly OOS Performance

```
  Year   Mean Rank IC   Hit Rate   Mean OOS R²
------------------------------------------------
  2010        -0.0216     0.1667       -0.9482
  2011        -0.0571     0.0833       -0.4757
  2012        -0.0360     0.2500       -0.2720
  2013         0.0711     0.7500       -0.0076
  2014         0.0587     0.8333       -0.3597
  2015        -0.0316     0.2500       -3.1867
  2016         0.1411     1.0000       -0.7027
  2017         0.0914     1.0000       -0.2962
  2018         0.1070     1.0000       -0.2362
  2019         0.1691     1.0000        0.0278
  2020         0.0977     0.6667       -0.2323
  2021        -0.1796     0.0000       -0.6059
  2022         0.1117     0.8333       -0.0114
  2023        -0.0888     0.0000       -0.1237
  2024        -0.0652     0.0000       -0.0704
  2025         0.1163     1.0000       -0.0334
```


## Baseline Factor IC Comparison

```
Factor                     Mean IC     ICIR   NW-ICIR   Hit Rate
-----------------------------------------------------------------
low_ps                      0.0513   0.3915    2.0947     0.6594
high_fcf_yield              0.0507   0.5083    3.1368     0.6769
high_div_yield              0.0463   0.3740    2.1734     0.5852
low_evebitda                0.0330   0.2756    1.6364     0.6026
low_pe                      0.0383   0.3409    2.0650     0.5983
high_earnings_yield         0.0203   0.2035    1.2906     0.5371
composite (full-sample)     0.0334   0.3474    2.1941     0.6070
```

> Note: baseline ICs are computed on the full dataset (all dates at once). These are not OOS metrics and should only be used as a directional reference.


## Feature Importance (mean across folds)

```
Feature                                   Mean Importance
----------------------------------------------------------
pbv                                                0.0651
ps_ratio                                           0.0575
momentum_12_1                                      0.0574
ptbv                                               0.0569
fcf_yield                                          0.0566
earnings_yield                                     0.0461
roe                                                0.0439
roa                                                0.0429
interest_coverage                                  0.0426
ps_ratio_norm                                      0.0324
roic                                               0.0317
fcf_margin_5y_median                               0.0285
ev_ebitda                                          0.0270
roa_stability_5y                                   0.0265
ps_rolling_5yr_median                              0.0259
earnings_yield_norm                                0.0251
dividend_yield                                     0.0247
gross_margin_5y_median                             0.0238
operating_margin_slope_5y                          0.0234
pe_ratio                                           0.0226
```
