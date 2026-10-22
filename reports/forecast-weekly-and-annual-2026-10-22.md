# Weekly, revenue-target, and prior-year forecast experiments

## Decision

**Do not promote a new production model.** Three further directions were tested after the bulk-order split experiment: direct weekly quantities with per-series selection, direct weekly revenue, and prior-year demand features with fixed model blends. Development improvements did not survive the reserved product checks consistently. The main PostgreSQL database, sales data, model run, and deployed artifacts were not changed by this work.

This does not establish that the existing model is accurate enough. It establishes that these challengers have not earned replacement of that model. WAPE measures error, not accuracy, and can exceed 100%.

## Data and evaluation boundaries

- Source: UCI Online Retail II, Daqing Chen, DOI `10.24432/C5CG6D`, CC BY 4.0. Local source archive SHA-256: `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb`.
- UK positive-quantity, positive-price, non-cancelled product transactions. No customer identifiers were read. Large orders were retained; this is gross sales, not net sales after returns.
- Daily quantity and weighted unit price were aggregated per product. Missing transaction dates were explicitly zero-filled in this complete public extract, not treated as confirmed stock availability. Prices were forward-filled from known history and rounded to six decimals. GBP x 40 is only a demo denomination, not a historical exchange rate.
- The annual experiment uses both workbook sheets, taking the earlier sheet strictly before 1 December 2010 and the later sheet on/after that date to prevent overlapping dates being counted twice. It prepared 44,769 daily rows for 66 products. These rows were not imported into the main app.
- Development origins: 10 August, 7 September, and 5 October 2011, each forecasting 28 days. Final origin: 2 November, scoring 3–30 November. All preprocessing used for modeling is limited to the forecast origin; final labels are used only for scoring.
- The original comparator refits the existing Poisson XGBoost procedure using history from 5 April 2011. Annual candidates use the longer history. The `extended` control adds history without annual features. These are refitted procedures, not tests of an unchanged production artifact.
- Daily WAPE scores individual product-days. Weekly WAPE sums the same predictions into four consecutive seven-day blocks per product. SKU 28-day WAPE sums per product before absolute error. Business-total error allows errors between products to cancel and is not the promotion objective.
- Product cohorts were selected by pre-cutoff revenue and activity. New products are **from the same retailer and familiar dates**, not an independent future period or business. Models are fitted to their own pre-cutoff cohort history; this is not zero-shot prediction of unseen product IDs.

## 1. Direct weekly quantities and selection

Implemented normalized direct 1–4-week quantity models, recent weekly mean/median baselines, and fixed blends. Weekly totals are distributed using weekday shares estimated from past data only. Selection rules use the first two rolling folds and are checked on the third; the per-series rule was frozen before the new 24-product check.

The first development pool contained the six familiar products and the twelve products already consumed by the previous bulk-order experiment. The new cohort was frozen separately; after scoring it was treated as development data for subsequent experiments, never called untouched again.

| New 24-product check | Daily WAPE | Weekly WAPE | SKU 28-day WAPE |
| --- | ---: | ---: | ---: |
| Original XGBoost | 76.18% | 47.77% | 42.08% |
| Previous-week baseline | 91.02% | **44.20%** | **37.10%** |
| Selected weekly procedure | 78.49% | 45.67% | 37.40% |

Rejected: daily error regressed, weekly error did not beat the simpler baseline, and the latest rolling calibration gate also failed. Paired product bootstrap 95% interval for weekly WAPE gain versus original: **-3.05 to +7.95 percentage points**, crossing zero.

## 2. Forecast revenue directly

Used the now-familiar 42 products to compare forecasting daily/weekly revenue directly against forecasting quantities multiplied by the last known price. The selected direct weekly absolute-error revenue model improved pooled development scores but regressed on the familiar main six-product November period.

| Dataset / method | Daily WAPE | Weekly WAPE | SKU 28-day WAPE |
| --- | ---: | ---: | ---: |
| Development 42, original | 112.10% | 79.03% | 60.91% |
| Development 42, direct revenue | **86.07%** | **48.94%** | **34.07%** |
| Familiar main six, original | **56.77%** | **38.77%** | **37.24%** |
| Familiar main six, direct revenue | 60.77% | 50.68% | 46.41% |

Not promoted. No independent final revenue-target confirmation was claimed. These are exploratory comparisons.

## 3. Prior-year features and fixed ensemble

Added prior-year demand aligned at a 364-day offset, prior-year 7/28-day means, and a recent-56-day to corresponding-prior-year growth ratio. Training examples are limited to the most recent 365 days, with older history available for features. Missing prior-year observations remain unknown, not fabricated zeros.

The selected candidate averages two complete, independent recursive trajectories with fixed 50/50 weights:

1. Annual-feature Poisson XGBoost.
2. Annual-feature, price-weighted absolute-error XGBoost.

The weights are not adjusted per product or after confirmation. Quantity predictions are nonnegative and revenue uses the latest observed unit price, not future actual prices.

