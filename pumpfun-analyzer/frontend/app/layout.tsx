import "./globals.css";
import type { Metadata } from "next";
import { Sidebar } from "@/components/Sidebar";
import { ThemeToggle } from "@/components/ThemeToggle";

export const metadata: Metadata = {
  title: "Pump.fun Cüzdan Analizcisi",
  description: "Solana & Pump.fun cüzdan ve token analizi, bildirim ve kopya işlem paneli",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr" className="dark">
      <body>
        <div className="flex h-screen">
          <Sidebar />
          <div className="flex flex-1 flex-col overflow-hidden">
            <header
              className="flex items-center justify-between border-b px-6 py-3"
              style={{ borderColor: "var(--border)" }}
            >
              <div className="text-sm muted">
                Yatırım tavsiyesi değildir · Kârlılık garantisi yoktur
              </div>
              <ThemeToggle />
            </header>
            <main className="flex-1 overflow-y-auto p-6">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
