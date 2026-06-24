"use client";
import { createContext, useContext, useCallback, useState } from "react";
import { CheckCircle2, XCircle, Info, X } from "lucide-react";

type Toast = { id: number; kind: "success" | "error" | "info"; text: string };
const Ctx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((s) => [...s, { id, kind, text }]);
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), 4000);
  }, []);
  const Icon = { success: CheckCircle2, error: XCircle, info: Info };
  const color = { success: "#10b981", error: "#ef4444", info: "#38bdf8" };
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {items.map((t) => {
          const I = Icon[t.kind];
          return (
            <div key={t.id} className="card flex items-center gap-3 py-3 pr-3 shadow-lg" style={{ minWidth: 280 }}>
              <I size={18} style={{ color: color[t.kind] }} />
              <span className="flex-1 text-sm">{t.text}</span>
              <button onClick={() => setItems((s) => s.filter((x) => x.id !== t.id))} className="btn-ghost">
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}
