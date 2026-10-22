# M5 volume robustness check — 22 October 2026

## Decision

**Do not replace the application's forecasting model with `direct_absolute`.** On 90 additional M5 product/store series, the fixed challenger was worse than the existing Poisson XGBoost overall on weekly and product-level 28-day revenue WAPE. Its weekly gain was not stable across product-volume groups. The predeclared acceptance gate failed; the app model and PostgreSQL data were not changed.

This is a robustness check of the earlier M5 result, **not a new independent time holdout**. The 90 products were unused in the prior high-volume cohort, but the same retailer and the same final dates had already been examined.

## Protocol

The source is the [University of Nicosia M5 record](https://zenodo.org/records/10203108). The three source-file checksums were verified against the prior M5 protocol. Selection used only sales through `d_1913` and excluded the prior 60 high-volume product/store pairs. Within each of 10 stores × 3 categories, eligible items were sorted by units sold in the last 365 training days, split into three equal-sized relative-volume groups, and the middle item in each group was selected. This yields **30 low-, 30 medium-, and 30 high-volume** product/store series. Eligibility required pre-`d_1549` sales, at least 28 selling days in `d_1549`–`d_1913`, and at least one sale in the final 28 training days. These groups are relative to their own store/category and one central item per group; they are not a random or statistically representative sample of all M5 items.

The candidate, existing Poisson XGBoost, and repeated-previous-week baseline were fixed before scoring `d_1914`–`d_1941` (25 April–22 May 2016). We reused the earlier M5 gate: the challenger must improve weekly and product/store 28-day WAPE by at least 2 percentage points against **both** comparators, not materially regress daily WAPE, and have a paired 95% bootstrap interval for weekly gain entirely above zero. An additional check disallowed weekly regression greater than 2 points in any volume group relative to its stronger comparator. No formula or cohort was changed after viewing scores.

WAPE is summed absolute revenue error divided by summed actual revenue; lower is better. Weekly WAPE uses four fixed seven-day blocks per product/store. Product/store 28-day WAPE aggregates each item's four weeks before computing error. The overall business-total error is not a promotion metric because positive and negative item errors cancel.

## Results

| Cohort / method | Daily WAPE | Weekly WAPE | Product/store 28-day WAPE |
| --- | ---: | ---: | ---: |
| All 90 — existing Poisson | **93.42%** | **45.52%** | **31.00%** |
| All 90 — previous week | 111.24% | 49.01% | 36.95% |
| All 90 — fixed direct weekly | 94.16% | 46.05% | 32.96% |
| Low 30 — existing Poisson | 141.76% | **61.36%** | **39.74%** |
| Low 30 — previous week | 139.64% | 71.93% | 55.20% |
| Low 30 — fixed direct weekly | **132.48%** | 63.17% | 44.10% |
| Medium 30 — existing Poisson | 115.78% | **56.26%** | **38.40%** |
| Medium 30 — previous week | 126.37% | 62.93% | 47.24% |
| Medium 30 — fixed direct weekly | **115.54%** | 58.28% | 41.72% |
| High 30 — existing Poisson | **73.37%** | 37.84% | **26.28%** |
| High 30 — previous week | 98.81% | 38.42% | 28.78% |
| High 30 — fixed direct weekly | 77.07% | **37.54%** | 27.17% |

The challenger regressed overall by **0.53 points weekly** and **1.96 points per product over 28 days** against the existing model. Its weekly regression was **1.81 points** in low volume and **2.02 points** in medium volume. In high volume it gained just **0.30 points weekly**, while product-level 28-day WAPE still worsened by **0.89 points**. Compared with the existing model, the paired product/store bootstrap 95% interval for weekly gain was **−5.59 to +3.34 percentage points**; it includes zero. The only overall gate check that passed was daily non-regression. The medium-volume regression also failed the additional group check.

These errors are materially larger than in the prior high-volume cohort. Sparse, intermittent products are harder to predict and can generate zero-actual series in a 28-day window; WAPE is particularly unstable on small denominators. Accordingly, do not generalize the prior cohort's approximately 16% weekly error to all items. Nor does this check show that the existing model is accurate enough for real inventory decisions. For this final project without private business data, the defensible result is a documented comparison and a negative promotion decision.

## Technical note and reproducibility

The first confirmation attempt scored the fixed models but stopped before writing `result.json`: the inherited bootstrap helper could not handle a product with zero actual revenue over all 28 days. Only the new robustness benchmark's uncertainty calculation was repaired to keep zero-actual products in pooled resampling. The original cohort, candidate, baselines, period, scoring, and gate remained unchanged. The run then resumed under the consumed marker; `result.json` records both the original and repaired script hashes. The interval should be read with the usual caveat that items share stores and one retailer, so independent item-level resampling can understate dependence.

Implementation and tests: `backend/scripts/benchmark_m5_robustness.py` and `backend/tests/test_benchmark_m5_robustness.py`. Source files remain in gitignored `backend/data/uploads/m5_benchmark/`; the protocol, consumed marker, and result are in gitignored `outputs/m5_robustness_2026-10-22/`. Neither downloaded data nor forecast rows were imported into PostgreSQL.

For a clean workspace with the three verified M5 CSVs and the earlier M5 protocol already produced, run from `C:\ProjectA\backend`:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_m5_robustness.py prepare
.\.venv\Scripts\python.exe scripts\benchmark_m5_robustness.py confirm
```

Those one-time phases have already been consumed in this workspace. Do not rerun them here or describe another check on the same dates as an unseen holdout.
