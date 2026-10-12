"use client";

import { useEffect, useMemo, useState } from "react";

type Point = { date: string; forecast?: number };
type Period = { period: string; forecast_total: number; forecast_matched: number; actual: number; difference: number | null; matched_count: number; forecast_count: number };
type Report = { runs: { run_id: number; origin_date: string }[]; run_id: number | null; origin_date: string | null; periods: Period[] };
type Filters = { store: string; sku: string; category: string; channel: string };
type Props = { items: Point[]; filters: Filters; lang: "th" | "en" };

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const money = (value: number) => `฿${new Intl.NumberFormat("th-TH", { maximumFractionDigits: 0 }).format(value)}`;

function periodStart(value: string, grain: "week" | "month") {
  if (grain === "month") return `${value.slice(0, 7)}-01`;
  const day = new Date(`${value}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - ((day.getUTCDay() + 6) % 7));
  return day.toISOString().slice(0, 10);
}

export default function ForecastInsights({ items, filters, lang }: Props) {
  const th = lang === "th";
  const [grain, setGrain] = useState<"week" | "month">("week");
  const [runId, setRunId] = useState<number | null>(null);
  const [volumeChange, setVolumeChange] = useState(0);
  const [priceChange, setPriceChange] = useState(0);
  const [report, setReport] = useState<Report | null>(null);
  const [reportLoading, setReportLoading] = useState(true);
  const [reportError, setReportError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ grain });
    if (runId !== null) params.set("run_id", String(runId));
    if (filters.store) params.set("store_id", filters.store);
    if (filters.sku) params.set("sku_id", filters.sku);
    if (filters.category) params.set("category", filters.category);
    if (filters.channel) params.set("channel", filters.channel);
    setReportLoading(true);
    setReportError("");
    setReport(null);
    fetch(`${API}/reports/forecast-vs-actual?${params}`, { credentials: "include", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(th ? "โหลดรายงานไม่สำเร็จ" : "Could not load the report.");
        return response.json() as Promise<Report>;
      })
      .then(setReport)
      .catch(failure => { if (failure.name !== "AbortError") setReportError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setReportLoading(false); });
    return () => controller.abort();
  }, [grain, runId, filters.store, filters.sku, filters.category, filters.channel, th, retry]);

  const futurePeriods = useMemo(() => {
    const values = new Map<string, number>();
    for (const item of items) {
      const period = periodStart(item.date, grain);
      values.set(period, (values.get(period) ?? 0) + (item.forecast ?? 0));
    }
    return [...values].map(([period, value]) => ({ period, value }));
  }, [items, grain]);
  const baseline = items.reduce((sum, item) => sum + (item.forecast ?? 0), 0);
  const scenario = baseline * (1 + volumeChange / 100) * (1 + priceChange / 100);

  return <div className="insights-stack">
    <section className="surface scenario-surface" aria-labelledby="scenario-heading">
      <div className="section-heading"><div><p className="overline">WHAT-IF / PLANNING</p><h2 id="scenario-heading">{th ? "ลองปรับสมมติฐาน" : "Explore a scenario"}</h2><p className="muted">{th ? "คำนวณจากผลพยากรณ์เดิม ไม่ใช่การให้โมเดลทำนายใหม่" : "Arithmetic on the current forecast, not a new model prediction."}</p></div></div>
      {items.length ? <div className="scenario-layout">
        <div className="scenario-controls">
          <label htmlFor="scenario-volume">{th ? "ปริมาณขาย" : "Sales volume"} <strong>{volumeChange > 0 ? "+" : ""}{volumeChange}%</strong></label>
          <input id="scenario-volume" type="range" min="-50" max="50" step="5" value={volumeChange} onChange={event => setVolumeChange(Number(event.target.value))}/>
          <label htmlFor="scenario-price">{th ? "ราคาขายเฉลี่ย" : "Average selling price"} <strong>{priceChange > 0 ? "+" : ""}{priceChange}%</strong></label>
          <input id="scenario-price" type="range" min="-50" max="50" step="5" value={priceChange} onChange={event => setPriceChange(Number(event.target.value))}/>
          <button type="button" className="secondary" onClick={() => { setVolumeChange(0); setPriceChange(0); }} disabled={volumeChange === 0 && priceChange === 0}>{th ? "คืนค่าเริ่มต้น" : "Reset assumptions"}</button>
        </div>
        <div className="scenario-result" aria-live="polite"><span>{th ? "รายได้ตามสมมติฐาน" : "Scenario revenue"}</span><strong>{money(scenario)}</strong><small>{th ? "เทียบกับผลโมเดล" : "Versus model forecast"} {money(baseline)} · {scenario - baseline >= 0 ? "+" : "−"}{money(Math.abs(scenario - baseline))}</small><p>{th ? "สูตร: ผลพยากรณ์ × (1 + % ปริมาณ) × (1 + % ราคา) ไม่รวมผลกระทบต่อดีมานด์จากการเปลี่ยนราคา" : "Formula: forecast × volume factor × price factor. Price-driven demand changes are not modeled."}</p></div>
      </div> : <p className="muted insight-empty">{th ? "เทรนโมเดลก่อนจึงจะลองปรับสมมติฐานได้" : "Train a model before exploring scenarios."}</p>}
    </section>

    <section className="surface report-surface" aria-labelledby="report-heading">
      <div className="section-heading"><div><p className="overline">FORECAST REVIEW</p><h2 id="report-heading">{th ? "รายงานรายสัปดาห์ / เดือน" : "Weekly / monthly report"}</h2><p className="muted">{th ? "ผลที่บันทึกไว้ตอนเทรน เทียบกับยอดจริงที่นำเข้าภายหลัง" : "Saved training-time forecast versus actual sales imported later."}</p></div></div>
      <div className="report-controls">
        <label>{th ? "ช่วงรายงาน" : "Period"}<select value={grain} onChange={event => setGrain(event.target.value as "week" | "month")}><option value="week">{th ? "รายสัปดาห์" : "Weekly"}</option><option value="month">{th ? "รายเดือน" : "Monthly"}</option></select></label>
        {report?.runs.length ? <label>{th ? "รอบพยากรณ์" : "Forecast run"}<select value={runId ?? report.run_id ?? ""} onChange={event => setRunId(Number(event.target.value))}>{report.runs.map(run => <option key={run.run_id} value={run.run_id}>{run.origin_date} · #{run.run_id}</option>)}</select></label> : null}
      </div>
      {reportLoading ? <p className="muted insight-empty" role="status">{th ? "กำลังโหลดรายงาน…" : "Loading report…"}</p> : reportError ? <p className="model-warning" role="alert">{reportError} <button type="button" className="text-link" onClick={() => setRetry(value => value + 1)}>{th ? "ลองอีกครั้ง" : "Retry"}</button></p> : !report?.runs.length ? <p className="muted insight-empty">{th ? "ยังไม่มีผลพยากรณ์ที่บันทึกไว้ เทรนโมเดลใหม่เพื่อเริ่มเก็บผล" : "No saved forecast yet. Train a new model to start tracking."}</p> : <>
        <p className="report-note">{th ? `รอบวันที่ ${report.origin_date} · เทียบเฉพาะรายการที่มีข้อมูลจริงตรงวัน/สาขา/SKU/ช่องทาง` : `Run from ${report.origin_date} · only matching date/store/SKU/channel records are compared.`}</p>
        {report.periods.length > 0 && report.periods.every(period => period.matched_count === 0) ? <p className="model-warning" role="status">{th ? "ยังไม่พบยอดจริงในช่วงที่เคยพยากรณ์ไว้ นำเข้าข้อมูลวันที่ถัดไปเพื่อเริ่มเทียบผล" : "No actual sales for the saved forecast period yet. Import later dates to compare outcomes."}</p> : null}
        {report.periods.length ? <div className="table-scroll report-table"><table><thead><tr><th>{th ? "เริ่มช่วง" : "Period starts"}</th><th>{th ? "พยากรณ์ทั้งหมด" : "Full forecast"}</th><th>{th ? "พยากรณ์ที่เทียบได้" : "Matched forecast"}</th><th>{th ? "ยอดจริง" : "Actual"}</th><th>{th ? "ส่วนต่าง" : "Difference"}</th><th>{th ? "ข้อมูลที่เทียบได้" : "Coverage"}</th></tr></thead><tbody>{report.periods.map(period => <tr key={period.period}><td>{period.period}</td><td>{money(period.forecast_total)}</td><td>{period.matched_count ? money(period.forecast_matched) : "—"}</td><td>{period.matched_count ? money(period.actual) : "—"}</td><td>{period.difference == null ? "—" : `${period.difference >= 0 ? "+" : "−"}${money(Math.abs(period.difference))}`}</td><td>{period.matched_count}/{period.forecast_count}</td></tr>)}</tbody></table></div> : <p className="muted insight-empty">{th ? "ไม่มีข้อมูลในตัวกรองนี้" : "No data for these filters."}</p>}
        <p className="report-note">{th ? "หากความครอบคลุมไม่เต็ม ส่วนต่างคำนวณจากคู่ที่ตรงกันเท่านั้น; วันที่ไม่มีข้อมูลไม่ถือเป็นยอดขายศูนย์" : "When coverage is partial, difference uses matched pairs only; missing days are not zero sales."}</p>
      </>}
      {futurePeriods.length ? <div className="future-periods"><h3>{th ? "ยอดพยากรณ์ข้างหน้าตามช่วง" : "Upcoming forecast by period"}</h3><div className="future-period-list">{futurePeriods.map(period => <div key={period.period}><span>{period.period}</span><strong>{money(period.value)}</strong></div>)}</div></div> : null}
    </section>
  </div>;
}
