"use client";
import { useEffect, useRef, useState } from "react";

/** Değer değiştiğinde eski değerden yenisine yumuşak (ease-out) sayan rakam.
 *  prefers-reduced-motion açıksa anında atlar. */
export function CountUp({
  value, decimals = 0, prefix = "", suffix = "", duration = 700, signed = false,
}: {
  value: number; decimals?: number; prefix?: string; suffix?: string; duration?: number; signed?: boolean;
}) {
  const [shown, setShown] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const reduce = typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const from = fromRef.current;
    const to = value;
    if (reduce || from === to) { setShown(to); fromRef.current = to; return; }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
      setShown(from + (to - from) * eased);
      if (t < 1) rafRef.current = requestAnimationFrame(tick);
      else fromRef.current = to;
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [value, duration]);

  const sign = signed && shown > 0 ? "+" : "";
  return <span>{sign}{prefix}{shown.toLocaleString("tr-TR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}</span>;
}