| Dataset / method | Daily WAPE | Weekly WAPE | SKU 28-day WAPE |
| --- | ---: | ---: | ---: |
| Development 42, original | 112.10% | 79.03% | 60.91% |
| Development 42, annual robust blend | **83.08%** | **50.76%** | **34.65%** |
| Familiar main six, original | 56.77% | 38.77% | 37.24% |
| Familiar main six, annual robust blend | **55.03%** | **34.99%** | **28.59%** |
| Reserved annual cohort 24, original | 85.70% | 62.54% | 49.62% |
| Reserved annual cohort 24, previous-week | 82.20% | **54.16%** | **44.34%** |
| Reserved annual cohort 24, annual robust blend | **82.16%** | 64.33% | 56.98% |

The six-product improvement is real in that exploratory comparison, but **not evidence of a generally better deployable model**. On the reserved cohort, daily error improves by 3.54 points, while weekly error worsens by 1.80 points and SKU 28-day error worsens by 7.36 points. The previous-week baseline beats the challenger on aggregate horizons.

### Frozen final gate and audit

Before final scoring, `freeze` persisted the selected candidate, weights, cohort, forecast date, and hashes of the implementation, dependencies, prepared data, manifest, and development results. `confirm` verifies those hashes and creates an exclusive consumed marker **before** evaluating, preventing a retry from being labelled fresh.

The predeclared gate requires all of:

- Daily and weekly WAPE at least two percentage points below original.
- SKU 28-day WAPE no worse than original.
- Weekly WAPE below the previous-week baseline.
- The lower end of the paired SKU bootstrap 95% weekly improvement interval above zero.

Only the daily criterion passed. Weekly improvement interval: **-7.76 to +6.12 points**, crossing zero. This interval captures resampling variability across these products, not uncertainty across independent businesses or future seasons.

Reserved products, now consumed: `21928, 21929, 22138, 22112, 21915, 20712, 22139, 21166, 22384, 85066, 82486, 20724, 82583, 22659, 85152, 82494L, 22189, 22273, 21733, 20914, 22382, 20726, 21212, 22385`.

### Failure diagnosis

The candidate underpredicts total sales on **19/24 products** and improves absolute 28-day product error on only **6/24**. Predicted cohort revenue is 1,273,675.92 versus actual 2,298,129.20 in the demo denomination, a 44.58% shortfall. Original total shortfall is 23.83%.

The largest increases in absolute product-total error are 22138 (+46,652.30), 85066 (+41,311.63), and 22659 (+23,902.13). These are diagnostics after scoring, not grounds to exclude those products or retune the frozen weights and re-use the cohort as fresh evidence.

The observed trade-off is lower daily absolute error but excessive underprediction of product totals. It is consistent with smoothing large, irregular demand; it does not establish that price, promotions, stock-outs, or any particular customer behavior caused the error. Those explanatory inputs are absent.

## Implementation and verification

New isolated tooling:

- `backend/scripts/benchmark_weekly_direct.py`
- `backend/scripts/prepare_weekly_cohort.py`
- `backend/scripts/benchmark_weekly_revenue.py`
- `backend/scripts/prepare_annual_history.py`
- `backend/scripts/benchmark_annual_forecast.py`
- Dedicated weekly and annual unit tests; generated datasets/results are gitignored under their dated `outputs/` directories.

Annual evidence files: `development.json`, `known_main_six.json`, `manifest.json`, `confirmation_protocol.json`, `confirmation_started.json`, `confirmation.json`, and `confirmation_predictions.json` under `outputs/annual_forecast_2026-10-22/`. Preserve these together. Source/model results are not embedded into application code.

From `backend/`, development commands are:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_annual_forecast.py develop
.\.venv\Scripts\python.exe scripts\benchmark_annual_forecast.py known
```

`freeze` then `confirm` are single-consumption operations and have **already run** in this workspace. Do not delete their marker/protocol to manufacture another untouched test. The frozen protocol hashes the development results too, so regenerating them invalidates that protocol.

Regression command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_forecasting tests.test_quality tests.test_benchmark_bulk_orders tests.test_benchmark_weekly_direct tests.test_benchmark_annual_forecast
```

Tests cover existing forecast/quality behavior, temporal feature boundaries, history-only evaluation input, complete weekly targets, conservation of weekly totals, missing-vs-zero history, nonnegative fixed blends, promotion criteria, rejection of changed protocol inputs, and refusal to consume a confirmation cohort twice.

Result: **40 tests passed** on 22 October 2026. Tests used temporary artifacts and simulated records; no PostgreSQL connection or production retraining was required.

## Next defensible work

Keep the production model unchanged and stop treating November's repeatedly inspected examples as fresh validation. Before further model selection, reserve a sufficiently long future period or an independent representative business dataset and define the business objective (daily operations versus weekly product purchasing).

The highest-value additional signals for the demonstrated large-order problem are information available before forecasting: confirmed orders and delivery dates, planned promotions, price changes, and stock availability. More parameter search cannot guarantee reconstruction of unobserved future orders from past totals. None of these signals or guaranteed accuracy is claimed by this experiment.

The main app currently has approximately 240 days for the six demo products; the annual experiment's longer history is separate. Promoting annual features would also require a deliberate, audited history-import and model-eligibility path, not silently swapping in an artifact trained on unrelated products.
