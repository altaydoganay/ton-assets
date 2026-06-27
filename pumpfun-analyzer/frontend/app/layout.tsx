import "./globals.css";
import type { Metadata } from "next";
import { Shell } from "@/components/Shell";
import { ToastProvider } from "@/components/Toast";

export const metadata: Metadata = {
  title: "Altay Analysis Bot",
  description: "Akıllı para kopya istihbaratı — Solana & Pump.fun cüzdan/token analizi ve kopya işlem paneli",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr" className="dark">
      <body>
        <ToastProvider>
          <Shell>{children}</Shell>
        </ToastProvider>
      </body>
    </html>
  );
}
