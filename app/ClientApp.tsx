"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { UiIcon } from "./UiIcon";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
type User = { id: number; name: string; email: string; role: string; organization: string };
type Score = { wape: number | null; baseline_wape: number | null; mae: number; rmse: number; test_rows: number };
type Metrics = Partial<Score> & { train_rows?: number; backtests?: (Score & { days: number; folds: number })[]; by_store?: { id: string; wape: number | null; test_rows: number }[]; by_sku?: { id: string; wape: number | null; test_rows: number }[]; error?: string };
type Summary = { record_count: number; store_count: number; sku_count: number; latest_date: string | null; total_revenue: number | null; price_missing_count: number; model: { status: string; created_at: string; metrics: Metrics } | null; stores: string[]; skus: string[]; categories: string[]; channels: string[] };
type Point = { date: string; actual?: number; forecast?: number };
type Forecast = { source: string; items: Point[]; history: Point[]; coverage?: { series_used: number; series_total: number } };
type View = "overview" | "forecast" | "import" | "model" | "settings";
const emptySummary: Summary = { record_count: 0, store_count: 0, sku_count: 0, latest_date: null, total_revenue: 0, price_missing_count: 0, model: null, stores: [], skus: [], categories: [], channels: [] };
const nav: { key: View; th: string; en: string; thShort: string; enShort: string; icon: string }[] = [
  { key: "overview", th: "ภาพรวมยอดขาย", en: "Overview", thShort: "ภาพรวม", enShort: "Overview", icon: "▦" },
  { key: "forecast", th: "การพยากรณ์", en: "Forecast", thShort: "พยากรณ์", enShort: "Forecast", icon: "⌁" },
  { key: "import", th: "นำเข้าข้อมูล", en: "Import data", thShort: "นำเข้า", enShort: "Import", icon: "↥" },
  { key: "model", th: "ประสิทธิภาพโมเดล", en: "Model performance", thShort: "โมเดล", enShort: "Model", icon: "◷" },
  { key: "settings", th: "ตั้งค่า", en: "Settings", thShort: "ตั้งค่า", enShort: "Settings", icon: "⚙" },
];

async function api(path: string, options: RequestInit = {}) {
  const response = await fetch(`${API}${path}`, { credentials: "include", ...options });
  const body = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw Object.assign(new Error(typeof body?.detail === "string" ? body.detail : `เกิดข้อผิดพลาด (${response.status})`), { status: response.status });
  return body;
}
const money = (value: number) => `฿${new Intl.NumberFormat("th-TH", { maximumFractionDigits: 0 }).format(value)}`;
const count = (value: number) => new Intl.NumberFormat("th-TH").format(value);
const percent = (value?: number | null) => value == null ? "—" : `${(value * 100).toFixed(2)}%`;

