import "./globals.css";
import type { Metadata } from "next";
import { Shell } from "@/components/Shell";
import { ToastProvider } from "@/components/Toast";

export const metadata: Metadata = {
  title: "Pump.fun Cüzdan Analizcisi",
  description: "Solana & Pump.fun cüzdan ve token analizi, bildirim ve kopya işlem paneli",
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
