# Walk-Forward Validation Report

**Features**: 35

**Target**: ret_1y

**Fold structure**: train=5y rolling, test=1y

**Universe**: min_market_cap=1000000000 | min_price=5.00

**Embargo**: 12 months (prevents ret_1y label leakage into test window)


## Aggregate OOS Metrics

```
Metric                    XGBoost  Composite
----------------------------------------------
Mean Rank IC               0.0346     0.0362
Std Rank IC                0.0972        N/A
ICIR                       0.8133     0.3954
NW-ICIR                    3.3302     2.6031
Hit Rate                   0.5833     0.6332
Mean OOS R²               -0.6809        N/A
Q5-Q1 Spread               0.0473        N/A
N folds                        16
```


## Per-Fold Results

```
Fold       Test period               N train  N test   RankIC     ICIR   NW-ICIR  HitRate   Q-Spread
----------------------------------------------------------------------------------------------------
fold_00    2010-03 – 2011-02          13,467   5,958  -0.0232  -0.7048   -3.3784   0.2500     +2.12%
fold_01    2011-03 – 2012-02          18,527   6,559  -0.0116  -0.2673   -0.8214   0.3333     -2.87%
fold_02    2012-03 – 2013-02          22,275   6,924  -0.0618  -1.2165   -6.1017   0.1667     -7.51%
fold_03    2013-03 – 2014-02          22,197   7,872   0.0645   1.2408    3.1519   0.8333     +4.60%
fold_04    2014-03 – 2015-02          24,522   8,547   0.0441   0.7007    1.9692   0.8333     +7.56%
fold_05    2015-03 – 2016-02          27,313   8,849  -0.0096  -0.1355   -0.3338   0.4167     +0.94%
fold_06    2016-03 – 2017-02          29,902   9,222   0.1561   5.2087   26.5818   1.0000    +14.73%
fold_07    2017-03 – 2018-02          31,475   9,799   0.0712   1.8956   10.8602   0.9167     +7.63%
fold_08    2018-03 – 2019-02          34,490  10,089   0.1240   3.6017   12.5084   1.0000    +12.10%
fold_09    2019-03 – 2020-02          36,417  10,263   0.1735   4.9383   19.0805   1.0000    +21.32%
fold_10    2020-03 – 2021-02          37,959  10,347   0.0996   1.0935    2.6843   0.6667    +17.35%
fold_11    2021-03 – 2022-02          38,524  11,238  -0.1551  -2.6624   -7.4109   0.0000    -12.04%
fold_12    2022-03 – 2023-02          40,498  11,204   0.1237   1.3516    4.6204   0.8333    +22.00%
fold_13    2023-03 – 2024-02          41,937  11,315  -0.0828  -1.7958   -7.5433   0.0833     -9.44%
fold_14    2024-03 – 2025-02          43,052  11,527  -0.0750  -2.3668   -7.8516   0.0000     -8.97%
fold_15    2025-03 – 2026-02          43,162   2,845   0.1164   2.1310    5.2676   1.0000     +6.15%
```


## Yearly OOS Performance

```
  Year   Mean Rank IC   Hit Rate   Mean OOS R²
------------------------------------------------
  2010        -0.0232     0.2500       -0.8927
  2011        -0.0116     0.3333       -0.3952
  2012        -0.0618     0.1667       -0.2906
  2013         0.0645     0.8333       -0.0056
  2014         0.0441     0.8333       -0.3795
  2015        -0.0096     0.4167       -6.3440
  2016         0.1561     1.0000       -0.6464
  2017         0.0712     0.9167       -0.5724
  2018         0.1240     1.0000       -0.3470
  2019         0.1735     1.0000        0.0288
  2020         0.0996     0.6667       -0.2344
  2021        -0.1551     0.0000       -0.5908
  2022         0.1237     0.8333        0.0038
  2023        -0.0828     0.0833       -0.1187
  2024        -0.0750     0.0000       -0.0767
  2025         0.1164     1.0000       -0.0335
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
composite (full-sample)     0.0362   0.3954    2.6031     0.6332
```

> Note: baseline ICs are computed on the full dataset (all dates at once). These are not OOS metrics and should only be used as a directional reference.


## Feature Importance (mean across folds)

```
Feature                                   Mean Importance
----------------------------------------------------------
earnings_yield                                     0.0520
roa                                                0.0499
momentum_12_1                                      0.0482
roe                                                0.0481
earnings_quality                                   0.0473
ptbv                                               0.0454
pbv                                                0.0438
ps_ratio                                           0.0437
asset_growth                                       0.0419
fcf_yield                                          0.0409
roic                                               0.0382
interest_coverage                                  0.0320
roa_stability_5y                                   0.0278
ev_ebitda                                          0.0268
fcf_margin_5y_median                               0.0255
gross_margin_5y_median                             0.0254
ps_ratio_norm                                      0.0249
earnings_yield_norm                                0.0245
ps_rolling_5yr_median                              0.0243
dividend_yield                                     0.0237
```
