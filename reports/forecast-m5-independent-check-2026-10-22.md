# M5 product forecast check — 22 October 2026

## Decision

The direct weekly absolute-error model is a **promising experimental candidate**, but it did **not** pass the promotion gate frozen before the final 28-day check. It improved all three reported error resolutions against the application's existing Poisson XGBoost on this new retailer. Its advantage over the previous-week baseline is smaller and uncertain across the sampled products. The app model, PostgreSQL records, and existing artifacts were not changed.

This is a useful academic result: a documented new-source benchmark and a negative deployment decision under an explicit gate. It does not establish a universal accuracy percentage or claim performance on the project's older UCI demo.

## Source and task

The [M5 Forecasting Accuracy data description](https://www.kaggle.com/competitions/m5-forecasting-accuracy/data) identifies daily item/store unit sales, calendar dates, and weekly item/store selling prices. This check downloaded `calendar.csv`, `sales_train_evaluation.csv`, and `sell_prices.csv` from the [University of Nicosia's Zenodo M5 record](https://zenodo.org/records/10203108), DOI `10.5281/zenodo.10203108`. The downloaded MD5s match that record:

| File | MD5 |
| --- | --- |
| `calendar.csv` | `3ffeab2991b0c8e861d008b39ea4c95c` |
| `sales_train_evaluation.csv` | `b806dfc9f30a745102b708c09951f6aa` |
| `sell_prices.csv` | `08c591caa99e55daf3e0ccac913f7c85` |

Only product/store series with at least 180 selling days in the last 365 training days were eligible. The two highest-volume eligible products in each of three categories and ten stores were selected using **days 1549–1913 only**, yielding 60 product/store series. This is a high-activity sample, not a random or representative draw of all M5 items. The source's final 28 days, `d_1914`–`d_1941` (25 April–22 May 2016), were reserved from selection and model choice. M5's final hidden competition period is later; this project check uses the earlier **published** 28-day validation period, which had not previously been tested in this project.

The benchmark prepares daily history starting at `d_1400`. Source zero sales remain zero. Item/store/week prices are joined through the calendar; missing prices are carried forward only from earlier observed weeks. A product's future units and actual selling price are used to calculate its **observed** revenue; forecasts use the **last price known at the forecast origin**. The study evaluates revenue WAPE, not the M5 competition's hierarchical WRMSSE, so results should not be compared with the competition leaderboard.

## Procedure

- Three earlier 28-day rolling origins (31 January, 28 February, 27 March 2016) were used for model choice. Each fit stops at its own origin.
- Compared the existing Poisson XGBoost, repeated previous-week quantities, a four-week mean baseline, and a normalized direct weekly absolute-error XGBoost. Each produces 28 daily item/store quantities, valued at the last observed price.
- The direct model predicts four seven-day totals with horizon-specific training rows and distributes each total using weekday shares from the preceding 56 days. Its training labels end by the relevant origin; no final-period units or prices enter features, fitting, or selection.
- Selected the method with the lowest **weekly WAPE plus product 28-day WAPE** across all three earlier windows. The winner was `direct_absolute`.
- Before opening the final period, saved the selected method, cohort, source checksums, development-result hash, implementation hashes, dates, and acceptance gate in `outputs/m5_benchmark_2026-10-22/protocol.json`. Confirmation checks the hashes and writes a consumed marker before evaluation.
- The frozen gate required the candidate to beat **both** existing Poisson and previous-week baseline by at least **2 percentage points** on weekly and per-product 28-day revenue WAPE; daily WAPE could be at most 2 points worse than existing Poisson; and the paired product/store bootstrap 95% interval for weekly gain over the stronger baseline had to lie wholly above zero.

WAPE is absolute error divided by actual revenue, aggregated after the relevant time grouping. Lower is better; it is not “percentage of correct predictions.” Weekly WAPE groups into four fixed seven-day blocks per product/store. Product 28-day WAPE sums each product/store's four weeks before taking absolute error. Business-total error is not a promotion criterion because opposing item errors can cancel.

## Results

| Period and method | Daily revenue WAPE | Weekly revenue WAPE | Product/store 28-day revenue WAPE |
| --- | ---: | ---: | ---: |
| Development, existing Poisson | 29.89% | 18.00% | 14.64% |
| Development, previous week | 37.38% | 16.68% | 13.24% |
| Development, selected direct weekly | **28.66%** | **15.67%** | **12.99%** |
| Reserved final 28 days, existing Poisson | 31.44% | 19.02% | 16.11% |
| Reserved final 28 days, previous week | 35.67% | 17.27% | 15.41% |
| Reserved final 28 days, selected direct weekly | **29.22%** | **15.88%** | **13.55%** |

The final period contains 1,680 item/store-day observations. The candidate improves over existing Poisson by 2.22 points daily, 3.14 points weekly, and 2.56 points per product over 28 days. Against the stronger previous-week baseline it improves weekly by **1.39 points** and product 28-day by **1.87 points**, below the frozen 2-point threshold. A paired bootstrap resampling the 60 item/store series gives a 95% weekly-gain interval of **-1.01 to +4.13 points** relative to the previous-week baseline; it crosses zero. Those series share stores and one retailer, so the interval may understate dependence. Only the daily non-regression gate passed.

The candidate's 28-day **total** forecast revenue was 110,051.97 versus actual 111,059.11. This close overall total does not replace the product-level errors above: errors between products offset. The previous-week baseline has an even closer total but worse weekly/product errors, showing why the gate was defined around product planning rather than a single grand total.

## Interpretation and handoff

This independent retailer check supports saying that the direct weekly model **beat the existing model in this M5 sample**. It does not support saying that it meets the predetermined standard for replacing the app model, especially because the previous-week baseline remains competitive. The app uses a different public retailer sample with only about 240 days for six products; earlier direct-week experiments on another reserved UCI product cohort failed their gate. We therefore keep `direct_absolute` as a research candidate and preserve the application's current method.

For the final project, report both datasets and the different outcomes. The academic contribution is a reproducible comparison, temporal holdout, simple baseline, and honest deployment rule. No private business data is required to present those results, but the evaluation cannot claim fitness for a real company's purchasing decisions.

Implementation: `backend/scripts/benchmark_m5.py`, reusing `backend/scripts/benchmark_weekly_direct.py` and the app's `backend/app/forecasting.py`. Tests: `backend/tests/test_benchmark_m5.py`. Downloaded raw files are under gitignored `backend/data/uploads/m5_benchmark/`; results, source hashes, frozen protocol, and consumed marker are under gitignored `outputs/m5_benchmark_2026-10-22/`. Raw M5 data were not committed or imported into PostgreSQL.

From `C:\ProjectA\backend`, in a new workspace containing the three source CSVs, the one-time benchmark sequence is:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_m5.py develop
.\.venv\Scripts\python.exe scripts\benchmark_m5.py freeze
.\.venv\Scripts\python.exe scripts\benchmark_m5.py confirm
```

These phases **already ran** in this workspace. `confirm` refuses to relabel a repeated check as fresh. Source checksums and implementation hashes protect the frozen selection.
