"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
type Filters = { store: string; sku: string; category: string; channel: string };
type Product = { sku_id: string; sku_name: string | null; recent_units: number; previous_units: number; recent_revenue: number | null;
  change_pct: number | null; history_complete: boolean; forecast_units: number | null; forecast_revenue: number | null;
  series_used: number; series_total: number };
type Channel = { channel: string; recent_revenue: number | null; forecast_revenue: number | null; history_complete: boolean };
type Action = { kind: "refresh_data" | "check_coverage" | "inspect_decline" | "review_model" | "check_stock" | "train_model" | "fix_prices";
  days?: number; series_used?: number; series_total?: number; sku_id?: string; change_pct?: number; forecast_units?: number };
type Insights = { as_of: string | null; recent_start?: string; products: Product[]; product_count: number; channels: Channel[]; channel_count: number;
  weekday: { status: "ready" | "no_data" | "missing_price" | "incomplete_history"; values: { day: number; average_revenue: number }[] };
  forecast_coverage: { series_used: number; series_total: number }; actions: Action[] };

const weekdays = { th: ["จ.", "อ.", "พ.", "พฤ.", "ศ.", "ส.", "อา."], en: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] };
const number = (value: number, lang: "th" | "en") => new Intl.NumberFormat(lang === "th" ? "th-TH" : "en-US", { maximumFractionDigits: 1 }).format(value);
const money = (value: number, lang: "th" | "en") => `฿${new Intl.NumberFormat(lang === "th" ? "th-TH" : "en-US", { maximumFractionDigits: 0 }).format(value)}`;

function actionText(action: Action, th: boolean) {
  switch (action.kind) {
    case "refresh_data": return th ? `ข้อมูลล่าสุดเก่า ${action.days} วัน — นำเข้ายอดขายใหม่ก่อนใช้วางแผน` : `Sales data is ${action.days} days old. Import recent sales before planning.`;
    case "check_coverage": return th ? `พยากรณ์ได้ ${action.series_used}/${action.series_total} ชุดข้อมูล — ตรวจวันที่ขาดก่อนใช้ยอดรวม` : `Forecast covers ${action.series_used}/${action.series_total} series. Review missing dates before using totals.`;
    case "inspect_decline": return th ? `ตรวจสอบ ${action.sku_id}: ยอดขายจริง 28 วันล่าสุดลดลง ${Math.abs((action.change_pct ?? 0) * 100).toFixed(0)}% เทียบช่วงก่อนหน้า` : `Review ${action.sku_id}: actual units fell ${Math.abs((action.change_pct ?? 0) * 100).toFixed(0)}% versus the prior 28 days.`;
    case "review_model": return th ? "ตรวจผลทดสอบโมเดลก่อนใช้ตัวเลขพยากรณ์ตัดสินใจ" : "Review model evaluation before making decisions from the forecast.";
    case "check_stock": return th ? `เทียบสต็อก ${action.sku_id} กับยอดพยากรณ์ ${number(action.forecast_units ?? 0, "th")} ชิ้น — ระบบยังไม่มีข้อมูลสต็อก` : `Compare ${action.sku_id} stock with ${number(action.forecast_units ?? 0, "en")} forecast units. Inventory is not connected.`;
    case "train_model": return th ? "ยังไม่มีผลพยากรณ์ที่ใช้ได้ — เทรนโมเดลหลังตรวจข้อมูล" : "No usable forecast yet. Train after checking the data.";
    case "fix_prices": return th ? "ข้อมูลบางแถวไม่มีราคา — นำเข้าไฟล์ที่มีราคาครบก่อนดูพยากรณ์รายได้" : "Some rows have no price. Import complete prices before reviewing revenue forecasts.";
  }
}

