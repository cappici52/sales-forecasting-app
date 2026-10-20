# Independent Olist benchmark (2026-10-20)

The current Poisson XGBoost model was evaluated **without changing its settings** on a new source: [Olist's public Brazilian e-commerce dataset](https://www.kaggle.com/olistbr/brazilian-ecommerce/home/). The input CSVs came from [Olist's own GitHub repository](https://github.com/olist/work-at-olist-data/tree/master/datasets). No Olist rows were imported into the app database, and no customer or seller identifiers were retained in the benchmark frame.

## Protocol

- Use delivered orders only, positive item prices, and purchase date as the sales date. Aggregate item lines into daily counts and average item price for each product category. Individual product IDs are too sparse for this benchmark; categories act as SKU proxies, so these results **do not** establish SKU-level accuracy.
- Select the six busiest categories using dates through 2018-06-30 only. Represent days with no orders explicitly as zero, carrying forward the last observed category price. Use one synthetic store (`olist`) and one channel (`ecommerce`). Price values remain in Brazilian reais, not Thai baht.
- Use data from 2017-03-01 onward. Evaluate three non-overlapping rolling origins within the training period, then reserve 2018-07-01 through 2018-07-28 as a separate, untouched 28-day holdout. At each origin, fit only on rows available through that origin and recursively forecast all 28 days without feeding future actuals back into the model.
- Compare the existing Poisson XGBoost against (a) repeating the last week, (b) the mean of the same weekday over four weeks, and (c) the mean of the last 28 days. WAPE is sum of absolute error divided by sum of actuals; lower is better. Revenue predictions multiply forecast quantity by the last observed category average price. Every score covers six categories; 504 category-days for rolling validation and 168 for the holdout.

| Method | Rolling unit WAPE | Holdout unit WAPE | Rolling revenue WAPE | Holdout revenue WAPE |
| --- | ---: | ---: | ---: | ---: |
| Poisson XGBoost | 34.31% | **36.89%** | **40.48%** | **56.08%** |
| Last week repeated | 41.49% | 46.19% | 47.84% | 63.13% |
| Four-week weekday mean | **34.27%** | 39.85% | 41.53% | 60.76% |
| Last 28-day mean | 35.91% | 40.73% | 42.38% | 61.51% |

On the held-out month the model beats the best simple baseline by 2.96 percentage points for units and 4.68 points for revenue. On rolling unit validation, the four-week weekday mean is marginally better (0.04 points). Revenue error remains high even for the winning method, likely including price-mix changes that a last-observed-price forecast cannot capture. This is evidence that the model has some value for category-level trend estimation, **not** proof of reliable revenue forecasts or production readiness. Results are from one retailer and one final holdout; they should be repeated on independent businesses and at actual SKU/store grain before broader claims.

## Reproduce

Download `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`, and `olist_products_dataset.csv` from the [source folder](https://github.com/olist/work-at-olist-data/tree/master/datasets) into `backend/data/uploads/olist_benchmark/` (gitignored), then from `C:\ProjectA` run:

```powershell
.\backend\.venv\Scripts\python.exe backend\scripts\benchmark_olist.py
```

SHA-256 of the tested files, in the order above:

```text
olist_orders_dataset.csv       8DF58EF3D2D7E9944010F7BEECD9B75367F5588EC6E3C91CEC19AE3345EF9ECF
olist_order_items_dataset.csv  4F6ABDBBC94036D0DF4A76FA0520C072E31A40119D70F7F370FBA1E2285D2BCB
olist_products_dataset.csv     3E6569628A17FBC75FD206EE357B59E20364B9AFA90F5B6CD5B4D624C58AA9CC
```
