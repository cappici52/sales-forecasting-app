# Transaction spikes and split-demand experiment

## Decision

Do not replace the production forecaster. Separating regular and large-order demand improved earlier development windows, but failed the frozen check on a previously unused 12-SKU cohort. The main PostgreSQL database, sales records, model runs, and model artifacts were not changed in this experiment.

This is public historical retail data, not current sales from the owner's business. The new cohort is from the **same retailer and familiar dates**, not a new future period or independent business. After this run it must not be described as untouched confirmation again.

## What caused the spikes?

The source is [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii), `Year 2010-2011`, supplied by Daqing Chen (DOI 10.24432/C5CG6D, CC BY 4.0). Only UK, positive-quantity, positive-price, non-cancelled invoice lines with normal SKU codes are included. Returns and cancellations are outside this gross-sales target. Customer identifiers and descriptions were not read.

Invoice lines were summed by invoice, SKU, and date before classifying an order. No identical lines or large orders were discarded. This identifies unusually large orders, **not proven wholesale customers or data errors**.

Examples among the largest original-model errors in 3–30 November 2011:

| SKU / date | Total units | Invoices for that SKU | Largest invoice units | Largest invoice share |
| --- | ---: | ---: | ---: | ---: |
| 85123A / 3 Nov | 1,265 | 7 | 992 | 78.4% |
| 85099B / 10 Nov | 1,064 | 11 | 1,000 | 94.0% |
| 85099B / 9 Nov | 725 | 15 | 200 | 27.6% |
| 85123A / 14 Nov | 374 | 8 | 320 | 85.6% |
| 85099B / 14 Nov | 640 | 5 | 400 | 62.5% |

For 85123A on 3 November, the two largest invoices contained 992 and 224 units: together 96.1% of the day's units. Not every spike has that pattern, as the 9 November example shows.

Across the existing six SKUs' final 28 days, 37 of 990 invoice-SKU-day groups exceeded their training-only size threshold. They represented 45.1% of units and 41.2% of revenue. The ten worst SKU-day prediction errors accounted for 50.1% of total absolute revenue error.

## Frozen experiment design

- Development products: 85099B, 85123A, 20725, 20727, 20728, 22423.
- Daily training begins 5 April 2011. Development forecast origins: 10 August, 7 September, and 5 October, each predicting the next 28 days. Final origin: 2 November, predicting 3–30 November.
- An invoice-SKU quantity strictly above that SKU's 95th percentile in training history is classified as bulk. The full order goes into bulk, not just its excess above the threshold. Regular plus bulk quantities reconstruct the original daily total exactly.
- Thresholds are re-estimated using only history available at each origin. No future transactions influence thresholds, features, or prices. Missing transaction-calendar days are explicitly represented as zero sales, as in the existing public-data importer; no availability/stock-out information is present.
- Regular demand uses the existing Poisson XGBoost settings and lag features. Two bulk candidates were fixed: another Poisson XGBoost, or a 56-day weekday occurrence-rate × conditional-size expectation, shrunk halfway to the overall daily expectation. Zero-bulk days are included. Neither candidate knows future orders.
- Both components are added and multiplied by the **last observed total unit price**, preserving the current price assumption. Scores include **all** ordinary and bulk sales and zero-sale days. Unit prices are rounded to six decimals, matching the application's importer; the fixed GBP × 40 multiplier is a demo denomination, not historical THB exchange rates.
- The challenger with lowest pooled daily revenue WAPE over development folds is frozen before new-cohort scoring. This selected `split_rate`.
- Promotion requires at least a 2-percentage-point daily WAPE improvement in both development and confirmation, no weekly or per-SKU 28-day regression in either, and improvement in at least two of three development folds. This is an experimental gate, not a claim of business-acceptable absolute error.

Before confirmation, benchmark parity checks identified differences in training row ordering and price precision. These were aligned with the app importer/preparer and the development experiment rerun. Candidate definitions, threshold, cohort, and acceptance gate were unchanged; no new-cohort score was inspected during these corrections. The corrected original baseline reproduces the prior 56.77% daily WAPE.

