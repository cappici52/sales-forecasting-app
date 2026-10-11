# ProjectA_1 UX Contract

## Product context

- Audience: Thai business owners working with store and SKU sales data.
- Primary jobs: sign in, import and validate sales, train a model, inspect a forecast, export data.
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
| Upload validation | Import action unavailable | Row count and date range | Error banner, file retained |
| Import | Confirm disabled | Overview refresh | Error banner, retry file |
| Train | Train button disabled | Metrics and forecast available | Error banner, retry training |
| Export | Browser download | CSV saved | Error banner |
| Logout | Immediate request | Login screen | Local session cleared |

## Permissions and resilience

All data APIs require a session. Import and training require owner or manager on the server. New registration creates an owner. Session expires after seven days and logout revokes it. A 401 returns the user to login; a 403 is displayed as an action error. Writes wait for the server response, and the current dataset is replaced only after server validation. Requests for forecast are cancelled when filters change. Dataset and model artifacts are scoped by organization ID.

## Navigation and display

The selected section is visible in the sidebar on desktop and in the fixed bottom bar on mobile. Language and theme switches preserve preference in local storage when available. Status messages use `role=status` or `role=alert`. The forecast table is the text alternative to the chart.
