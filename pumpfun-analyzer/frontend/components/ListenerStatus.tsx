"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";

export function ListenerStatus() {
  const { data } = useSWR<any>("/setup", fetcher, { refreshInterval: 20000 });
  if (!data) return null;
  const listener = data.checks?.find((c: any) => c.key === "listener");
  const ok = listener?.ok;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="relative flex h-2.5 w-2.5">
        {ok && <span className="absolute inline-flex h-full w-full animate-ping rounded-full" style={{ background: "#10b981", opacity: 0.6 }} />}
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full" style={{ background: ok ? "#10b981" : "#ef4444" }} />
      </span>
      <span className="muted">Dinleyici: {ok ? "bağlı" : "kapalı"}</span>
      {data.trade_stream_ok === false && (
        <span
          className="rounded px-1.5 py-0.5 font-semibold text-red-500"
          style={{ background: "#ef444422" }}
          title={data.trade_stream_hint || "PumpPortal trade aboneliği çalışmıyor: funded API anahtarı (≥0.02 SOL) gerekli."}
        >
          ⚠ Trade akışı YOK
        </span>
      )}
      <span className="muted">·</span>
      <span className="muted">Mod: {data.trading_mode === "live" ? "Canlı" : data.trading_mode === "paper" ? "Paper" : data.trading_mode}</span>
      {data.token_gate && (<><span className="muted">·</span><span className="muted">Kapı: {data.token_gate}</span></>)}
      {data.build && (
        <>
          <span className="muted">·</span>
          <span
            className="rounded px-1.5 py-0.5 font-semibold"
            style={{ background: "#10b98122", color: "#10b981" }}
            title={data.build_label || ""}
          >
            BUILD {data.build}
          </span>
        </>
      )}
    </div>
  );
}
