r"""Run an isolated HTTP smoke test with real UCI Online Retail transactions.

From backend/: .\.venv\Scripts\python.exe scripts\real_data_e2e.py
No user database or model artifacts are modified. The raw source stays in OS temp.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
import zipfile

import pandas as pd
import uvicorn
from sqlalchemy import text
from sqlalchemy.engine import make_url

SOURCE_URL = "https://archive.ics.uci.edu/static/public/352/online%2Bretail.zip"
SOURCE_NAME = "Online Retail.xlsx"
START = pd.Timestamp("2011-04-05")
TRAIN_END = pd.Timestamp("2011-11-02")
HOLDOUT_END = pd.Timestamp("2011-11-30")
SKU_COUNT = 6
# Demo-only normalization because the current UI labels money in THB. Not a historical FX rate.
DEMO_THB_PER_GBP = 40.0


def source_path(explicit: Path | None, temp: Path) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(explicit)
        return explicit
    path = temp / "online-retail.zip"
    print("Downloading UCI Online Retail into the isolated test directory.", flush=True)
    with urlopen(SOURCE_URL, timeout=90) as response, path.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    return path


def prepare_data(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    with zipfile.ZipFile(path) as archive, archive.open(SOURCE_NAME) as workbook:
        raw = pd.read_excel(workbook, engine="openpyxl", dtype={"StockCode": str, "InvoiceNo": str},
                            usecols=["InvoiceNo", "StockCode", "InvoiceDate", "Quantity", "UnitPrice", "Country"])
    source_rows = len(raw)
    # CustomerID and free-text Description are not even read from the workbook.
    sales = raw[["InvoiceNo", "StockCode", "InvoiceDate", "Quantity", "UnitPrice", "Country"]].copy()
    sales = sales[
        sales.Country.eq("United Kingdom")
        & ~sales.InvoiceNo.str.upper().str.startswith("C", na=True)
        & sales.StockCode.str.fullmatch(r"\d{5}[A-Z]?", na=False)
        & sales.Quantity.gt(0)
        & sales.UnitPrice.gt(0)
        & sales.InvoiceDate.between(START, HOLDOUT_END + pd.Timedelta(days=1), inclusive="left")
    ].copy()
    sales["date"] = sales.InvoiceDate.dt.normalize()
    sales["revenue_gbp"] = sales.Quantity * sales.UnitPrice
    # Select series using only dates available at training time, never the holdout.
    training_sales = sales[sales.date.le(TRAIN_END)]
    activity = training_sales.groupby("StockCode").agg(first=("date", "min"), last=("date", "max"), active_days=("date", "nunique"))
    eligible = activity[(activity["first"] <= START) & (activity["last"] >= TRAIN_END - pd.Timedelta(days=7))]
    codes = eligible.sort_values(["active_days", "first"], ascending=[False, True]).head(SKU_COUNT).index.tolist()
    if len(codes) != SKU_COUNT:
        raise ValueError(f"Only {len(codes)} eligible SKUs; expected {SKU_COUNT}")
    selected = sales[sales.StockCode.isin(codes)]
    daily = selected.groupby(["StockCode", "date"], as_index=False).agg(
        quantity_sold=("Quantity", "sum"), revenue_gbp=("revenue_gbp", "sum")
    )
    dates = pd.date_range(START, HOLDOUT_END, freq="D")
    frames = []
    for code in codes:
        product = daily[daily.StockCode.eq(code)].set_index("date").reindex(dates)
        product["quantity_sold"] = product.quantity_sold.fillna(0)
        product["unit_price"] = (product.revenue_gbp / product.quantity_sold.replace(0, float("nan"))).ffill()
        if product.unit_price.isna().any():
            raise ValueError(f"Missing prior observed price for SKU {code}")
        frames.append(pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"), "store_id": "UK_ONLINE", "sku_id": code,
            "channel": "online", "quantity_sold": product.quantity_sold.to_numpy(),
            "unit_price": (product.unit_price * DEMO_THB_PER_GBP).round(6).to_numpy(),
        }))
    full = pd.concat(frames, ignore_index=True).sort_values(["date", "sku_id"]).reset_index(drop=True)
    initial = full[full.date.le(TRAIN_END.strftime("%Y-%m-%d"))].copy()
    details = {
        "source_rows": source_rows, "usable_transaction_rows": len(sales), "selected_transaction_rows": len(selected),
        "sku_ids": codes, "start": str(START.date()), "train_end": str(TRAIN_END.date()),
        "holdout_end": str(HOLDOUT_END.date()), "zero_sale_rows": int(full.quantity_sold.eq(0).sum()),
        "initial_rows": len(initial), "full_rows": len(full), "demo_thb_per_gbp": DEMO_THB_PER_GBP,
    }
    return initial, full, details


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")


def multipart(file_bytes: bytes) -> tuple[bytes, str]:
    boundary = f"projecta-{secrets.token_hex(12)}"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"uci-retail.csv\"\r\n"
            "Content-Type: text/csv\r\n\r\n").encode() + file_bytes + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def open_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def browser_smoke(api_port: int, web_port: int, email: str, password: str) -> dict:
    project = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "NEXT_PUBLIC_API_URL": f"http://127.0.0.1:{api_port}/api/v1"}
    next_bin = project / "node_modules" / "next" / "dist" / "bin" / "next"
    startup_log = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    server = subprocess.Popen(
        ["node", str(next_bin), "dev", "-H", "127.0.0.1", "-p", str(web_port)],
        cwd=project, env=environment, stdout=startup_log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    web_url = f"http://127.0.0.1:{web_port}/"
    script = r"""
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.E2E_WEB_URL, { waitUntil: 'domcontentloaded' });
    await page.locator('input[name="email"]').fill(process.env.E2E_EMAIL);
    await page.locator('input[name="password"]').fill(process.env.E2E_PASSWORD);
    await page.locator('.auth-card button.primary').click();
    await page.locator('.stat-grid').waitFor({ timeout: 30000 });
    await page.locator('.stat-grid').getByText('2011-11-30', { exact: false }).waitFor({ timeout: 30000 });
    const overview = await page.locator('.stat-grid').innerText();
    assert(overview.includes('2011-11-30') && overview.includes('6'), overview);
    const title = await page.title();
    await page.getByRole('button', { name: 'การพยากรณ์', exact: true }).click();
    await page.locator('.report-table tbody tr').first().waitFor({ timeout: 30000 });
    const reportRows = await page.locator('.report-table tbody tr').count();
    const reportText = await page.locator('.report-table').innerText();
    assert(reportText.includes('/'), reportText);
    await page.locator('.report-surface').scrollIntoViewIfNeeded();
    await page.waitForTimeout(700);
    const desktop = require('node:path').join(process.env.TEMP, 'projecta-real-data-desktop.png');
    await page.screenshot({ path: desktop });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.report-surface').scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(overflow, false);
    const mobile = require('node:path').join(process.env.TEMP, 'projecta-real-data-mobile.png');
    await page.screenshot({ path: mobile });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ title, reportRows, horizontalOverflow: overflow, browserErrors: errors, screenshots: [desktop, mobile] }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    try:
        for _ in range(80):
            if server.poll() is not None:
                startup_log.seek(0)
                raise RuntimeError(f"Next.js exited with code {server.returncode}: {startup_log.read()[-2000:]}")
            try:
                with urlopen(web_url, timeout=15):
                    break
            except (URLError, TimeoutError):
                time.sleep(.5)
        else:
            startup_log.seek(0)
            raise RuntimeError(f"Next.js did not start: {startup_log.read()[-2000:]}")
        result = subprocess.run(
            ["node", "-e", script], cwd=project,
            env={**environment, "E2E_WEB_URL": web_url, "E2E_EMAIL": email, "E2E_PASSWORD": password},
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, check=False,
        )
        if result.returncode:
            raise RuntimeError(f"Browser smoke failed: {(result.stderr or '').strip()}")
        return json.loads(result.stdout.strip())
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        startup_log.close()


