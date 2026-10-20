# ProjectA_1 UX Contract

## Product context

- Audience: Thai business owners working with store and SKU sales data.
- Primary jobs: sign in, import and validate sales, train a model, inspect a forecast, export data.
- Planning jobs: inspect saved forecast versus later actuals and explore clearly labeled arithmetic what-if assumptions.
- Insight job: compare recent SKU/channel sales, see eligible 28-day per-series forecast totals, and inspect descriptive weekday averages without presenting CRM, attribution, or inventory data as if it existed.
- Active locales: Thai and English. Timezone is not inferred from the browser for stored sales dates.
- Accessibility target: keyboard-accessible controls and WCAG 2.2 AA contrast intent.

## Source and visual contract

- Source of product requirements: user conversation and `README.md`.
- API/domain behavior: `backend/app/main.py`, `backend/app/models.py`, `backend/app/services.py`.
- Visual context: `DESIGN.md`; runtime tokens: `app/globals.css`.

## Canonical UI map

| Capability | Owner | Variant | Verification |
| --- | --- | --- | --- |
| Form | `app/ClientApp.tsx` auth form | Login / register | Browser auth flow |
| Select | Native HTML select in forecast filters | Platform popup accepted | Keyboard and browser QA |
| Scrollbar | `app/globals.css` | Global tokenized baseline | Browser QA |
| Feedback | Shared banner styles and `notice`/`error` state | Success / error | Browser upload/training flow |
| Upload | Import section in `app/ClientApp.tsx` | CSV/XLSX, one file | Validate/import flow |

## Workflow

| Operation | Pending | Success | Failure recovery |
| --- | --- | --- | --- |
| Register/login | Submit disabled | Dashboard with session | Inline error, fields retained |
| Upload validation | Import action unavailable | Row count, date range, and missing-calendar-day warning | Error banner, file retained |
| Import | Confirm disabled | Overview refresh | Error banner, retry file |
| Train | Train button disabled | Metrics and forecast available | Error banner, retry training |
| Review saved forecast | Report loading within forecast page | Week/month matched-pair report, coverage visible | Inline error with retry; prior values cleared |
| What-if | Local slider adjustment | Recomputed arithmetic revenue, original forecast unchanged | Reset assumptions; unavailable until forecast exists |
| Product/channel insights | Forecast-page filters trigger a cancellable read-only request | Actual 28-day SKU/channel totals, eligible forecast totals, weekday evidence, and rule-based checks appear with their date context | Inline retry on server error; empty/no-match and incomplete-calendar explanations |
| Export | Browser download | CSV saved | Error banner |
| Logout | Immediate request | Login screen | Local session cleared |

## Permissions and resilience

All data APIs require a session. Import and training require owner or manager on the server. New registration creates an owner. Session expires after seven days and logout revokes it. A 401 returns the user to login; a 403 is displayed as an action error. Writes wait for the server response, and the current dataset is replaced only after server validation. Requests for forecast are cancelled when filters change. Dataset and model artifacts are scoped by organization ID.

## Navigation and display

The selected section is visible in the sidebar on desktop and in the fixed bottom bar on mobile. Language and theme switches preserve preference in local storage when available. Status messages use `role=status` or `role=alert`. The forecast table is the text alternative to the chart.

Section entrances and success emphasis are visual-only; they do not delay controls or announce false data changes. The pixel-art cat identifies the product on auth, navigation, and favicon surfaces. With `prefers-reduced-motion: reduce`, entrance, pop, and pulse animations are disabled.

If the latest model run is recorded but its artifact is unavailable, display a distinct “model file unavailable” state and direct the user to retrain. Historical sales may still be charted, but must be labeled as actual data only; no forecast total, model badge, or forecast table is shown until forecast items exist.

The model page displays rolling 7/14/28-day WAPE beside the previous-week baseline, plus 28-day MAE/RMSE and the highest-error evaluated stores/SKUs. Older runs without rolling results prompt retraining. A forecast with incomplete recent series states how many store/SKU/channel series were included. Imported data with missing calendar dates warns that absent days are not zero sales. If legacy records lack `unit_price`, suppress monetary totals and forecasts and direct the owner to re-import complete data.

A completed model remains technically available even if review checks fail. New training compares XGBoost with the previous-week baseline on rolling backtests and saves the lower-WAPE method separately for 7/14/28 days; the forecast badge and model table identify the served method. Existing model-only artifacts continue to serve XGBoost until retrained. Overview, forecast, and model pages show a persistent review notice when 28-day rolling revenue WAPE is at least 30%, does not beat the previous-week baseline, has fewer than three evaluation folds, sales data is over 30 days old (Asia/Bangkok calendar), or fewer than all series have 28 observed recent dates. The notice shows the WAPE comparison, full-dataset series coverage, data age, and exact reasons in Thai/English. Passing these starter checks is not described as guaranteed accuracy or business readiness. The review thresholds are initial capstone heuristics, not industry standards.

The forecast page's product/channel section follows the same store/SKU/category/channel filters. It compares actual units from the last 28 observed calendar dates with the preceding 28 dates only when every included store/SKU/channel series has all 56 daily records; missing days are never filled with zero. Forecasted units and revenue are shown separately and only for eligible series in the active trained model. It lists at most eight SKUs, exposes series coverage, and labels sales channels as distinct from lead sources. Weekday revenue averages require eight complete weeks and prices; they describe sales timing, not customer purchase-decision time. Suggestions are deterministic checks, with no inferred stock levels, discount elasticity, deal probabilities, or causal effects. A stale or review-flagged model cannot generate a stock-planning prompt.

Training also saves an immutable 28-day per-series forecast snapshot. Re-importing sales marks the model run superseded and removes its model file, but keeps the run ID and snapshot so the comparison report remains available. Week starts Monday (ISO); month starts on day 1. A difference is shown only for forecast rows with matching actual date/store/SKU/channel and a price; partial coverage is explicit. What-if sliders only multiply the current forecast by price and volume factors; their values are not stored or claimed as causal ML predictions.
