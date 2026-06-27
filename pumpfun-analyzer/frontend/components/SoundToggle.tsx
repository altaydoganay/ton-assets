"use client";
import { useEffect, useState } from "react";
import { Volume2, VolumeX } from "lucide-react";
import { playPing } from "./Celebrations";

/** Bildirim sesini aç/kapat (localStorage). Açınca kısa bir önizleme çalar. */
export function SoundToggle() {
  const [on, setOn] = useState(false);
  useEffect(() => { setOn(typeof window !== "undefined" && localStorage.getItem("altay_sound") === "1"); }, []);

  function toggle() {
    const next = !on;
    setOn(next);
    localStorage.setItem("altay_sound", next ? "1" : "0");
    if (next) playPing();
  }

  return (
    <button className="btn-ghost" onClick={toggle} title={on ? "Bildirim sesi açık" : "Bildirim sesi kapalı"}>
      {on ? <Volume2 size={16} /> : <VolumeX size={16} />}
    </button>
  );
}