def postgres_test_url() -> str:
    """Derive a separate test database from the configured PostgreSQL database."""
    from dotenv import dotenv_values

    backend = Path(__file__).resolve().parents[1]
    configured = os.environ.get("DATABASE_URL") or dotenv_values(backend / ".env").get("DATABASE_URL")
    if not configured:
        raise ValueError("Set DATABASE_URL in backend/.env before using --postgres")
    url = make_url(configured)
    if not url.drivername.startswith("postgresql") or not url.database or url.database.endswith("_test"):
        raise ValueError("--postgres requires a non-test PostgreSQL DATABASE_URL")
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def exercise_api(initial: pd.DataFrame, full: pd.DataFrame, temp: Path, check_browser: bool,
                 database_url: str | None = None) -> dict:
    os.environ["DATABASE_URL"] = database_url or f"sqlite:///{(temp / 'real-data.db').as_posix()}"
    web_port = open_port() if check_browser else None
    if web_port is not None:
        os.environ["CORS_ORIGINS"] = f"http://localhost:3000,http://127.0.0.1:{web_port}"
    if database_url:
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import forecasting
    forecasting.ARTIFACTS = temp / "artifacts"
    from app.main import app

    port = open_port()
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    cookies = http.cookiejar.CookieJar()
    client = build_opener(HTTPCookieProcessor(cookies))

    def call(method: str, route: str, body: bytes | None = None, content_type: str | None = None) -> dict:
        headers = {"Origin": "http://localhost:3000"} if method != "GET" else {}
        if content_type:
            headers["Content-Type"] = content_type
        request = Request(base + route, data=body, headers=headers, method=method)
        try:
            with client.open(request, timeout=180) as response:
                return json.load(response)
        except HTTPError as error:
            raise RuntimeError(f"{method} {route}: HTTP {error.code}: {error.read().decode()}") from error

    try:
        for _ in range(100):
            try:
                with urlopen(base + "/health", timeout=1):
                    break
            except (URLError, TimeoutError):
                time.sleep(.1)
        else:
            raise RuntimeError("API server did not start")

        email = f"uci-e2e-{secrets.token_hex(5)}@example.invalid"
        password = secrets.token_urlsafe(20)
        signup = json.dumps({"organization_name": f"UCI retail test {secrets.token_hex(5)}", "display_name": "Test Owner",
                             "email": email, "password": password}).encode()
        user = call("POST", "/api/v1/auth/register", signup, "application/json")
        assert user["role"] == "owner"
        assert call("GET", "/api/v1/auth/me")["id"] == user["id"]

        initial_csv = csv_bytes(initial)
        full_csv = csv_bytes(full)
        validation_body, validation_type = multipart(initial_csv)
        validated = call("POST", "/api/v1/uploads/validate", validation_body, validation_type)
        assert validated["rows"] == len(initial) and validated["missing_days"] == 0
        print("Upload validation passed; importing historical window.", flush=True)
        import_body, import_type = multipart(initial_csv)
        imported = call("POST", "/api/v1/uploads/import", import_body, import_type)
        assert imported["imported"] == len(initial)
        summary = call("GET", "/api/v1/summary")
        assert summary["record_count"] == len(initial) and summary["sku_count"] == SKU_COUNT

        trained = call("POST", "/api/v1/models/train")
        assert trained["status"] == "completed", trained
        print("Model training and rolling backtests completed.", flush=True)
        forecast = call("GET", "/api/v1/forecast?days=28")
        assert forecast["source"] == "trained" and len(forecast["items"]) == 28
        assert forecast["coverage"] == {"series_used": SKU_COUNT, "series_total": SKU_COUNT}
        before = call("GET", "/api/v1/reports/forecast-vs-actual?grain=week")
        assert sum(p["matched_count"] for p in before["periods"]) == 0

        full_body, full_type = multipart(full_csv)
        assert call("POST", "/api/v1/uploads/import", full_body, full_type)["imported"] == len(full)
        print("Held-out actuals imported; checking saved forecast comparison.", flush=True)
        after = call("GET", "/api/v1/reports/forecast-vs-actual?grain=week")
        matched = sum(p["matched_count"] for p in after["periods"])
        assert matched == SKU_COUNT * 28, (matched, after)
        assert sum(p["forecast_count"] for p in after["periods"]) == matched
        assert call("GET", "/api/v1/summary")["model"]["status"] == "superseded"
        assert call("GET", "/api/v1/forecast?days=28")["source"] == "empty"

        from app.database import engine
        with engine.connect() as db:
            pairs = db.execute(text("""SELECT s.target_date, s.sku_id, s.forecast_revenue,
                                     a.quantity_sold * a.unit_price
                              FROM forecast_snapshots s JOIN sales_records a
                              ON a.organization_id=s.organization_id AND a.date=s.target_date
                              AND a.store_id=s.store_id AND a.sku_id=s.sku_id AND a.channel=s.channel
                              WHERE s.organization_id=(SELECT organization_id FROM users WHERE id=:user_id)"""),
                               {"user_id": user["id"]}).fetchall()
        assert len(pairs) == matched
        actual_total = sum(row[3] for row in pairs)
        forecast_total = sum(row[2] for row in pairs)
        holdout_wape = sum(abs(row[3] - row[2]) for row in pairs) / actual_total
        prior_week = initial[initial.date.gt((TRAIN_END - pd.Timedelta(days=7)).strftime("%Y-%m-%d"))]
        naive_by_sku = {sku: list(group.sort_values("date").quantity_sold) for sku, group in prior_week.groupby("sku_id")}
        price_by_sku = {sku: float(group.sort_values("date").unit_price.iloc[-1]) for sku, group in initial.groupby("sku_id")}
        baseline_error = 0.0
        for day, sku, _, actual in pairs:
            offset = (pd.Timestamp(day) - TRAIN_END).days - 1
            baseline_error += abs(actual - naive_by_sku[sku][offset % 7] * price_by_sku[sku])
        assert abs(actual_total - sum(p["actual"] for p in after["periods"])) < .1
        result = {
            "validation_rows": validated["rows"], "missing_calendar_days": validated["missing_days"],
            "backtests": trained["metrics"]["backtests"], "forecast_days": len(forecast["items"]),
            "forecast_coverage": forecast["coverage"], "snapshot_matched_rows": matched,
            "holdout_actual_thb": round(actual_total, 2), "holdout_forecast_thb": round(forecast_total, 2),
            "holdout_wape": round(holdout_wape, 4), "holdout_weekly_naive_wape": round(baseline_error / actual_total, 4),
            "preimport_report_matched_rows": 0, "postimport_model_status": "superseded",
        }
        if web_port is not None:
            print("Checking login, overview and saved report in Edge/Playwright.", flush=True)
            result["browser"] = browser_smoke(port, web_port, email, password)
        return result
    except Exception as error:
        print(f"Real-data E2E failed: {ascii(error)}", flush=True)
        raise
    finally:
        server.should_exit = True
        thread.join(timeout=30)
        from app.database import engine
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", type=Path, help="Existing UCI download; default caches in OS temp")
    parser.add_argument("--browser", action="store_true", help="Also smoke-test the real-data UI in headless Edge")
    parser.add_argument("--postgres", action="store_true", help="Use a separate <DATABASE_URL>_test PostgreSQL database")
    args = parser.parse_args()
    database_url = postgres_test_url() if args.postgres else None
    with tempfile.TemporaryDirectory(prefix="projecta-real-e2e-") as directory:
        temp = Path(directory)
        initial, full, source = prepare_data(source_path(args.source_zip, temp))
        print("Prepared PII-free daily sales with an untouched 28-day holdout.", flush=True)
        result = exercise_api(initial, full, temp, args.browser, database_url)
    print(json.dumps({"source": source, "results": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
