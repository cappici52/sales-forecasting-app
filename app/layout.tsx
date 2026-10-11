import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ProjectA_1 | Sales Forecasting",
  description: "ระบบพยากรณ์ยอดขายด้วย Machine Learning"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="th" suppressHydrationWarning><body>{children}</body></html>;
}
