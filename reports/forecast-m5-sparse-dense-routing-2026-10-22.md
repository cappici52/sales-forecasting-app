# M5 sparse/dense routing check — 22 October 2026

## Decision

**Keep the application's existing model unchanged.** A history-only rule for choosing a forecast method separately for sparse and dense items did not earn a switch in either group. It consequently matched the existing model exactly on the subsequent internal check: **48.00% weekly revenue WAPE**, with no gain. The predeclared promotion checks failed. This is a negative experimental result, not a new feature or a production model change.

## Boundaries and method

The data are the same public [M5 retailer record](https://zenodo.org/records/10203108) and 90 product/store series used in the [volume robustness check](forecast-m5-volume-robustness-2026-10-22.md). Source checksums, cohort, and benchmark implementation hashes were verified. The final M5 `d_1914`–`d_1941` results had already been examined in earlier work, so this experiment does **not** relabel those dates as a fresh holdout. It uses only earlier chronological windows:

| Role | Forecast origin | 28-day target |
| --- | --- | --- |
| Calibration 1 | 31 Jan 2016 | Feb 2016 |
| Calibration 2 | 28 Feb 2016 | Mar 2016 |
| Locked-rule internal check | 27 Mar 2016 | 28 Mar–24 Apr 2016 |

At each origin, a series is **dense** if at least 28 of the preceding 56 days had positive unit sales; otherwise it is **sparse**. No target-window sales enter this classification. Four fixed methods were compared in the first two windows: existing Poisson XGBoost, previous-week repetition, four-week mean, and the previously developed direct weekly absolute-error model. For each group, the lowest-weekly-WAPE alternative could replace the existing model only if its gain was at least **2 percentage points** and product/store 28-day WAPE was no worse. Otherwise that group retained the existing model. The choices, code/source hashes, third origin, and interpretation were written to `protocol.json` **before** scoring the third window. The one-time check wrote a consumed marker before reading its targets.

Weekly WAPE is summed absolute revenue error across four seven-day product/store blocks divided by actual revenue. Lower is better. It is not a percentage of correct predictions. This is one retailer, an already-studied cohort, and an internally checked chronological split—not independent external validation.

## Calibration and check

| Group, first two windows | Series-windows | Existing weekly WAPE | Previous week | Four-week mean | Direct weekly | Locked choice |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Sparse | 121 | 67.13% | 68.38% | 66.35% | **65.14%** | Existing |
| Dense | 59 | 36.12% | 44.36% | 35.54% | **35.09%** | Existing |

The direct model's sparse-group gain was **1.991 percentage points**, just under the frozen 2-point threshold; the dense-group gain was **1.04 points**. We did not lower the threshold after seeing this result. Thus the rule selected the existing model for both groups.

| Locked third-window method | Daily WAPE | Weekly WAPE | Product/store 28-day WAPE |
| --- | ---: | ---: | ---: |
| Existing Poisson, and identical routed rule | **95.55%** | **48.00%** | 37.26% |
| Previous week | 109.94% | 50.92% | 41.54% |
| Four-week mean | 95.60% | 48.14% | 35.39% |
| Direct weekly | 95.74% | 48.14% | **35.31%** |

On that check, 60 series were sparse and 30 dense. The routed rule forecasted all 2,520 product-days exactly as the existing model did. Its paired bootstrap weekly-gain interval versus the existing model is therefore **0 to 0 points**, and its 2-point improvement gate fails. The direct and four-week mean methods have lower product-total error in this one window, but their weekly and daily errors do not make a convincing overall replacement case; selecting them *after* seeing the check would invalidate it as a test of the locked rule.

The absolute error levels remain high, especially for sparse products. This experiment does not establish acceptable inventory-planning accuracy. It does establish that simply routing by recent selling-day frequency, under the stated standard, did not solve the problem. With no real business sales data, the final-project claim should be a reproducible public-data comparison with limitations, not a promise of real-world predictive accuracy.

## Files and verification

- Isolated experiment: `backend/scripts/benchmark_m5_routing.py`; tests: `backend/tests/test_benchmark_m5_routing.py`.
- Evidence: gitignored `outputs/m5_routing_2026-10-22/protocol.json`, `check_started.json`, and `result.json`. These are one-time artifacts; preserve them together.
- No PostgreSQL connection, application retraining, artifact promotion, or imported sales rows.

In a **clean workspace** with the same three verified M5 CSVs and earlier robustness protocol, the sequence from `backend/` is:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_m5_routing.py calibrate
.\.venv\Scripts\python.exe scripts\benchmark_m5_routing.py check
```

The check has already been consumed in this workspace. Running it again on the same period would not create fresh evidence.
