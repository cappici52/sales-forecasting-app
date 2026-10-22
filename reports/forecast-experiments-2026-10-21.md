# Further model accuracy experiments — 21 October 2026

## Decision

Keep the deployed version-4 model/run 27. This round tested 22 additional configurations across direct forecasts, recency weighting, model complexity, price estimates, seasonal features, longer history, alternative estimators, and a fixed ensemble. No replacement demonstrated a dependable improvement on the app's UCI demo. This is a negative experimental result, not a claim that further improvement is impossible.

No sales, model runs, or artifacts in the app database were modified in this round. Existing uncommitted work from previous rounds remains intact.

## Comparable historical results

All results below use the same six SKU/day/channel series, held-price revenue target, and complete 28-day windows. Development origins are 10 August, 7 September, and 5 October 2011. The historical final origin is 2 November 2011. These periods have been inspected repeatedly and are exploratory, not independent confirmation.

| Candidate | Earlier-window revenue WAPE | November 28-day WAPE |
| --- | ---: | ---: |
| Current Poisson XGBoost | 100.65% | 56.77% |
| Direct Poisson, horizon feature | 104.15% | 62.43% |
| Direct log-target model | 75.94% | 79.35% |
| Direct normalized Poisson | 99.13% | 68.08% |
| Recency weights, 28-day half-life | 93.37% | 63.37% |
| Recency weights, 56-day half-life | 98.32% | 62.95% |
| Recency weights, 112-day half-life | 98.91% | 60.82% |
| Shallower trees | 99.39% | 59.09% |
| Deeper trees | 95.78% | 59.97% |
| Deeper trees, 56-day half-life | 93.49% | 64.10% |
| Shallower trees, 56-day half-life | 100.60% | 61.04% |
| Same-weekday mean/median features | 101.39% | 56.76% |
| Weekday + trend/zero/variation features | 107.03% | 57.13% |
| Seven-day median price | 93.22% | 61.64% |
| 28-day median price | 93.27% | 61.12% |
| 28-day volume-weighted price | 95.40% | 61.39% |
| Original model, history from December 2009 | 115.21% | 64.87% |
| Direct log model, history from December 2009 | 73.49% | 63.12% |
| Extra Trees | 99.14% | 57.11% |
| Random Forest | 112.27% | 59.01% |
| Histogram gradient boosting, Poisson | 104.66% | 60.25% |
| Tweedie XGBoost | 100.83% | 66.80% |
| Fixed 50/50 original + Extra Trees | 97.92% | 56.42% |

The 50/50 ensemble improved historical WAPE by only 0.35 percentage points. The same-weekday feature variant improved it by approximately 0.006 percentage points and did not improve development WAPE. Neither is a persuasive reason to replace production on its own.

## Additional week beyond the app data

The Extra Trees parameters and 50/50 weighting were fixed before inspecting the following result. The initial Extra Trees/original evaluation and the subsequent ensemble-inclusive evaluation were launched before reading the first result; there was no adjustment of weights after seeing this week. Fit data ended 30 November. Actuals from **1–7 December 2011**, not previously used in the app's benchmarks, were read from the second UCI Retail II sheet. This is an additional seven-day check, not a new 28-day test or a different business.

| Model | Revenue WAPE across 42 SKU/day rows |
| --- | ---: |
| Original Poisson | 64.21% |
| Extra Trees | 70.63% |
| Fixed 50/50 ensemble | 67.21% |

The fresh week does not support deploying the ensemble. These dates are now evaluated and must not be described as untouched in future tuning.

## Error concentration

The ten largest errors out of 168 November SKU/day observations account for **50.12% of total absolute error**. The largest is SKU 85123A on 3 November: 1,265 units sold, demo-normalized revenue about 161,145, versus a forecast near 9,190. This is an error diagnosis, not a reason to remove the observation. No spikes or difficult rows were excluded to improve the metric.

The available model inputs do not contain advance order commitments, campaign dates, stock availability, or customer purchasing plans. UCI describes the source as a gift retailer with many wholesale customers. Large orders are therefore a plausible source of unpredictable spikes, but this investigation does not establish the cause of each individual spike. Additional known-in-advance signals should be evaluated when available; retrospective actuals must not be fed into forecasts.

## Provenance and controls

- Source: [UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online%2Bretail%2Bii), CC BY 4.0; Daqing Chen, DOI 10.24432/C5CG6D.
- Historical extension adds only observations before 5 April 2011 for the same existing six UCI SKUs. The overlapping December 2010 portion is resolved by using the first sheet before 1 December 2010 and the second sheet thereafter. No extension was imported into the app.
- UK, positive quantity/price, non-cancelled transactions only, consistent with the original demo. Customer identifiers and descriptions are not read.
- Currency is multiplied by the existing demo factor 40 THB/GBP, not a real historical exchange rate. Missing transaction days in the complete source calendar are explicit zero sales; original missing observations in prepared application data remain unknown.
- Development code filters training at each origin. Forecasting uses only past quantities/prices. Future price is used only to calculate observed revenue during scoring.
- Additional history and more complex models did not produce a reliable gain here. The results do not establish a universal accuracy ceiling or business-readiness.

## Reproduction

From `C:\ProjectA\backend`, using the existing local PostgreSQL configuration and downloaded source archive:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_direct_forecast.py postgres
.\.venv\Scripts\python.exe scripts\benchmark_recency.py postgres
.\.venv\Scripts\python.exe scripts\benchmark_price_features.py postgres
.\.venv\Scripts\python.exe scripts\benchmark_estimators.py postgres
.\.venv\Scripts\python.exe scripts\benchmark_extended_history.py
.\.venv\Scripts\python.exe scripts\benchmark_fresh_week.py
```

The first five accept `--holdout` for the previously inspected November period. The first four also support the other locally downloaded public datasets. All scripts are research tools with fixed candidate configurations, not automatic production-model promotion commands.