export default function SalesInsights({ filters, dataVersion, lang, onImport, onModel, onUnauthorized }: {
  filters: Filters; dataVersion: object; lang: "th" | "en"; onImport: () => void; onModel: () => void; onUnauthorized: () => void;
}) {
  const [data, setData] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const th = lang === "th";
  const hasFilters = Boolean(filters.store || filters.sku || filters.category || filters.channel);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams();
    if (filters.store) params.set("store_id", filters.store);
    if (filters.sku) params.set("sku_id", filters.sku);
    if (filters.category) params.set("category", filters.category);
    if (filters.channel) params.set("channel", filters.channel);
    setLoading(true); setError(false); setData(null);
    fetch(`${API}/insights?${params}`, { credentials: "include", signal: controller.signal })
      .then(response => { if (response.status === 401) { onUnauthorized(); throw new Error("unauthorized"); } if (!response.ok) throw new Error("load"); return response.json(); })
      .then((result: Insights) => setData(result))
      .catch(failure => { if (failure.name !== "AbortError" && failure.message !== "unauthorized") setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filters.store, filters.sku, filters.category, filters.channel, dataVersion, retry, onUnauthorized]);

  const maxChannel = Math.max(1, ...(data?.channels.map(item => item.recent_revenue ?? 0) ?? []));
  const maxWeekday = Math.max(1, ...(data?.weekday.values.map(item => item.average_revenue) ?? []));

  return <section className="insight-section" aria-labelledby="insight-title">
    <div className="section-heading insight-heading"><div><p className="overline">PRODUCT & CHANNEL SIGNALS</p><h2 id="insight-title">{th ? "สินค้าและช่องทางที่ควรดู" : "Products and channels to watch"}</h2><p className="muted">{th ? "เทียบยอดจริง 28 วันล่าสุดกับ 28 วันก่อนหน้า · ไม่ใช่ข้อมูลลูกค้าหรือที่มาของลีด" : "Compare the latest 28 actual days with the prior 28 · not customer or lead-source data"}</p></div>{data?.as_of && <span className="insight-asof">{th ? "ข้อมูลถึง" : "Data through"} {data.as_of}</span>}</div>
    {loading ? <div className="surface insight-state" role="status">{th ? "กำลังวิเคราะห์สินค้าและช่องทาง…" : "Loading product and channel insights…"}</div>
      : error ? <div className="surface insight-state" role="alert">{th ? "โหลดข้อมูลเชิงลึกไม่สำเร็จ" : "Could not load insights."} <button className="text-link" type="button" onClick={() => setRetry(value => value + 1)}>{th ? "ลองอีกครั้ง" : "Retry"}</button></div>
      : !data?.as_of ? <div className="surface insight-state"><h3>{hasFilters ? (th ? "ไม่พบข้อมูลตามตัวกรอง" : "No matching data") : (th ? "ยังไม่มีข้อมูลยอดขาย" : "No sales data yet")}</h3><p className="muted">{hasFilters ? (th ? "ลองเปลี่ยนสาขา SKU หมวดหมู่ หรือช่องทางด้านบน" : "Change the store, SKU, category, or channel filters above.") : (th ? "นำเข้าข้อมูลเพื่อดูสินค้าและช่องทาง" : "Import sales to explore products and channels.")}</p>{!hasFilters && <button className="secondary" type="button" onClick={onImport}>{th ? "นำเข้าข้อมูล" : "Import data"} →</button>}</div>
      : data.products.length === 0 ? <div className="surface insight-state"><h3>{th ? "ไม่พบข้อมูลตามตัวกรอง" : "No matching data"}</h3><p className="muted">{th ? "ลองเปลี่ยนสาขา SKU หมวดหมู่ หรือช่องทางด้านบน" : "Change the store, SKU, category, or channel filters above."}</p></div>
      : <>
        <div className="insight-grid">
          <section className="surface insight-product"><div className="section-heading"><div><p className="overline">SKU / 28 DAYS</p><h3>{th ? "รายสินค้าจากข้อมูลจริงและผลพยากรณ์" : "Actual and forecast by product"}</h3></div><span className="insight-count">{data.product_count} SKU</span></div>
            <div className="table-scroll insight-table"><table><thead><tr><th>{th ? "สินค้า" : "Product"}</th><th>{th ? "ขายจริง" : "Actual units"}</th><th>{th ? "เทียบ 28 วันก่อน" : "Vs prior 28d"}</th><th>{th ? "พยากรณ์ชิ้น" : "Forecast units"}</th><th>{th ? "พยากรณ์รายได้" : "Forecast revenue"}</th></tr></thead><tbody>{data.products.map(item => <tr key={item.sku_id}><td><strong>{item.sku_name || item.sku_id}</strong>{item.sku_name && <small>{item.sku_id}</small>}</td><td>{number(item.recent_units, lang)}</td><td>{item.change_pct == null ? <span className="muted" title={th ? "ข้อมูลรายวันไม่ครบหรือยอดช่วงก่อนเป็นศูนย์" : "Missing daily history or zero prior units"}>—</span> : <span className={item.change_pct < 0 ? "insight-down" : "insight-up"}>{item.change_pct >= 0 ? "+" : ""}{(item.change_pct * 100).toFixed(0)}%</span>}</td><td>{item.forecast_units == null ? "—" : number(item.forecast_units, lang)}</td><td>{item.forecast_revenue == null ? "—" : money(item.forecast_revenue, lang)}</td></tr>)}</tbody></table></div>
            <p className="insight-scroll-hint">{th ? "เลื่อนตารางไปทางขวาเพื่อดูคอลัมน์เพิ่มเติม →" : "Scroll the table right for more columns →"}</p>
            <p className="insight-caption">{th ? `แสดงสูงสุด 8 จาก ${data.product_count} SKU · พยากรณ์ครอบคลุม ${data.forecast_coverage.series_used}/${data.forecast_coverage.series_total} ชุดสาขา/SKU/ช่องทาง · “—” หมายถึงข้อมูลไม่ครบหรือยอดช่วงก่อนเป็นศูนย์` : `Top 8 of ${data.product_count} SKUs · forecast covers ${data.forecast_coverage.series_used}/${data.forecast_coverage.series_total} store/SKU/channel series · “—” means incomplete data or zero prior units`}</p>
          </section>
          <section className="surface insight-channel"><p className="overline">CHANNEL MIX</p><h3>{th ? "ยอดขายตามช่องทาง" : "Sales by channel"}</h3><p className="muted">{th ? "แท่งกราฟคือรายได้จริง 28 วันล่าสุด" : "Bars show actual revenue in the latest 28 days"}</p><div className="channel-list">{data.channels.map(item => <div className="channel-item" key={item.channel}><div><strong>{item.channel}</strong><span>{item.recent_revenue == null ? "—" : money(item.recent_revenue, lang)}</span></div>{item.recent_revenue != null && <div className="channel-track"><span style={{ width: `${Math.max(2, item.recent_revenue / maxChannel * 100)}%` }}/></div>}<small>{th ? "พยากรณ์ 28 วัน" : "28-day forecast"}: {item.forecast_revenue == null ? "—" : money(item.forecast_revenue, lang)}</small></div>)}</div><p className="insight-caption">{data.channels.some(item => item.recent_revenue == null) ? (th ? "ข้อมูลราคายังไม่ครบ จึงไม่แสดงรายได้จริงบางส่วน" : "Price data is incomplete, so actual revenue is hidden.") : data.channel_count === 1 ? (th ? "มีเพียงช่องทางเดียว จึงยังเปรียบเทียบช่องทางไม่ได้" : "Only one channel is available; there is no channel comparison yet.") : (th ? `แสดงสูงสุด 8 จาก ${data.channel_count} ช่องทาง · ช่องทางขายไม่ใช่แหล่งที่มาของลูกค้า` : `Top 8 of ${data.channel_count} channels · sales channel is not lead source or ad attribution.`)}</p></section>
        </div>
        <div className="insight-grid insight-secondary">
          <section className="surface insight-weekday"><p className="overline">WEEKLY RHYTHM</p><h3>{th ? "วันที่ยอดขายจริงสูง" : "Actual sales by weekday"}</h3>{data.weekday.status === "ready" ? <><p className="muted">{th ? "รายได้เฉลี่ยต่อวันใน 8 สัปดาห์ล่าสุด ไม่ใช่เวลาที่ลูกค้าตัดสินใจซื้อ" : "Average daily revenue over the last 8 weeks, not customer purchase timing."}</p><div className="weekday-bars" role="img" aria-label={th ? "รายได้จริงเฉลี่ยแยกตามวันในสัปดาห์" : "Average actual revenue by weekday"}>{data.weekday.values.map(item => <div className="weekday-item" key={item.day}><span>{weekdays[lang][item.day]}</span><div className="weekday-track"><span style={{ width: `${item.average_revenue / maxWeekday * 100}%` }}/></div><strong>{money(item.average_revenue, lang)}</strong></div>)}</div></> : <p className="muted insight-unavailable">{data.weekday.status === "missing_price" ? (th ? "ข้อมูลราคายังไม่ครบ จึงสรุปรายได้ตามวันไม่ได้" : "Price data is incomplete; weekday revenue is unavailable.") : (th ? "ต้องมีข้อมูลครบทุกวันต่อเนื่อง 8 สัปดาห์ รวมวันที่ยอดขายเป็นศูนย์" : "Eight complete weeks of daily data, including zero-sale days, are required.")}</p>}</section>
          <section className="surface insight-actions"><p className="overline">NEXT CHECKS</p><h3>{th ? "สิ่งที่ควรตรวจต่อ" : "What to check next"}</h3><p className="muted">{th ? "ข้อสังเกตตามกฎที่ระบุ ไม่ใช่คำสั่งจาก AI หรือการยืนยันสาเหตุ" : "Rule-based observations, not AI instructions or causal claims."}</p>{data.actions.length ? <ul>{data.actions.slice(0, 4).map((item, index) => <li key={`${item.kind}-${index}`}>{actionText(item, th)}</li>)}</ul> : <p className="insight-unavailable muted">{th ? "ยังไม่พบข้อสังเกตตามเกณฑ์เบื้องต้น" : "No items under the basic checks."}</p>}{data.actions.some(item => item.kind === "refresh_data" || item.kind === "check_coverage" || item.kind === "fix_prices") && <button className="text-link" type="button" onClick={onImport}>{th ? "ดูการนำเข้าข้อมูล" : "Review data import"} →</button>}{data.actions.some(item => item.kind === "review_model" || item.kind === "train_model") && <button className="text-link" type="button" onClick={onModel}>{th ? "ดูผลโมเดล" : "Review model"} →</button>}</section>
        </div>
      </>}
  </section>;
}
