# Forecast error diagnosis (2026-10-21)

This is a read-only study of **public, historical** datasets, not the owner's current sales. The Olist series are category proxies priced in BRL; the UCI series are six products from 2011 with a constant demo GBP-to-THB multiplier. The existing PostgreSQL `projecta1` database was queried only; no records, model runs, or artifacts were changed.

| 28-day held-out source | Unit WAPE | Revenue WAPE with last observed price | Revenue WAPE if actual future price were known | Revenue WAPE if actual future units were known |
| --- | ---: | ---: | ---: | ---: |
| Olist, six categories | 36.89% | 56.08% | 37.17% | 43.02% |
| UCI-derived, six SKUs | 61.52% | 56.77% | 61.08% | 32.30% |

The last two columns are **diagnostics with future information**, not deployable forecasts. They are not additive error components. Olist's revenue error is strongly affected by the held-price assumption for aggregated categories; UCI's unit forecast remains the larger issue. A universal price adjustment is therefore not supported by these samples.

An experimental per-series method selector chose the lowest earlier rolling revenue WAPE among XGBoost, previous-week, four-week weekday mean, and 28-day mean. It used three 28-day validation windows before each final period:

| Source | XGBoost final revenue WAPE | Per-series selection final revenue WAPE | Decision |
| --- | ---: | ---: | --- |
| Olist | 56.08% | 54.16% | Small exploratory gain |
| UCI-derived | 56.77% | 63.59% | Regression; reject production change |

These final periods had already been inspected in earlier development. This is exploratory evidence, **not a fresh untouched confirmation**. The production forecasting method remains unchanged. Future work should use a new representative source or future real sales, choose candidate methods on earlier rolling windows, and judge the frozen choice on a genuinely new final period. Both datasets here are stale and cannot establish accuracy for the owner's business.

## Fresh period check: UCI Online Retail II (2009–2010)

