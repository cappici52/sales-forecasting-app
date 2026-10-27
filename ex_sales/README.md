# UCI Online Retail demo data

These two CSV files are a historical teaching example for ProjectA_1. They are **not current sales for a Thai business**. The source is Daqing Chen's [Online Retail dataset at the UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/352/online%2Bretail), DOI [10.24432/C5BW33](https://doi.org/10.24432/C5BW33), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The source ZIP used for this export has SHA-256 `F5385CBB54BBEBF7196389109C6B0621FAAB0C304E3702548165E71C84AEDE8B`.

| File | Dates | Rows | Use |
| --- | --- | ---: | --- |
| `uci-online-retail-demo-train.csv` | 5 April–2 November 2011 | 1,272 | Import, then train and save a 28-day forecast. |
| `uci-online-retail-demo-full.csv` | 5 April–30 November 2011 | 1,440 | Import **after** forecasting to compare the saved forecast with the 28-day actuals. This replaces the organization's sales history and supersedes its current model. |

SHA-256 checksums: training CSV `D1A74480219BACF56FA48CD0E3B47D56D6E198264BBBE283A24A8DDE8F3FECED`; full CSV `9EA6BC4BA05F6DAF3DCED550CF9A0363D837505929F5BBDBAFBF4C22D3B1A771`.

The export reads invoice number, stock code, invoice date, quantity, unit price and country. It excludes cancelled invoices, nonpositive quantities/prices and non-product codes, and keeps UK transactions within the dates above. Six frequently active SKUs are selected using training dates only. Transactions are aggregated to one row per SKU/day. A day without a transaction in this extract is explicitly recorded as zero sales, with the last previously observed unit price carried forward. `store_id=UK_ONLINE` and `channel=online` describe the one source retailer; the source does not supply branches or product categories. Customer identifiers and item descriptions are never read into the export.

The source prices are in GBP. `unit_price` in these demo CSVs is multiplied by a fixed **40 THB/GBP solely to match the application's baht display**. This is an assumed display conversion, not a historical exchange rate. The apparent baht revenue is not a real Thai company's revenue.

To reproduce, download the ZIP from `https://archive.ics.uci.edu/static/public/352/online%2Bretail.zip` into `backend/data/uploads/uci_online_retail.zip`, then run from `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_uci_demo_csv.py --source-zip data\uploads\uci_online_retail.zip
```

The script refuses to overwrite an existing output. To run the complete automated test without changing the main PostgreSQL database:

```powershell
.\.venv\Scripts\python.exe scripts\real_data_e2e.py --source-zip data\uploads\uci_online_retail.zip --postgres --browser
```

The 27 October 2026 run used `projecta1_test`: 6/6 series forecast, 168/168 forecast–actual pairs matched, and the reserved 28-day **revenue WAPE was 56.77%** versus 72.84% for repeating the previous week. WAPE is error, not accuracy. This dataset and final period have been inspected in earlier development, so this rerun checks reproducibility and the app workflow; it is not a new independent estimate of model performance. See [the full test report](../reports/uci-online-retail-e2e.md) and [model validation](../reports/forecast-model-validation-2026-10-21.md).
