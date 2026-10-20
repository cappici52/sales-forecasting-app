# Forecast method review (2026-10-21)

The existing Poisson XGBoost still has large revenue error, so it is not reliable enough for unreviewed business planning. Two datasets were inspected: the UCI-derived six-SKU daily sample already held in the local app database, and the independent Olist six-category proxy benchmark. Both are public examples, not the owner's current sales. The app's PostgreSQL `projecta1` sales and model runs were read only; no model was retrained there.

| Source | Current XGBoost rolling revenue WAPE | Current XGBoost final 28-day WAPE | Previous-week final WAPE |
| --- | ---: | ---: | ---: |
| UCI sample | 100.65% | 56.77% | 72.84% |
| Olist category proxy | 40.48% | 56.08% | 63.13% |

Lower WAPE is better. A stable 28-day sales-weighted price improved Olist's final revenue WAPE to 43.55%, but worsened the UCI sample to 61.39%. A 25% price blend, a volatility rule, and choosing price treatment from earlier windows also failed to improve both sources consistently. A 75% XGBoost / 25% four-week weekday unit blend yielded only a marginal UCI final improvement and worsened Olist revenue. These candidate comparisons are exploratory: their final periods were inspected during development and must **not** be presented as untouched confirmation of a selected new model. None was made the universal production default.

The shipped reliability change is a per-horizon guard. New training performs the existing three rolling-origin backtests for 7, 14, and 28 days, compares revenue WAPE of XGBoost and a repeated-previous-week forecast, and stores the lower-error method for each horizon. Forecast, SKU/channel insight totals, and saved 28-day snapshots use the same stored choice. The UI names the actual method. Legacy model-only artifacts continue to use XGBoost until retrained. This selection improves *measured historical* error whenever XGBoost loses to that baseline; it does not prove lower future error. On both public samples above, XGBoost already beats the weekly baseline in the reported final periods, so no immediate numerical improvement is claimed for their existing forecasts.

Next accuracy step: collect recent, representative sales from the actual business (with complete daily zero-sale rows and realistic prices), reserve a new final time period that is not used for model selection, and rerun the rolling-origin and final-period comparison. The existing 2011 sample is stale and should not be used to claim current-business accuracy. Rolling-origin evaluation follows the [time-series cross-validation method](https://otexts.com/fpptr/tscv.html); retail demand is known to vary across products and aggregation levels, as described in the [M5 accuracy competition paper](https://doi.org/10.1016/j.ijforecast.2021.11.013).
