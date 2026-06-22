export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

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