export default function ClientApp() {
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [view, setView] = useState<View>("overview");
  const [lang, setLang] = useState<"th" | "en">("th");
  const [dark, setDark] = useState(false);
  const [summary, setSummary] = useState<Summary>(emptySummary);
  const [forecast, setForecast] = useState<Forecast>({ source: "empty", items: [], history: [] });
  const [days, setDays] = useState(28);
  const [store, setStore] = useState("");
  const [sku, setSku] = useState("");
  const [category, setCategory] = useState("");
  const [channel, setChannel] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [validation, setValidation] = useState<{ rows: number; missing_days: number; date_range: { from: string; to: string } } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const th = lang === "th";

  useEffect(() => {
    try { setDark(localStorage.getItem("projecta-theme") === "dark"); setLang(localStorage.getItem("projecta-lang") === "en" ? "en" : "th"); } catch { /* storage unavailable */ }
    api("/auth/me").then(setUser).catch(() => setUser(null)).finally(() => setAuthLoading(false));
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = dark ? "dark" : "light"; try { localStorage.setItem("projecta-theme", dark ? "dark" : "light"); } catch { /* storage unavailable */ } }, [dark]);
  useEffect(() => { document.documentElement.lang = lang; try { localStorage.setItem("projecta-lang", lang); } catch { /* storage unavailable */ } }, [lang]);
  useEffect(() => { window.scrollTo(0, 0); document.title = `${nav.find(item => item.key === view)?.[lang === "th" ? "th" : "en"] ?? "ProjectA_1"} | ProjectA_1`; }, [view, lang]);

  const refresh = useCallback(async () => {
    if (!user) return;
    setLoading(true); setError("");
    try { const next = await api("/summary") as Summary; setSummary(next); }
    catch (failure) { if ((failure as { status?: number }).status === 401) setUser(null); else setError(failure instanceof Error ? failure.message : "โหลดข้อมูลไม่สำเร็จ"); }
    finally { setLoading(false); }
  }, [user]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!user) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ days: String(days) });
    if (store) params.set("store_id", store); if (sku) params.set("sku_id", sku); if (category) params.set("category", category); if (channel) params.set("channel", channel);
    fetch(`${API}/forecast?${params}`, { credentials: "include", signal: controller.signal }).then(r => r.ok ? r.json() : Promise.reject(new Error("โหลดผลพยากรณ์ไม่สำเร็จ"))).then(setForecast).catch(e => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [user, days, store, sku, category, channel, summary.model]);

  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setAuthError("");
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") ?? "").trim(); const password = String(form.get("password") ?? "");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return setAuthError(th ? "กรุณากรอกอีเมลให้ถูกต้อง" : "Enter a valid email address.");
    if (authMode === "register" && password.length < 10) return setAuthError(th ? "รหัสผ่านต้องมีอย่างน้อย 10 ตัวอักษร" : "Use at least 10 characters.");
    const payload: Record<string, string> = { email, password };
    if (authMode === "register") { payload.organization_name = String(form.get("organization_name") ?? "").trim(); payload.display_name = String(form.get("display_name") ?? "").trim(); if (payload.organization_name.length < 2 || payload.display_name.length < 2) return setAuthError(th ? "กรุณากรอกชื่อและชื่อองค์กรอย่างน้อย 2 ตัวอักษร" : "Name and organization need at least 2 characters."); }
    setAuthBusy(true);
    try { const signedIn = await api(`/auth/${authMode === "login" ? "login" : "register"}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }) as User; setUser(signedIn); setView("overview"); }
    catch (failure) { setAuthError(failure instanceof Error ? failure.message : "เข้าสู่ระบบไม่สำเร็จ"); }
    finally { setAuthBusy(false); }
  }
  async function logout() { await api("/auth/logout", { method: "POST" }).catch(() => undefined); setUser(null); setSummary(emptySummary); setForecast({ source: "empty", items: [], history: [] }); setNotice(""); }
  async function validateFile(file: File) {
    setError(""); setValidation(null); setSelectedFile(file);
    if (!/\.(csv|xlsx)$/i.test(file.name) || file.size > 20_000_000 || file.size === 0) return setError(th ? "เลือกไฟล์ CSV/XLSX ขนาดไม่เกิน 20 MB" : "Choose a CSV/XLSX file under 20 MB.");
    setBusy(true);
    try { const form = new FormData(); form.append("file", file); setValidation(await api("/uploads/validate", { method: "POST", body: form })); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "ตรวจไฟล์ไม่สำเร็จ"); }
    finally { setBusy(false); }
  }
  async function importFile() {
    if (!selectedFile || !validation) return;
    setBusy(true); setError("");
    try { const form = new FormData(); form.append("file", selectedFile); const result = await api("/uploads/import", { method: "POST", body: form }); setNotice(th ? `นำเข้า ${count(result.imported)} แถวสำเร็จ` : `Imported ${count(result.imported)} rows.`); setSelectedFile(null); setValidation(null); if (fileRef.current) fileRef.current.value = ""; await refresh(); setView("overview"); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "นำเข้าไม่สำเร็จ"); }
    finally { setBusy(false); }
  }
  async function train() {
    setBusy(true); setError("");
    try { const result = await api("/models/train", { method: "POST" }); if (result.status !== "completed") throw new Error(result.message ?? "เทรนโมเดลไม่สำเร็จ"); setNotice(th ? "เทรนโมเดลสำเร็จ ผลพยากรณ์พร้อมดูแล้ว" : "Model trained. Forecast is ready."); await refresh(); setView("model"); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "เทรนโมเดลไม่สำเร็จ"); }
    finally { setBusy(false); }
  }
  function sample() {
    const lines = ["date,store_id,store_name,sku_id,sku_name,category,channel,quantity_sold,unit_price,promotion_flag"];
    const items = [["BKK01", "Bangkok", "FD001", "Coffee", "Food", 189], ["BKK01", "Bangkok", "FD002", "Tea", "Food", 95], ["CNX01", "Chiang Mai", "HM001", "Storage Box", "Home", 240], ["CNX01", "Chiang Mai", "HB001", "Board Game", "Hobbies", 590]] as const;
    for (let day = 0; day < 150; day++) { const date = new Date(Date.UTC(2026, 0, day + 1)).toISOString().slice(0, 10); items.forEach((item, index) => { const qty = Math.max(4, Math.round(18 + index * 5 + Math.sin(day / 7 + index) * 6 + (day % 7 === 5 ? 8 : 0))); lines.push(`${date},${item[0]},${item[1]},${item[2]},${item[3]},${item[4]},in_store,${qty},${item[5]},${day % 21 === 0 ? 1 : 0}`); }); }
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = "projecta-sample-sales.csv"; link.click(); URL.revokeObjectURL(url);
  }
  async function exportCsv() {
    setError(""); try { const response = await fetch(`${API}/export`, { credentials: "include" }); if (!response.ok) throw new Error("ดาวน์โหลดข้อมูลไม่สำเร็จ"); const url = URL.createObjectURL(await response.blob()); const link = document.createElement("a"); link.href = url; link.download = "projecta-sales.csv"; link.click(); URL.revokeObjectURL(url); } catch (failure) { setError(failure instanceof Error ? failure.message : "ดาวน์โหลดไม่สำเร็จ"); }
  }

  const chart = useMemo(() => [...forecast.history, ...forecast.items], [forecast]);
  const totalForecast = forecast.items.reduce((sum, point) => sum + (point.forecast ?? 0), 0);
  const forecastReady = forecast.source === "trained" && forecast.items.length > 0;
  const modelReady = summary.model?.status === "completed";
  const modelMissing = summary.model?.status === "missing";
  const modelFailed = summary.model?.status === "failed";
  const modelNeedsRetrain = summary.model?.status === "needs_retrain";
  const modelInvalid = summary.price_missing_count > 0;
  const modelStatusLabel = modelInvalid ? (th ? "● ข้อมูลขาดราคา" : "● Missing prices") : modelReady ? (th ? "● พร้อมใช้งาน" : "● Ready") : modelNeedsRetrain ? (th ? "● ต้องเทรนใหม่" : "● Retrain required") : modelMissing ? (th ? "● ไฟล์โมเดลไม่พร้อม" : "● Model file unavailable") : modelFailed ? (th ? "● เทรนไม่สำเร็จ" : "● Training failed") : (th ? "○ ยังไม่เทรน" : "○ Not trained");
  const activeTitle = nav.find(item => item.key === view)?.[th ? "th" : "en"] ?? "";
  if (authLoading) return <div className="boot" role="status">ProjectA_1 · {th ? "กำลังตรวจสอบบัญชี…" : "Checking session…"}</div>;
  if (!user) return <main className="auth-layout"><section className="auth-story"><span className="brandmark">PA</span><p className="overline">PROJECTA_1 / SALES INTELLIGENCE</p><h1>{th ? "มองเห็นยอดขาย\nก่อนวันพรุ่งนี้" : "See tomorrow’s sales\ntoday"}</h1><p>{th ? "นำเข้าข้อมูลขาย ประเมินโมเดล และดูแนวโน้มในที่เดียว" : "Import sales, measure model quality, and explore trends in one place."}</p><div className="auth-graphic"><span>ACTUAL</span><div className="auth-bars">{[36,48,42,63,54,71,62,84,74,88,79,96].map((height,i) => <i key={i} style={{ height: `${height}%` }}/>)}</div><span>FORECAST ↗</span></div></section><section className="auth-panel"><div className="auth-tools"><button type="button" className="quiet" onClick={() => setLang(th ? "en" : "th")}>{th ? "EN" : "ไทย"}</button><button type="button" className="quiet" onClick={() => setDark(!dark)} aria-label={th ? "สลับธีม" : "Toggle theme"}>{dark ? "☀" : "☾"}</button></div><div className="auth-card"><p className="overline">{authMode === "login" ? "WELCOME BACK" : "CREATE WORKSPACE"}</p><h2>{authMode === "login" ? (th ? "เข้าสู่ระบบ" : "Sign in") : (th ? "สร้างบัญชีเจ้าของธุรกิจ" : "Create owner account")}</h2><p className="muted">{authMode === "login" ? (th ? "เข้าใช้ข้อมูลยอดขายขององค์กรคุณ" : "Access your organization’s sales workspace.") : (th ? "เริ่มด้วยชื่อองค์กรและอีเมลของคุณ" : "Start with your organization and email.")}</p><form noValidate onSubmit={authenticate}>{authMode === "register" && <><label>{th ? "ชื่อองค์กร" : "Organization"}<input name="organization_name" autoComplete="organization" placeholder="Example Co." /></label><label>{th ? "ชื่อของคุณ" : "Your name"}<input name="display_name" autoComplete="name" placeholder="Business Owner" /></label></>}<label>{th ? "อีเมล" : "Email"}<input name="email" type="email" autoComplete="email" placeholder="you@company.com" /></label><label>{th ? "รหัสผ่าน" : "Password"}<span className="password-field"><input name="password" type={showPassword ? "text" : "password"} autoComplete={authMode === "login" ? "current-password" : "new-password"} placeholder={authMode === "register" ? (th ? "อย่างน้อย 10 ตัวอักษร" : "At least 10 characters") : "••••••••••"}/><button type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? (th ? "ซ่อนรหัสผ่าน" : "Hide password") : (th ? "แสดงรหัสผ่าน" : "Show password")}>{showPassword ? "ซ่อน" : "แสดง"}</button></span></label>{authError && <p className="form-error" role="alert">{authError}</p>}<button className="primary wide" type="submit" disabled={authBusy}>{authBusy ? (th ? "กำลังดำเนินการ…" : "Working…") : authMode === "login" ? (th ? "เข้าสู่ระบบ" : "Sign in") : (th ? "สร้างบัญชี" : "Create account")}</button></form><button type="button" className="switch-auth" onClick={() => { setAuthMode(authMode === "login" ? "register" : "login"); setAuthError(""); }}>{authMode === "login" ? (th ? "ยังไม่มีบัญชี? สร้างบัญชี" : "New here? Create an account") : (th ? "มีบัญชีแล้ว? เข้าสู่ระบบ" : "Already have an account? Sign in")}</button></div></section></main>;

  return <main className="app-shell"><aside className="app-sidebar"><div className="app-brand"><span className="brandmark">PA</span><span><strong>ProjectA_1</strong><small>Sales intelligence</small></span></div><div className="sidebar-label">WORKSPACE</div><nav aria-label={th ? "เมนูหลัก" : "Main navigation"}>{nav.map(item => <button key={item.key} type="button" className={view === item.key ? "selected" : ""} onClick={() => { setView(item.key); setError(""); }} aria-current={view === item.key ? "page" : undefined} aria-label={th ? item.th : item.en}><span className="nav-icon"><UiIcon name={item.key}/></span><span className="nav-full">{th ? item.th : item.en}</span><span className="nav-short">{th ? item.thShort : item.enShort}</span></button>)}</nav><div className="sidebar-footer"><div className="user-avatar">{user.name.slice(0,1).toUpperCase()}</div><div><strong>{user.name}</strong><small>{user.organization}</small></div><button type="button" className="logout-icon" onClick={logout} aria-label={th ? "ออกจากระบบ" : "Sign out"}><UiIcon name="logout"/></button></div></aside>
    <section className="app-main"><header className="topbar"><div className="breadcrumb">PROJECTA_1 <span>/</span> {activeTitle}</div><div className="top-actions"><button type="button" onClick={() => setLang(th ? "en" : "th")}>{th ? "EN" : "ไทย"}</button><button type="button" onClick={() => setDark(!dark)} aria-label={th ? "สลับธีม" : "Toggle theme"}>{dark ? "☀" : "☾"}</button><span className="top-user">{user.name}</span></div></header><div className="page-content"><div className="page-heading"><div><p className="overline">{user.organization.toUpperCase()}</p><h1>{activeTitle}</h1><p className="muted">{view === "overview" ? (th ? "ข้อมูลยอดขายและความพร้อมของโมเดลในที่เดียว" : "Sales data and model readiness at a glance.") : view === "forecast" ? (th ? "สำรวจแนวโน้มจากข้อมูลขององค์กรคุณ" : "Explore trends from your organization’s data.") : view === "import" ? (th ? "ตรวจข้อมูลก่อนนำเข้าเสมอ" : "Validate your data before importing.") : view === "model" ? (th ? "วัดผลโมเดลจากช่วงข้อมูลที่กันไว้ทดสอบ" : "Evaluate the model on held-out dates.") : (th ? "บัญชีและการตั้งค่าแสดงผล" : "Account and display preferences.")}</p></div>{(view === "overview" || view === "forecast" || view === "model") && user.role !== "analyst" && <button className="primary" type="button" onClick={() => setView("import")}>＋ {th ? "นำเข้าข้อมูล" : "Import data"}</button>}</div>
      {notice && <div className="banner success" role="status">✓ {notice}<button type="button" onClick={() => setNotice("")} aria-label={th ? "ปิดข้อความ" : "Dismiss"}>×</button></div>}{error && <div className="banner error" role="alert">{error}<button type="button" onClick={() => setError("")} aria-label={th ? "ปิดข้อผิดพลาด" : "Dismiss error"}>×</button></div>}
      {view === "overview" && <>
        <div className="stat-grid">
          <Stat label={th ? "ยอดขายรวมในข้อมูล" : "Recorded revenue"} value={summary.record_count && summary.total_revenue != null ? money(summary.total_revenue) : "—"} detail={modelInvalid ? (th ? "บางแถวไม่มีราคา กรุณานำเข้าใหม่" : "Some rows lack prices; re-import data") : summary.latest_date ? `${th ? "ข้อมูลถึง" : "Through"} ${summary.latest_date}` : (th ? "ยังไม่มีข้อมูล" : "No data yet")} icon="฿"/>
          <Stat label={th ? "สาขา" : "Stores"} value={count(summary.store_count)} detail={th ? "ในชุดข้อมูลปัจจุบัน" : "In current dataset"} icon="▦"/>
          <Stat label={th ? "สินค้า / SKU" : "Products / SKUs"} value={count(summary.sku_count)} detail={th ? "ในชุดข้อมูลปัจจุบัน" : "In current dataset"} icon="◇"/>
          <Stat label={th ? "คาดการณ์ 28 วัน" : "28-day forecast"} value={forecastReady ? money(totalForecast) : "—"} detail={forecastReady ? "XGBoost" : (th ? "เทรนโมเดลเพื่อดูผล" : "Train a model to see results")} icon="↗"/>
        </div>
        <div className="content-grid">
          <section className="surface chart-surface">
            <div className="section-heading"><div><p className="overline">SALES SIGNAL</p><h2>{th ? "แนวโน้มยอดขาย" : "Sales trend"}</h2></div><button className="text-link" type="button" onClick={() => setView("forecast")}>{th ? "ดูการพยากรณ์" : "Explore forecast"} →</button></div>
            {chart.length ? <TrendChart data={chart}/>: <Empty title={th ? "ยังไม่มีกราฟยอดขาย" : "No sales chart yet"} text={th ? "อัปโหลด CSV หรือ XLSX เพื่อเริ่มดูยอดขายจริง" : "Upload CSV or XLSX to start exploring sales."} action={th ? "ไปหน้านำเข้าข้อมูล" : "Go to import"} onAction={() => setView("import")}/>}
          </section>
          <section className="surface model-surface">
            <p className="overline">MODEL HEALTH</p><h2>{th ? "สถานะโมเดล" : "Model status"}</h2>
            <div className={`model-badge ${modelReady ? "ready" : "waiting"}`}>{modelStatusLabel}</div>
            {modelMissing && <p className="model-warning">{th ? "ไฟล์โมเดลไม่พร้อม กรุณาเทรนใหม่" : "The model file is unavailable. Please retrain."}</p>}
            <div className="model-detail"><span>WAPE · 28 {th ? "วัน" : "days"}</span><strong>{modelReady ? percent(summary.model?.metrics.wape) : "—"}</strong></div>
            <div className="model-detail"><span>{th ? "ข้อมูลฝึก" : "Training rows"}</span><strong>{summary.model?.metrics.train_rows ? count(summary.model.metrics.train_rows) : "—"}</strong></div>
            <div className="model-detail"><span>{th ? "เทรนล่าสุด" : "Last trained"}</span><strong>{summary.model?.created_at ? new Date(summary.model.created_at).toLocaleDateString(th ? "th-TH" : "en-US") : "—"}</strong></div>
            <button className="secondary wide" type="button" onClick={() => setView("model")}>{th ? "ดูประสิทธิภาพโมเดล" : "View model performance"} →</button>
          </section>
        </div>
        <div className="quick-row"><div><strong>{th ? "ลำดับถัดไป" : "Next step"}</strong><p>{summary.record_count === 0 ? (th ? "ดาวน์โหลดไฟล์ตัวอย่าง แล้วนำเข้าข้อมูลเพื่อเริ่มต้น" : "Download the sample file and import data to begin.") : modelInvalid ? (th ? "ข้อมูลบางแถวไม่มีราคา กรุณานำเข้าไฟล์ใหม่" : "Some rows lack prices. Import a corrected file.") : modelMissing ? (th ? "ไฟล์โมเดลไม่พร้อม ไปหน้าโมเดลเพื่อเทรนใหม่" : "The model file is unavailable. Retrain on the model page.") : !modelReady ? (th ? "ข้อมูลพร้อมแล้ว เทรนโมเดลเพื่อดูผลพยากรณ์" : "Data is ready. Train the model to see a forecast.") : (th ? "ผลพยากรณ์พร้อมสำรวจตามสาขาและหมวดหมู่" : "Explore the forecast by store and category.")}</p></div><button type="button" onClick={() => setView(summary.record_count === 0 || modelInvalid ? "import" : modelReady ? "forecast" : "model")}>{th ? "ไปต่อ" : "Continue"} →</button></div>
      </>}
      {view === "forecast" && <>
        <div className="filter-bar">
          <label>{th ? "ช่วงพยากรณ์" : "Horizon"}<select value={days} onChange={e => setDays(Number(e.target.value))}><option value={7}>7 {th ? "วัน" : "days"}</option><option value={14}>14 {th ? "วัน" : "days"}</option><option value={28}>28 {th ? "วัน" : "days"}</option></select></label>
          <label>{th ? "สาขา" : "Store"}<select value={store} onChange={e => setStore(e.target.value)}><option value="">{th ? "ทุกสาขา" : "All stores"}</option>{summary.stores.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          <label>SKU<select value={sku} onChange={e => setSku(e.target.value)}><option value="">{th ? "ทุกสินค้า" : "All SKUs"}</option>{summary.skus.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          <label>{th ? "หมวดหมู่" : "Category"}<select value={category} onChange={e => setCategory(e.target.value)}><option value="">{th ? "ทุกหมวดหมู่" : "All categories"}</option>{summary.categories.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          <label>{th ? "ช่องทาง" : "Channel"}<select value={channel} onChange={e => setChannel(e.target.value)}><option value="">{th ? "ทุกช่องทาง" : "All channels"}</option>{summary.channels.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
        </div>
        <section className="surface wide-surface">
          <div className="section-heading">
            <div>
              <p className="overline">{forecastReady ? `FORECAST / ${days} DAYS` : "SALES HISTORY"}</p>
              <h2>{forecastReady ? money(totalForecast) : forecast.history.length ? (th ? "ยอดขายย้อนหลัง" : "Historical sales") : (th ? "ยังไม่มีผลพยากรณ์" : "No forecast yet")}</h2>
              <p className="muted">{forecastReady ? (th ? "ยอดขายคาดการณ์รวมในช่วงที่เลือก" : "Total projected revenue for the selected period") : forecast.history.length ? (th ? "กราฟสีเขียวแสดงยอดขายจริงย้อนหลัง ยังไม่มีเส้นพยากรณ์" : "The teal line shows actual sales only; no forecast is available.") : (th ? "ปรับตัวกรองหรือนำเข้าข้อมูลเพื่อเริ่มต้น" : "Adjust filters or import sales data to begin.")}</p>
            </div>
            {forecastReady && <span className="model-badge ready">XGBoost</span>}
          </div>
          {!forecastReady && forecast.history.length > 0 && <div className="forecast-guidance" role="status">
            <span>{modelNeedsRetrain ? (th ? "โมเดลเดิมใช้วิธีประเมินเก่า กรุณาเทรนใหม่" : "The older model used the previous evaluation method. Retrain it.") : modelMissing ? (th ? "ไฟล์โมเดลไม่พร้อม ต้องเทรนใหม่จึงจะพยากรณ์ได้" : "The model file is unavailable. Retrain to generate a forecast.") : modelFailed ? (th ? "การเทรนครั้งล่าสุดไม่สำเร็จ กรุณาตรวจสอบและเทรนใหม่" : "The last training failed. Review it and train again.") : (th ? "มีข้อมูลยอดขายแล้ว เทรนโมเดลเพื่อสร้างผลพยากรณ์" : "Sales data is ready. Train a model to generate a forecast.")}</span>
            <button type="button" className="secondary" onClick={() => setView("model")}>{th ? "ไปหน้าโมเดล" : "Go to model"} →</button>
          </div>}
          {forecast.source === "needs_price" && <div className="forecast-guidance" role="alert"><span>{th ? "ข้อมูลบางแถวไม่มีราคา กรุณานำเข้าไฟล์ที่มี unit_price ครบก่อนพยากรณ์เป็นบาท" : "Some rows lack prices. Re-import complete unit_price values before forecasting revenue."}</span><button type="button" className="secondary" onClick={() => setView("import")}>{th ? "นำเข้าข้อมูล" : "Import data"} →</button></div>}
          {forecastReady && forecast.coverage && forecast.coverage.series_used < forecast.coverage.series_total && <p className="model-warning" role="status">{th ? `พยากรณ์ได้ ${count(forecast.coverage.series_used)} จาก ${count(forecast.coverage.series_total)} ชุดสาขา/SKU/ช่องทาง; ชุดที่ข้อมูลล่าสุดไม่ครบ 28 วันไม่ถูกรวม` : `Forecast includes ${count(forecast.coverage.series_used)} of ${count(forecast.coverage.series_total)} store/SKU/channel series; series without 28 recent observed days are excluded.`}</p>}
          {chart.length ? <TrendChart data={chart}/>: <Empty title={modelInvalid ? (th ? "ข้อมูลราคายังไม่ครบ" : "Price data is incomplete") : summary.record_count ? (th ? "ไม่พบข้อมูลตามตัวกรอง" : "No data for these filters") : (th ? "ยังไม่มีข้อมูลยอดขาย" : "No sales data yet")} text={modelInvalid ? (th ? "นำเข้าไฟล์ที่มี unit_price ทุกแถว" : "Import a file with unit_price on every row.") : summary.record_count ? (th ? "ลองเลือกสาขา สินค้า หรือช่องทางอื่น" : "Try another store, SKU, or channel.") : (th ? "เริ่มจากนำเข้าข้อมูลยอดขายอย่างน้อย 90 วัน" : "Start by importing at least 90 days of sales.")} action={th ? "นำเข้าข้อมูล" : "Import data"} onAction={() => setView("import")}/>}
        </section>
        {forecastReady && <section className="surface table-surface"><h2>{th ? "ผลรายวัน" : "Daily forecast"}</h2><div className="table-scroll"><table><thead><tr><th>{th ? "วันที่" : "Date"}</th><th>{th ? "ยอดขายคาดการณ์" : "Forecast revenue"}</th></tr></thead><tbody>{forecast.items.map(point => <tr key={point.date}><td>{point.date}</td><td>{money(point.forecast ?? 0)}</td></tr>)}</tbody></table></div></section>}
      </>}
      {view === "import" && <div className="content-grid import-grid"><section className="surface"><p className="overline">DATA INTAKE</p><h2>{th ? "นำเข้าข้อมูลยอดขาย" : "Import sales data"}</h2><p className="muted">{th ? "CSV หรือ XLSX สูงสุด 20 MB · ต้องมี date, store_id, sku_id, quantity_sold, unit_price · อย่างน้อย 90 วัน" : "CSV or XLSX up to 20 MB · required: date, store_id, sku_id, quantity_sold, unit_price · at least 90 days"}</p><div className="upload-zone"><span className="upload-symbol">↥</span><strong>{selectedFile?.name ?? (th ? "เลือกไฟล์ยอดขาย" : "Choose a sales file")}</strong><p>{selectedFile ? `${(selectedFile.size / 1024).toFixed(0)} KB` : (th ? "ระบบจะตรวจรูปแบบและข้อมูลส่วนบุคคลก่อนนำเข้า" : "Format and personal data are checked first.")}</p><input ref={fileRef} type="file" accept=".csv,.xlsx" onChange={(e: ChangeEvent<HTMLInputElement>) => { const file = e.target.files?.[0]; if (file) void validateFile(file); }}/><button className="secondary" type="button" onClick={() => fileRef.current?.click()} disabled={busy}>{th ? "เลือกไฟล์" : "Browse files"}</button></div>{validation && <div className="validation"><strong>✓ {th ? "ตรวจไฟล์ผ่าน" : "File validated"}</strong><p>{count(validation.rows)} {th ? "แถว" : "rows"} · {validation.date_range.from} — {validation.date_range.to}</p>{validation.missing_days > 0 && <p className="import-warning" role="status">{th ? `พบวันที่ไม่มีข้อมูล ${count(validation.missing_days)} วันตามชุดสาขา/SKU/ช่องทาง ระบบจะไม่ถือว่าเป็นยอดขายศูนย์` : `Found ${count(validation.missing_days)} missing calendar days across store/SKU/channel series. They will not be treated as zero sales.`}</p>}<p>{th ? "การนำเข้าจะใช้ข้อมูลชุดใหม่นี้แทนชุดเดิมขององค์กร" : "Import replaces your organization’s current dataset."}</p><button className="primary" type="button" disabled={busy} onClick={importFile}>{busy ? (th ? "กำลังนำเข้า…" : "Importing…") : (th ? "ยืนยันนำเข้า" : "Confirm import")}</button></div>}</section><section className="surface help-surface"><p className="overline">FILE GUIDE</p><h2>{th ? "เตรียมไฟล์อย่างไร" : "Prepare your file"}</h2><ol><li>{th ? "หนึ่งแถวต่อวัน สาขา สินค้า และช่องทาง; วันที่ขายศูนย์ให้ใส่ 0" : "One row per date, store, SKU, and channel; record zero-sales days as 0."}</li><li>{th ? "ยอดขายและราคาต้องไม่ติดลบ และทุกแถวต้องมีราคา" : "Sales quantity and price cannot be negative; every row needs a price."}</li><li>{th ? "ลบชื่อ อีเมล เบอร์โทร หรือที่อยู่ลูกค้าก่อนอัปโหลด" : "Remove customer names, email, phone, and address before upload."}</li></ol><button className="secondary wide" type="button" onClick={sample}>↓ {th ? "ดาวน์โหลดข้อมูลตัวอย่าง 150 วัน" : "Download 150-day sample"}</button>{summary.record_count > 0 && <button className="text-link export-link" type="button" onClick={exportCsv}>↓ {th ? "ส่งออกข้อมูลปัจจุบันเป็น CSV" : "Export current data as CSV"}</button>}</section></div>}
      {view === "model" && <div className="content-grid model-grid">
        <section className="surface">
          <p className="overline">MODEL TRAINING</p><h2>XGBoost</h2>
          <p className="muted">{th ? "โมเดลเรียนรู้ยอดขายย้อนหลัง วันในสัปดาห์ เดือน และราคา" : "The model learns from lagged sales, weekday, month, and price."}</p>
          <div className="model-callout"><span className={`model-badge ${modelReady ? "ready" : "waiting"}`}>{modelStatusLabel}</span><p>{modelInvalid ? (th ? "ข้อมูลบางแถวไม่มีราคา กรุณานำเข้าไฟล์ที่มี unit_price ครบ" : "Some rows lack prices. Re-import complete unit_price values.") : modelMissing ? (th ? "ไฟล์โมเดลที่เคยเทรนไม่อยู่ในระบบ กรุณาเทรนใหม่ ข้อมูลยอดขายยังอยู่" : "The trained model file is missing. Retrain it; your sales data is still available.") : summary.model?.metrics.error ?? (modelReady ? (th ? "ประเมินย้อนหลังหลายจุดตัดเวลา แล้วฝึกใหม่ด้วยข้อมูลทั้งหมด" : "Evaluated at rolling historical cutoffs, then trained on all available dates.") : (th ? "นำเข้าข้อมูลอย่างน้อย 90 วัน แล้วกดเทรน" : "Import at least 90 days, then train."))}</p></div>
          {user.role !== "analyst" && <button className="primary" type="button" onClick={train} disabled={busy || summary.record_count === 0 || modelInvalid}>{busy ? (th ? "กำลังเทรน…" : "Training…") : (th ? "เทรนโมเดลใหม่" : "Train model")}</button>}
        </section>
        <section className="surface"><p className="overline">ROLLING BACKTEST</p><h2>{th ? "ประสิทธิภาพตามช่วงเวลา" : "Performance by horizon"}</h2><p className="muted">{th ? "WAPE จากการพยากรณ์ต่อเนื่อง 7/14/28 วัน เทียบกับการใช้ยอดขาย 7 วันก่อน" : "Recursive 7/14/28-day WAPE versus the previous-week baseline."}</p>{summary.model?.metrics.backtests?.length ? <div className="table-scroll evaluation-table"><table><thead><tr><th>{th ? "ช่วง" : "Horizon"}</th><th>WAPE</th><th>Baseline</th><th>{th ? "รอบ" : "Folds"}</th></tr></thead><tbody>{summary.model.metrics.backtests.map(item => <tr key={item.days}><td>{item.days} {th ? "วัน" : "days"}</td><td>{percent(item.wape)}</td><td>{percent(item.baseline_wape)}</td><td>{item.folds}</td></tr>)}</tbody></table></div> : <p className="model-warning">{modelReady ? (th ? "โมเดลเดิมยังไม่มีผลประเมินหลายช่วง กรุณาเทรนใหม่" : "This older model has no rolling backtest. Retrain to see it.") : (th ? "เทรนโมเดลเพื่อดูผลประเมิน" : "Train a model to see its evaluation.")}</p>}<div className="metric-list"><MetricRow label={th ? "MAE · 28 วัน (บาท/แถว)" : "MAE · 28 days (THB/row)"} value={summary.model?.metrics.mae != null ? money(summary.model.metrics.mae) : "—"}/><MetricRow label={th ? "RMSE · 28 วัน (บาท/แถว)" : "RMSE · 28 days (THB/row)"} value={summary.model?.metrics.rmse != null ? money(summary.model.metrics.rmse) : "—"}/><MetricRow label={th ? "แถวทดสอบ · 28 วัน" : "Test rows · 28 days"} value={summary.model?.metrics.test_rows ? count(summary.model.metrics.test_rows) : "—"}/></div></section>
        {summary.model?.metrics.backtests?.length ? <section className="surface backtest-segments"><p className="overline">SEGMENT CHECK</p><h2>{th ? "จุดที่ควรตรวจเพิ่ม · 28 วัน" : "Segments to review · 28 days"}</h2><p className="muted">{th ? "เรียงจาก WAPE สูงสุด แสดงเฉพาะสาขาและ SKU ที่มีข้อมูลทดสอบ" : "Highest WAPE first; only stores and SKUs with evaluated data are shown."}</p><div className="segment-grid"><SegmentTable title={th ? "สาขา" : "Stores"} rows={summary.model.metrics.by_store ?? []} th={th}/><SegmentTable title="SKU" rows={summary.model.metrics.by_sku ?? []} th={th}/></div></section> : null}
      </div>}
      {view === "settings" && <div className="content-grid"><section className="surface"><p className="overline">ACCOUNT</p><h2>{th ? "บัญชีของคุณ" : "Your account"}</h2><div className="metric-list"><MetricRow label={th ? "ชื่อ" : "Name"} value={user.name}/><MetricRow label={th ? "อีเมล" : "Email"} value={user.email}/><MetricRow label={th ? "องค์กร" : "Organization"} value={user.organization}/><MetricRow label={th ? "บทบาท" : "Role"} value={user.role}/></div><button className="secondary" type="button" onClick={logout}>{th ? "ออกจากระบบ" : "Sign out"}</button></section><section className="surface"><p className="overline">PREFERENCES</p><h2>{th ? "การแสดงผล" : "Display"}</h2><div className="setting-row"><span>{th ? "ภาษา" : "Language"}</span><button type="button" onClick={() => setLang(th ? "en" : "th")}>{th ? "ไทย → English" : "English → ไทย"}</button></div><div className="setting-row"><span>{th ? "ธีม" : "Theme"}</span><button type="button" onClick={() => setDark(!dark)}>{dark ? (th ? "มืด → สว่าง" : "Dark → Light") : (th ? "สว่าง → มืด" : "Light → Dark")}</button></div></section></div>}
      {loading && <span className="loading-note" role="status">{th ? "กำลังโหลดข้อมูล…" : "Loading data…"}</span>}</div></section></main>;
}

function Stat({ label, value, detail, icon }: { label: string; value: string; detail: string; icon: string }) { const iconName = icon === "฿" ? "revenue" : icon === "▦" ? "stores" : icon === "◇" ? "skus" : "forecast"; return <article className="stat"><span className="stat-icon"><UiIcon name={iconName}/></span><p>{label}</p><strong>{value}</strong><small>{detail}</small></article>; }
function MetricRow({ label, value }: { label: string; value: string }) { return <div className="metric-row"><span>{label}</span><strong>{value}</strong></div>; }
function SegmentTable({ title, rows, th }: { title: string; rows: { id: string; wape: number | null; test_rows: number }[]; th: boolean }) { return <div className="segment-table"><h3>{title}</h3>{rows.length ? <div className="table-scroll"><table><thead><tr><th>{title}</th><th>WAPE</th><th>{th ? "แถว" : "Rows"}</th></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td>{row.id}</td><td>{percent(row.wape)}</td><td>{count(row.test_rows)}</td></tr>)}</tbody></table></div> : <p className="muted">{th ? "ไม่มีข้อมูลทดสอบ" : "No evaluated data"}</p>}</div>; }
function Empty({ title, text, action, onAction }: { title: string; text: string; action: string; onAction: () => void }) { return <div className="empty"><div className="empty-icon"><UiIcon name="forecast" width="29" height="29"/></div><h3>{title}</h3><p>{text}</p><button className="secondary" type="button" onClick={onAction}>{action} →</button></div>; }
function TrendChart({ data }: { data: Point[] }) {
  return <div className="trend-chart">
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data}>
        <defs>
          <linearGradient id="actualFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--teal)" stopOpacity={0.18}/>
            <stop offset="100%" stopColor="var(--teal)" stopOpacity={0}/>
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="var(--grid)"/>
        <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={28} padding={{ left: 12, right: 24 }} tickFormatter={value => String(value).slice(5)}/>
        <YAxis tickLine={false} axisLine={false} tickFormatter={value => `${Math.round(value / 1000)}k`}/>
        <Tooltip formatter={(value: number) => money(value)}/>
        <Area type="monotone" dataKey="actual" name="Actual" stroke="var(--teal)" strokeWidth={2.5} fill="url(#actualFill)" connectNulls={false} isAnimationActive={false}/>
        <Area type="monotone" dataKey="forecast" name="Forecast" stroke="var(--primary)" strokeWidth={2.5} strokeDasharray="6 5" fill="none" connectNulls={false} isAnimationActive={false}/>
      </AreaChart>
    </ResponsiveContainer>
  </div>;
}