After the above method comparison, we fixed the four benchmark methods, selection rule, and 28-day horizon **before inspecting** the November 2010 holdout. The [UCI Online Retail II archive](https://archive.ics.uci.edu/dataset/502/online+retail+ii) is a separate earlier year of the same retailer as the UCI-derived 2011 data, so this is a new period but not an independent business. Only United Kingdom, positive-price/quantity, non-cancelled invoice rows with normal SKU codes were used. Six active SKUs were selected by revenue through 31 October 2010; no November rows influenced selection or training. Zero-sale days were explicitly represented. Currency is GBP; no THB conversion was applied.

| Fixed method | Earlier rolling validation revenue WAPE | New 1–28 Nov revenue WAPE | New unit WAPE |
| --- | ---: | ---: | ---: |
| Current Poisson XGBoost | **87.90%** | 70.65% | 68.19% |
| Previous week | 138.23% | 79.22% | 77.28% |
| Four-week weekday mean | 96.94% | **68.48%** | **63.85%** |
| 28-day mean | 99.67% | 75.13% | 74.21% |

The XGBoost method was preferred on earlier validation; the 2.17 percentage-point holdout advantage of the weekday mean is **post-hoc** and too small to justify switching production methods. For XGBoost, replacing its future quantities with *actual future units* would reduce revenue WAPE to 8.16%; replacing only its held price with *actual future prices* would instead produce 75.08%. These are oracle diagnostics, not deployable forecasts. Unit prediction is the dominant problem for these six SKUs. The large errors across all methods and the very different source behaviour mean that the model is **not yet validated for business planning**. We did not tune to this final period or change the deployed forecaster. Next evidence should come from actual business data with known stock-outs/promotions and later chronological holdouts, or at minimum another unrelated retailer.

## New retailer check: Rossmann store sales

We froze the same four methods and 28-day design before evaluating the final 28 days of the [Rossmann Store Sales dataset](https://www.kaggle.com/competitions/rossmann-store-sales/data), obtained from a [public GitHub mirror](https://github.com/Muosvr/rossmann-store-sales/blob/master/data/train.csv). Six stores were selected for complete training history and highest training revenue; future revenue did not influence selection. This is a different German retailer, but its public file has only **store-day sales**, not item units or prices. For compatibility with the existing forecaster, sales were treated as a numeric target with a constant price of 1. Therefore this tests transfer to *aggregate revenue*, **not the application's product-level quantity-and-price task**. The final period includes 12 closed-store days and 60 promotion-store days among the six stores; the forecaster was not supplied future closure or promotion information.

| Frozen method | Earlier validation revenue WAPE | 4–31 Jul 2015 holdout revenue WAPE |
| --- | ---: | ---: |
| Current Poisson XGBoost | **14.62%** | **7.98%** |
| Previous week | 20.90% | 15.25% |
| Four-week weekday mean | 15.35% | 9.29% |
| 28-day mean | 26.99% | 22.12% |

The current model beats these baselines on this **easier aggregate** task. Alongside the 56–71% errors on item/category tests, this is evidence that accuracy depends heavily on the forecasting grain and dataset; it is **not** evidence of 7.98% accuracy for the owner's products. No production model change was justified. The raw mirrored CSV stays in a gitignored uploads folder and was not imported into PostgreSQL.

## Price-weighted quantity challenger

The application's 28-day output is revenue, but its XGBoost model is fitted to quantity. We therefore tested one conservative challenger: the *same* Poisson XGBoost and features, with training-row weight proportional to that row's unit price. The mean-normalized weights alter the objective without changing the forecast's units, recursion, price assumption, or API shape. Baselines and final periods are identical to the earlier tests.

| Source | Original rolling validation WAPE | Weighted validation WAPE | Original final WAPE | Weighted final WAPE |
| --- | ---: | ---: | ---: | ---: |
| Olist categories | 40.48% | **40.23%** | 56.08% | **53.79%** |
| UCI Retail II 2010 SKUs | 87.90% | **84.92%** | 70.65% | **67.96%** |
| UCI-derived 2011 SKUs in local PostgreSQL | **100.65%** | 103.34% | **56.77%** | 59.33% |
| Rossmann aggregate stores | 14.62% | 14.62% | 7.98% | 7.98% |

Because the challenger regresses on one SKU source, the app now trains both the original and price-weighted quantity models and chooses by *rolling validation revenue WAPE* independently for 7, 14, and 28 days, retaining the previous-week baseline as a fallback. A disposable, read-only training run against the local PostgreSQL data chose the **original** model for all three horizons; it did not write model runs or sales records to the database. New training creates a version-3 artifact containing both candidates. Version-1/2 artifacts remain loadable; an existing app model will not gain the new selection until retrained. These public final periods have now been inspected repeatedly, so their gains are exploratory, not proof of future business accuracy.

We also tried a previous-day-price feature and a direct-revenue target. The former worsened Olist materially. Direct revenue helped Olist but worsened the final 2011 SKU period and would require changing the meaning of item-unit forecasts. Neither was deployed. A new chronological holdout on the owner's own sales remains the decisive test.

Reproduce the read-only checks from `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_olist.py
.\.venv\Scripts\python.exe scripts\benchmark_series_selection.py olist
.\.venv\Scripts\python.exe scripts\benchmark_models.py
.\.venv\Scripts\python.exe scripts\benchmark_series_selection.py postgres
.\.venv\Scripts\python.exe scripts\benchmark_retail_ii.py
.\.venv\Scripts\python.exe scripts\benchmark_rossmann.py
.\.venv\Scripts\python.exe scripts\benchmark_revenue_blend.py olist
.\.venv\Scripts\python.exe scripts\benchmark_revenue_blend.py retail_ii
.\.venv\Scripts\python.exe scripts\benchmark_revenue_blend.py rossmann
.\.venv\Scripts\python.exe scripts\benchmark_revenue_blend.py postgres
```

The PostgreSQL commands require the configured local database. Olist uses only the three local source CSVs in `backend/data/uploads/olist_benchmark/`. The Retail II benchmark requires the UCI ZIP archive at `backend/data/uploads/uci_online_retail_ii.zip`; the Rossmann benchmark requires `backend/data/uploads/rossmann_train.csv`. Raw source files are gitignored.