The 12 confirmation SKUs were chosen using only revenue and activity through 2 November, excluding every SKU used in the existing six-product 2011 and six-product 2010 experiments. Requirements: known by 5 April, at least 100 active days from 5 April, and a sale in the last seven training days. Revenue ranking with SKU tie-break selected:

`84879, 22386, 22197, 79321, 22178, 85099F, 21931, 22720, 82484, 22411, 22699, 48187`.

The cohort's models are refitted to its own pre-cutoff history. The evaluation tests the frozen modeling **procedure**, not zero-shot prediction for unseen product IDs.

## Results

Revenue WAPE, lower is better. Daily WAPE evaluates all 28 separate predictions; weekly WAPE first sums those same predictions into four fixed seven-day blocks per SKU. SKU 28-day WAPE sums by SKU before taking absolute errors. Neither is the same as business-total error, where opposite SKU errors can cancel. WAPE is not an accuracy percentage and can exceed 100%.

| Dataset / method | Daily WAPE | Weekly WAPE | SKU 28-day WAPE | Business-total 28-day error |
| --- | ---: | ---: | ---: | ---: |
| Development, original XGBoost | 100.65% | 76.34% | 64.24% | 47.32% |
| Development, split + bulk rate | **85.54%** | **55.07%** | **41.01%** | **29.89%** |
| Development, split + bulk XGBoost | 90.76% | 66.04% | 51.18% | 33.41% |
| Familiar November, original XGBoost | **56.77%** | 38.77% | 37.24% | 36.37% |
| Familiar November, split + bulk rate | 58.19% | **35.04%** | **26.73%** | **23.66%** |
| New SKU cohort, original XGBoost | **80.92%** | 57.86% | 53.36% | 28.98% |
| New SKU cohort, previous-week baseline | 95.96% | **44.62%** | **38.38%** | 26.19% |
| New SKU cohort, split + bulk rate | 85.33% | 61.95% | 59.58% | **18.38%** |

Development contains 504 SKU-days, the familiar final period 168, and the new cohort 336. The selected challenger improved daily error in all three development folds. Nevertheless, new-cohort daily WAPE worsened by **4.41 percentage points**, weekly by 4.09 points, and SKU 28-day by 6.23 points. The promotion gate therefore failed. A better business total alone would conceal worse product-level errors.

## What this changes about the next step

1. Large orders are a real source of error in this sample, but a simple bulk-rate forecast does not solve their timing. Do not delete these orders or deploy this split procedure based on development scores.
2. If the business needs purchasing plans, explicitly choose weekly or 28-day **per-product** quantities as the primary objective. A separately trained aggregate-horizon model is a future candidate; the table above only aggregates daily predictions and does not test that model. Previous-week already beats both tested models on the new cohort's aggregate metrics, so it must remain a comparator.
3. For predicting large orders on specific dates, collect information available **before** the forecast: confirmed order book/pre-orders and expected shipment dates, planned promotions, and stock availability. A scenario for possible large orders should be clearly distinguished from a known order or an accurate daily point forecast.
4. Freeze any next candidate on development data and reserve a genuinely new period or representative business dataset for a final check. This cohort has now been consumed; repeatedly tuning to it would not constitute fresh evidence.

## Reproduction and checks

Experiment implementation: `backend/scripts/benchmark_bulk_orders.py`. Public source archive: `backend/data/uploads/uci_online_retail_ii.zip`. Intermediate orders and generated JSON are gitignored under `outputs/bulk_orders_2026-10-22/`; no raw invoice export is added to Git.

Run `prepare` once with the bundled Python/pandas runtime to read the workbook and freeze cohort/protocol. From `backend/`, run:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_bulk_orders.py develop
.\.venv\Scripts\python.exe scripts\benchmark_bulk_orders.py confirm
```

`confirm` checks the implementation hash against the frozen selection and refuses to overwrite an existing confirmation. The protocol records source SHA-256 `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb`.

Six dedicated tests cover invoice aggregation, future-independent thresholds and cohort selection, exact split reconstruction, strict threshold boundaries, inclusion of zero-demand days, and aggregation without merging different SKUs. No PostgreSQL connection is required by the experiment.

Verification: `python -m unittest tests.test_forecasting tests.test_quality tests.test_benchmark_bulk_orders -v` passed all **24 tests**, including the six new experiment tests and existing forecast/quality regressions.
