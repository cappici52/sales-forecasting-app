"use client";

import { useEffect, useRef, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
type Lang = "th" | "en";
type Filters = { store: string; category: string; channel: string };
type Product = { sku_id: string; sku_name: string | null; category: string | null; recent_units: number;
  previous_units: number; recent_revenue: number | null; forecast_units: number | null;
  forecast_revenue: number | null; change_pct: number | null; history_complete: boolean;
  series_used: number; series_total: number };
type Catalog = { as_of: string | null; recent_start: string | null; total: number; page: number;
  page_size: number; items: Product[] };
type Insights = { as_of: string | null; recent_start?: string; products: Product[] };
type Point = { date: string; actual?: number; forecast?: number };
type Forecast = { source: string; method?: "xgboost" | "weekly_naive"; history: Point[];
  items: Point[]; coverage?: { series_used: number; series_total: number } };
type Detail = { product: Product; asOf: string; recentStart: string; forecast: Forecast };
const number = (value: number, lang: Lang) => new Intl.NumberFormat(lang === "th" ? "th-TH" : "en-US", { maximumFractionDigits: 1 }).format(value);
const money = (value: number, lang: Lang) => `฿${new Intl.NumberFormat(lang === "th" ? "th-TH" : "en-US", { maximumFractionDigits: 0 }).format(value)}`;

export default function ProductExplorer({ filters, dataVersion, lang, modelReview, selectedSku, onSelectSku, onUnauthorized, onOpenForecast }: {
  filters: Filters; dataVersion: object; lang: Lang; modelReview: boolean; onUnauthorized: () => void;
  selectedSku: string | null; onSelectSku: (sku: string | null) => void; onOpenForecast: (sku: string) => void;
}) {
  const th = lang === "th";
  const searchRef = useRef<HTMLInputElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [composing, setComposing] = useState(false);
  const [sort, setSort] = useState("recent_revenue");
  const [page, setPage] = useState(1);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState(false);
  const [catalogRetry, setCatalogRetry] = useState(0);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(false);
  const [detailRetry, setDetailRetry] = useState(0);

  useEffect(() => {
    if (composing) return;
    const timer = window.setTimeout(() => { setQuery(draft.trim()); setPage(1); }, 300);
    return () => window.clearTimeout(timer);
  }, [draft, composing]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ query, sort, page: String(page) });
    if (filters.store) params.set("store_id", filters.store);
    if (filters.category) params.set("category", filters.category);
    if (filters.channel) params.set("channel", filters.channel);
    setCatalogLoading(true); setCatalogError(false); setCatalog(null);
    fetch(`${API}/products?${params}`, { credentials: "include", signal: controller.signal })
      .then(response => {
        if (response.status === 401) { onUnauthorized(); throw new Error("unauthorized"); }
        if (!response.ok) throw new Error("load");
        return response.json() as Promise<Catalog>;
      })
      .then(setCatalog)
      .catch(error => { if (error.name !== "AbortError" && error.message !== "unauthorized") setCatalogError(true); })
      .finally(() => { if (!controller.signal.aborted) setCatalogLoading(false); });
    return () => controller.abort();
  }, [query, sort, page, filters.store, filters.category, filters.channel, dataVersion, catalogRetry, onUnauthorized]);

  useEffect(() => { setPage(1); onSelectSku(null); }, [filters.store, filters.category, filters.channel, dataVersion, onSelectSku]);

  useEffect(() => {
    if (!selectedSku) return;
    const frame = window.requestAnimationFrame(() => detailRef.current?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start",
    }));
    return () => window.cancelAnimationFrame(frame);
  }, [selectedSku]);

  useEffect(() => {
    if (!selectedSku) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ sku_id: selectedSku });
    if (filters.store) params.set("store_id", filters.store);
    if (filters.category) params.set("category", filters.category);
    if (filters.channel) params.set("channel", filters.channel);
    setDetail(null); setDetailLoading(true); setDetailError(false);
    Promise.all([
      fetch(`${API}/insights?${params}`, { credentials: "include", signal: controller.signal }),
      fetch(`${API}/forecast?days=28&${params}`, { credentials: "include", signal: controller.signal }),
    ]).then(async ([insightsResponse, forecastResponse]) => {
      if (insightsResponse.status === 401 || forecastResponse.status === 401) {
        onUnauthorized(); throw new Error("unauthorized");
      }
      if (!insightsResponse.ok || !forecastResponse.ok) throw new Error("load");
      const [insights, forecast] = await Promise.all([insightsResponse.json() as Promise<Insights>, forecastResponse.json() as Promise<Forecast>]);
      const product = insights.products.find(item => item.sku_id === selectedSku);
      if (!product || !insights.as_of) throw new Error("missing");
      return { product, asOf: insights.as_of, recentStart: insights.recent_start ?? insights.as_of, forecast };
    }).then(setDetail)
      .catch(error => { if (error.name !== "AbortError" && error.message !== "unauthorized") setDetailError(true); })
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [selectedSku, filters.store, filters.category, filters.channel, dataVersion, detailRetry, onUnauthorized]);

  const clear = () => {
    setDraft(""); setQuery(""); setPage(1);
    searchRef.current?.focus();
  };
  const chart = detail ? [...detail.forecast.history, ...detail.forecast.items] : [];

  return <section className="product-explorer" aria-labelledby="product-explorer-title">
    <div className="section-heading"><div><p className="overline">SKU EXPLORER</p><h2 id="product-explorer-title">{th ? "สำรวจสินค้าทั้งหมด" : "Explore all products"}</h2><p className="muted">{th ? "ค้นหาจากข้อมูลขายจริง แล้วเปิดดูผลพยากรณ์ของสินค้าแต่ละตัว" : "Search recorded sales, then inspect each product forecast."}</p></div></div>
    <div ref={detailRef} className="surface product-workspace">
      {selectedSku ? <>
        <button className="text-link product-back" type="button" onClick={() => { onSelectSku(null); setDetail(null); }}>
          ← {th ? "กลับไปรายการสินค้า" : "Back to products"}
        </button>
        {detailLoading ? <p className="product-state" role="status">{th ? "กำลังโหลดรายละเอียดสินค้า…" : "Loading product detail…"}</p>
          : detailError ? <p className="product-state" role="alert">{th ? "โหลดรายละเอียดไม่สำเร็จ" : "Could not load product detail."} <button className="text-link" type="button" onClick={() => setDetailRetry(value => value + 1)}>{th ? "ลองอีกครั้ง" : "Retry"}</button></p>
          : detail ? <>
            <div className="product-detail-heading"><div><p className="overline">SKU / {detail.product.sku_id}</p><h3>{detail.product.sku_name || detail.product.sku_id}</h3><p className="muted">{detail.product.category || (th ? "ไม่ระบุหมวดหมู่" : "Uncategorized")} · {th ? "ข้อมูลถึง" : "Data through"} {detail.asOf}</p></div><button className="secondary" type="button" onClick={() => onOpenForecast(selectedSku)}>{th ? "ดูในกราฟพยากรณ์" : "Open full forecast"} →</button></div>
            <div className="product-metrics">
              <div><span>{th ? "ขายจริง 28 วัน" : "Actual / 28 days"}</span><strong>{number(detail.product.recent_units, lang)} {th ? "ชิ้น" : "units"}</strong><small>{detail.product.recent_revenue == null ? (th ? "รายได้ไม่พร้อม: ข้อมูลราคาขาด" : "Revenue unavailable: missing price") : money(detail.product.recent_revenue, lang)}</small></div>
              <div><span>{th ? "เทียบ 28 วันก่อน" : "Vs prior 28 days"}</span><strong>{detail.product.change_pct == null ? "—" : `${detail.product.change_pct >= 0 ? "+" : ""}${(detail.product.change_pct * 100).toFixed(0)}%`}</strong><small>{detail.product.history_complete ? (th ? "ข้อมูลรายวันครบ 56 วัน" : "56 daily records complete") : (th ? "ข้อมูลบางวันขาด ไม่ถือเป็นยอดขายศูนย์" : "Missing days are not zero sales")}</small></div>
              <div><span>{th ? "พยากรณ์ 28 วัน" : "Forecast / 28 days"}</span><strong>{detail.product.forecast_revenue == null ? "—" : money(detail.product.forecast_revenue, lang)}</strong><small>{detail.product.forecast_units == null ? (th ? "ไม่มีผลสำหรับชุดข้อมูลนี้" : "No eligible forecast for this product") : `${number(detail.product.forecast_units, lang)} ${th ? "ชิ้น" : "units"}`}</small></div>
            </div>
            <p className="product-evidence" role="status">{th ? "ความครอบคลุม" : "Coverage"}: {detail.product.series_used}/{detail.product.series_total} {th ? "ชุดสาขา/SKU/ช่องทาง" : "store/SKU/channel series"} · {th ? "วิธีพยากรณ์" : "Method"}: {detail.forecast.source === "trained" ? detail.forecast.method === "weekly_naive" ? (th ? "ยอดขายสัปดาห์ก่อน" : "Previous-week baseline") : "XGBoost" : (th ? "ยังไม่มีผลพยากรณ์" : "No forecast")}{modelReview && detail.forecast.source === "trained" ? (th ? " · ผลโมเดลควรตรวจสอบก่อนใช้วางแผน" : " · Review model quality before planning") : ""}</p>
            <div className="product-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chart}><CartesianGrid stroke="var(--grid)" vertical={false}/><XAxis dataKey="date" tickFormatter={value => String(value).slice(5)} minTickGap={26}/><YAxis tickFormatter={value => `${Math.round(Number(value) / 1000)}k`} width={42}/><Tooltip formatter={(value, name) => [money(Number(value ?? 0), lang), name === "actual" ? (th ? "ยอดจริง" : "Actual") : (th ? "พยากรณ์" : "Forecast")]}/><Area dataKey="actual" stroke="var(--teal)" fill="var(--teal)" fillOpacity={0.12} strokeWidth={2} connectNulls={false}/><Area dataKey="forecast" stroke="var(--primary)" fill="var(--primary)" fillOpacity={0.1} strokeWidth={2} strokeDasharray="5 4" connectNulls={false}/></AreaChart></ResponsiveContainer></div>
            <p className="product-chart-note">{th ? "สีเขียว = รายได้จริงย้อนหลัง · สีม่วง = รายได้พยากรณ์ ไม่ใช่ยอดที่เกิดขึ้นแล้ว" : "Teal = past actual revenue · purple = future forecast, not completed sales."}</p>
            <div className="table-scroll product-daily"><table><thead><tr><th>{th ? "วันที่" : "Date"}</th><th>{th ? "ประเภท" : "Type"}</th><th>{th ? "รายได้" : "Revenue"}</th></tr></thead><tbody>{chart.map(point => <tr key={`${point.date}-${point.actual == null ? "forecast" : "actual"}`}><td>{point.date}</td><td>{point.actual == null ? (th ? "พยากรณ์" : "Forecast") : (th ? "ยอดจริง" : "Actual")}</td><td>{money(point.actual ?? point.forecast ?? 0, lang)}</td></tr>)}</tbody></table></div>
          </> : null}
      </> : <>
        <div className="product-controls"><label className="product-search">{th ? "ค้นหา SKU หรือชื่อสินค้า" : "Search SKU or product name"}<span><input ref={searchRef} value={draft} onChange={event => setDraft(event.target.value)} onCompositionStart={() => setComposing(true)} onCompositionEnd={event => { setComposing(false); setDraft(event.currentTarget.value); }} placeholder={th ? "พิมพ์ชื่อหรือรหัสสินค้า" : "Name or SKU"}/>{draft && <button type="button" onClick={clear} aria-label={th ? "ล้างคำค้น" : "Clear search"}>×</button>}</span></label><label>{th ? "เรียงตาม" : "Sort by"}<select value={sort} onChange={event => { setSort(event.target.value); setPage(1); }}><option value="recent_revenue">{th ? "รายได้จริงมากสุด" : "Highest actual revenue"}</option><option value="recent_units">{th ? "จำนวนขายจริงมากสุด" : "Most actual units"}</option><option value="forecast_revenue">{th ? "รายได้พยากรณ์มากสุด" : "Highest forecast revenue"}</option><option value="change_pct">{th ? "เติบโตมากสุด" : "Largest change"}</option><option value="name">{th ? "ชื่อสินค้า A–Z" : "Product name A–Z"}</option></select></label></div>
        <p className="product-scope">{th ? "ข้อมูลจริง 28 วันล่าสุดตามตัวกรองสาขา/หมวดหมู่/ช่องทางด้านบน · ผลพยากรณ์ใช้ได้เฉพาะชุดที่ข้อมูลครบ" : "Actual sales over the latest 28 days under the filters above · forecasts only include eligible series."}</p>
        {catalogLoading ? <p className="product-state" role="status">{th ? "กำลังโหลดรายการสินค้า…" : "Loading products…"}</p>
          : catalogError ? <p className="product-state" role="alert">{th ? "โหลดรายการสินค้าไม่สำเร็จ" : "Could not load products."} <button className="text-link" type="button" onClick={() => setCatalogRetry(value => value + 1)}>{th ? "ลองอีกครั้ง" : "Retry"}</button></p>
          : !catalog?.items.length ? <p className="product-state">{th ? "ไม่พบสินค้าตามเงื่อนไข ลองล้างคำค้นหรือเปลี่ยนตัวกรอง" : "No matching products. Clear search or change filters."}</p>
          : <><p className="product-result-count" role="status">{th ? `พบ ${number(catalog.total, lang)} SKU · ข้อมูลถึง ${catalog.as_of}` : `${number(catalog.total, lang)} SKUs · data through ${catalog.as_of}`}</p><div className="table-scroll product-list"><table><thead><tr><th>{th ? "สินค้า" : "Product"}</th><th>{th ? "ขายจริง 28 วัน" : "Actual / 28 days"}</th><th>{th ? "พยากรณ์ 28 วัน" : "Forecast / 28 days"}</th><th>{th ? "ข้อมูล" : "Evidence"}</th></tr></thead><tbody>{catalog.items.map(item => <tr key={item.sku_id}><td><button type="button" className="product-open" onClick={() => onSelectSku(item.sku_id)}><strong>{item.sku_name || item.sku_id}</strong><small>{item.sku_id}{item.category ? ` · ${item.category}` : ""}</small></button></td><td>{item.recent_revenue == null ? "—" : money(item.recent_revenue, lang)}<small>{number(item.recent_units, lang)} {th ? "ชิ้น" : "units"}</small></td><td>{item.forecast_revenue == null ? "—" : money(item.forecast_revenue, lang)}<small>{item.series_used}/{item.series_total} {th ? "ชุด" : "series"}</small></td><td>{item.history_complete ? (th ? "ครบ 56 วัน" : "56 days complete") : (th ? "ข้อมูลบางวันขาด" : "Missing days")}</td></tr>)}</tbody></table></div><div className="product-pagination"><span>{th ? `รายการ ${(catalog.page - 1) * catalog.page_size + 1}–${Math.min(catalog.page * catalog.page_size, catalog.total)} จาก ${catalog.total}` : `Items ${(catalog.page - 1) * catalog.page_size + 1}–${Math.min(catalog.page * catalog.page_size, catalog.total)} of ${catalog.total}`}</span><div><button className="secondary" type="button" disabled={page === 1} onClick={() => setPage(value => value - 1)}>{th ? "ก่อนหน้า" : "Previous"}</button><button className="secondary" type="button" disabled={page * catalog.page_size >= catalog.total} onClick={() => setPage(value => value + 1)}>{th ? "ถัดไป" : "Next"}</button></div></div></>}
      </>}
    </div>
  </section>;
}
