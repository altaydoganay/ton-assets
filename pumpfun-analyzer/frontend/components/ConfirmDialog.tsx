"use client";
import { useState, useCallback } from "react";

type Opts = { title: string; body?: string; confirmText?: string; danger?: boolean };

export function useConfirm() {
  const [state, setState] = useState<(Opts & { resolve: (v: boolean) => void }) | null>(null);
  const confirm = useCallback((opts: Opts) => new Promise<boolean>((resolve) => setState({ ...opts, resolve })), []);

  const dialog = state ? (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => { state.resolve(false); setState(null); }}>
      <div className="card w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold">{state.title}</h3>
        {state.body && <p className="muted mt-2 text-sm">{state.body}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn" onClick={() => { state.resolve(false); setState(null); }}>Vazgeç</button>
          <button
            className={state.danger ? "btn-danger" : "btn-primary"}
            onClick={() => { state.resolve(true); setState(null); }}
          >
            {state.confirmText || "Onayla"}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return { confirm, dialog };
}
