import "./globals.css";
import type { Metadata, Viewport } from "next";
import { Shell } from "@/components/Shell";
import { ToastProvider } from "@/components/Toast";

export const metadata: Metadata = {
  title: "Altay Analysis Bot",
  description: "Akıllı para kopya istihbaratı — Solana & Pump.fun cüzdan/token analizi ve kopya işlem paneli",
  applicationName: "Altay Analysis Bot",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "Altay Bot" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",      // telefon çentik/kenar güvenli alanına uyum
  themeColor: "#0f1827",     // mobil tarayıcı çubuğu rengi (koyu tema)
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
