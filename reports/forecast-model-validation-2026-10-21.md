# Forecast objective and promotion check — 21 October 2026

## Result

Added a price-weighted absolute-error XGBoost candidate alongside the existing Poisson models and weekly baseline. It optimizes a loss closer to revenue WAPE while retaining quantity outputs, recursive forecasting, and the last-observed-price assumption. Negative quantities are clamped to zero. This does not solve price changes, promotions, stock-outs, or unpredictable bulk orders.

Candidates are selected on up to three earlier chronological windows. A separate latest 28-day window must also favor the proposed weighted model over the Poisson/weekly incumbent before promotion. Selection is independent for 7, 14, and 28 days. With insufficient history for a separate check, weighted candidates are not promoted. The confirmation period is used for promotion and **must not be represented as an untouched accuracy estimate**.

The audit now uses the actual application training and artifact-loading path in a temporary directory, then evaluates a further final 28 days excluded from all fitting, method selection, and promotion. Its result includes all three forecast horizons. No sales data are written during audits.

## Public-data results

28-day revenue WAPE (lower is better), compared with the preceding version-3 selector:

| Source | Previous selector | Updated selector | Updated method |
| --- | ---: | ---: | --- |
| Olist category proxies | 53.79% | 53.79% | Price-weighted Poisson |
| UCI Retail II 2010, six SKUs | 67.96% | 67.15% | Price-weighted absolute error |
| Rossmann, six aggregate stores | 7.98% | 7.73% | Price-weighted absolute error |
| App's UCI 2011 demo, six SKUs | 56.77% | 56.77% | Original Poisson |

| Updated selector | 7-day WAPE | 14-day WAPE | 28-day WAPE |
| --- | ---: | ---: | ---: |
| Olist | 49.99% | 66.07% | 53.79% |
| Retail II | 53.11% | 68.65% | 67.15% |
| Rossmann | 6.86% | 7.06% | 7.73% |
| App UCI demo | 66.38% | 66.12% | 56.77% |

Improvements are not universal: Retail II's 7-day score regresses from the previous weighted selector's 50.36% to 53.11%, despite passing earlier checks. No further tuning was made to remove that visible regression. The seasonal mean/blend experiment was not deployed because its selected Olist model worsened final performance. The absolute-error candidate alone would worsen the app UCI 28-day result from 56.77% to 65.56%; the promotion check rejects it.

All these public periods have been examined in earlier experiments or during this development. They are exploratory evidence, not fresh independent confirmation or evidence of accuracy on the owner's business. Rossmann is aggregate store revenue rather than item-level demand. Revenue WAPE is not a percentage of forecasts that are correct, and 1 − WAPE should not be presented as accuracy.

## Local app activation

Retrained through the application's training handler against the configured main PostgreSQL database. Run **27** completed, retaining previous run **26** and the existing **1,440 sales rows**. The new version-4 artifact selected original Poisson for all three horizons; it created **168 forecast snapshots**, covering all six series for 28 days. Daily, segment, and stored snapshot totals agree within rounding. Quality correctly remains `review` for `high_revenue_error` and `stale_data`; the demo ends on 30 November 2011.

Version-1/2/3 artifacts remain loadable by the updated code. Restart a backend that was running without reload before using version-4 artifacts. The app still exposes original Poisson diagnostics for backward compatibility, and additionally provides selected-method metrics, promotion decisions, origins, and confirmation scores. Quality flags now inspect the selected method and the confirmation period.

## Reproduction

From `C:\ProjectA\backend`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe scripts\benchmark_seasonal_challenger.py olist --audit
.\.venv\Scripts\python.exe scripts\benchmark_seasonal_challenger.py retail_ii --audit
.\.venv\Scripts\python.exe scripts\benchmark_seasonal_challenger.py rossmann --audit
.\.venv\Scripts\python.exe scripts\benchmark_seasonal_challenger.py postgres --audit
```

Omit `--audit` to reproduce the exploratory fixed-candidate comparison. The local public source files are the same ones documented in `forecast-error-diagnosis-2026-10-21.md`; raw data and trained artifacts are not source-code assets.

Objective reference: [XGBoost learning-task parameters](https://github.com/dmlc/xgboost/blob/master/doc/parameter.rst). Price weighting makes quantity absolute error equivalent to revenue absolute error only when the applied price matches the target price; future unknown prices remain an important limitation.
