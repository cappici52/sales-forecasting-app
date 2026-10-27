r"""Read-only browser smoke test of the migrated main PostgreSQL account.

Creates one short-lived auth session for the existing owner and deletes it in
finally. Does not import, train, or modify the organization's sales/model data.
Run from backend/: .\.venv\Scripts\python.exe scripts\smoke_main_postgres.py
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

from sqlalchemy import delete
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import token_hash
from app.config import settings
from app.database import SessionLocal
from app.models import AuthSession, SalesRecord, User
from scripts.real_data_e2e import open_port


def main() -> None:
    if not settings.database_url.startswith("postgresql") or settings.database_url.endswith("_test"):
        raise SystemExit("This smoke test requires the main PostgreSQL DATABASE_URL")
    project = Path(__file__).resolve().parents[2]
    api_port, web_port = open_port(), open_port()
    api_url = f"http://127.0.0.1:{api_port}"
    web_url = f"http://127.0.0.1:{web_port}"
    os.environ["CORS_ORIGINS"] = web_url

    with SessionLocal() as db:
        owner = (db.query(User).join(SalesRecord, User.organization_id == SalesRecord.organization_id)
                 .filter(User.role == "owner").first())
        if owner is None:
            raise RuntimeError("No migrated owner with sales records found")
        user_id = owner.id
        sales_count = db.query(SalesRecord).filter_by(organization_id=owner.organization_id).count()
        token = secrets.token_urlsafe(32)
        hashed = token_hash(token)
        db.add(AuthSession(user_id=user_id, token_hash=hashed,
                           expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)))
        db.commit()

    api_log = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    web_log = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
    api = web = None
    try:
        environment = {**os.environ, "CORS_ORIGINS": web_url}
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
                               cwd=project / "backend", env=environment, stdout=api_log, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        web = subprocess.Popen(["node", str(project / "node_modules" / "next" / "dist" / "bin" / "next"),
                                "dev", "-H", "127.0.0.1", "-p", str(web_port)], cwd=project,
                               env={**environment, "NEXT_PUBLIC_API_URL": api_url + "/api/v1"},
                               stdout=web_log, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for process, url, log, label in ((api, api_url + "/health", api_log, "API"), (web, web_url, web_log, "Next.js")):
            for _ in range(120):
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(f"{label} exited: {log.read()[-2000:]}")
                try:
                    with urlopen(url, timeout=2):
                        break
                except (URLError, TimeoutError):
                    time.sleep(.5)
            else:
                log.seek(0)
                raise RuntimeError(f"{label} did not start: {log.read()[-2000:]}")

        script = r"""
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
    await context.addCookies([{ name: 'projecta_session', value: process.env.SMOKE_TOKEN, url: process.env.SMOKE_API_URL, httpOnly: true, sameSite: 'Lax' }]);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.SMOKE_WEB_URL, { waitUntil: 'domcontentloaded' });
    await page.locator('.stat-grid').waitFor({ timeout: 45000 });
    await page.locator('.stat-grid').getByText('2011-11-30', { exact: false }).waitFor({ timeout: 45000 });
    const overview = await page.locator('.stat-grid').innerText();
    assert(overview.includes('2011-11-30') && overview.includes('6'), overview);
    const title = await page.title();
    await page.getByRole('button', { name: 'การพยากรณ์', exact: true }).click();
    await page.locator('.forecast-workspace').waitFor({ timeout: 30000 });
    await page.locator('.forecast-chart-surface .trend-chart').waitFor({ timeout: 60000 });
    await page.locator('.report-table tbody tr').first().waitFor({ timeout: 30000 });
    const reportRows = await page.locator('.report-table tbody tr').count();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(400);
    const forecastScreenshot = require('node:path').join(process.env.TEMP, 'projecta-main-forecast-desktop.png');
    await page.screenshot({ path: forecastScreenshot });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    const forecastOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(forecastOverflow, false);
    const forecastMobileScreenshot = require('node:path').join(process.env.TEMP, 'projecta-main-forecast-mobile.png');
    await page.screenshot({ path: forecastMobileScreenshot });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole('button', { name: 'นำเข้าข้อมูล', exact: true }).click();
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: /ส่งออกข้อมูลปัจจุบันเป็น CSV/ }).click();
    const download = await downloadPromise;
    assert.equal(download.suggestedFilename(), 'projecta-sales.csv');
    await page.getByRole('button', { name: 'ประสิทธิภาพโมเดล', exact: true }).click();
    await page.locator('.model-grid').first().waitFor({ timeout: 30000 });
    await page.waitForTimeout(900);
    const screenshot = require('node:path').join(process.env.TEMP, 'projecta-main-postgres-smoke.png');
    await page.screenshot({ path: screenshot });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(400);
    const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(horizontalOverflow, false);
    const mobileScreenshot = require('node:path').join(process.env.TEMP, 'projecta-main-postgres-mobile.png');
    await page.screenshot({ path: mobileScreenshot });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ title, reportRows, exportFilename: download.suggestedFilename(), horizontalOverflow, forecastOverflow, browserErrors: errors, screenshots: [forecastScreenshot, forecastMobileScreenshot, screenshot, mobileScreenshot] }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(["node", "-e", script], cwd=project, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120,
                                env={**environment, "SMOKE_TOKEN": token, "SMOKE_API_URL": api_url,
                                     "SMOKE_WEB_URL": web_url}, check=False)
        if result.returncode:
            raise RuntimeError(f"Browser smoke failed: {result.stderr.strip()}")
        print(json.dumps({"sales_records": sales_count, **json.loads(result.stdout.strip())}, ensure_ascii=False))
    finally:
        for process in (web, api):
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        api_log.close()
        web_log.close()
        with SessionLocal() as db:
            db.execute(delete(AuthSession).where(AuthSession.token_hash == hashed))
            db.commit()


if __name__ == "__main__":
    main()
