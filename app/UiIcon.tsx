import { ReactNode, SVGProps } from "react";

type Name = "overview" | "forecast" | "import" | "model" | "settings" | "revenue" | "stores" | "skus" | "logout";

const paths: Record<Name, ReactNode> = {
  overview: <><rect x="3" y="3" width="7" height="7" rx="1.4"/><rect x="14" y="3" width="7" height="7" rx="1.4"/><rect x="3" y="14" width="7" height="7" rx="1.4"/><rect x="14" y="14" width="7" height="7" rx="1.4"/></>,
  forecast: <><path d="M3 18h18M5 15l4-5 4 2 6-7"/><path d="M16 5h3v3"/></>,
  import: <><path d="M12 16V3m0 0L7.5 7.5M12 3l4.5 4.5"/><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/></>,
  model: <><path d="M3 19h18M5 15l4-4 4 2 6-7"/><circle cx="5" cy="15" r="1"/><circle cx="9" cy="11" r="1"/><circle cx="13" cy="13" r="1"/><circle cx="19" cy="6" r="1"/></>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l-1.8 1.8a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21h-2.6v-1a1.7 1.7 0 0 0-1.1-1.6 1.7 1.7 0 0 0-1.9.3l-1.8-1.8a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H5v-2.6h1a1.7 1.7 0 0 0 1.6-1.1 1.7 1.7 0 0 0-.3-1.9l1.8-1.8a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 12 5V4h2.6v1a1.7 1.7 0 0 0 1.1 1.6 1.7 1.7 0 0 0 1.9-.3l1.8 1.8a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1H21v2.6h-1a1.7 1.7 0 0 0-1.6 1.1Z"/></>,
  revenue: <><circle cx="12" cy="12" r="9"/><path d="M12 6v12m3-9.5h-4a2 2 0 1 0 0 4h2a2 2 0 0 1 0 4H9"/></>,
  stores: <><path d="M3 10h18l-1.7-6H4.7L3 10ZM5 10v10h14V10M9 20v-6h6v6"/></>,
  skus: <><path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5v-9ZM4 7.5l8 4.5 8-4.5M12 12v9"/></>,
  logout: <><path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M13 8l4 4-4 4m4-4H9"/></>,
};

export function UiIcon({ name, ...props }: { name: Name } & SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}
