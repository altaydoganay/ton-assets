// API adresini ÇALIŞMA ANINDA belirle ki panel hangi cihazdan/host'tan açılırsa
// açılsın (telefon, uzak IP, Tailscale) doğru backend'e gitsin:
//   1) NEXT_PUBLIC_API_URL tanımlıysa onu kullan (reverse-proxy/özel domain).
//   2) Tarayıcıda: sayfanın açıldığı host + :8000/api (compose varsayılanı) —
//      böylece http://<sunucu-ip>:3000 açınca API otomatik http://<sunucu-ip>:8000'e gider.
//   3) SSR fallback (localhost).
function resolveApiUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000/api`;
  }
  return "http://localhost:8000/api";
}

export const API_URL = resolveApiUrl();

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new ApiError(res.status, `İstek başarısız: ${res.status}`);
  }
  return res.json();
}

export async function apiSend<T>(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new ApiError(res.status, `İstek başarısız: ${res.status}`);
  return res.json();
}

export const fetcher = <T = any>(path: string): Promise<T> => apiGet<T>(path);

export function shortAddr(a?: string | null): string {
  if (!a) return "—";
  return a.length > 10 ? `${a.slice(0, 4)}…${a.slice(-4)}` : a;
}

export function fmtNum(n?: number | null, digits = 2): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("tr-TR", { maximumFractionDigits: digits });
}
