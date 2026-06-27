"use client";

/** Altay Analysis Bot logosu — degrade monogram "A" + yükseliş çizgisi.
 *  Animasyon (nefes alma + degrade) CSS'te (.brandmark / .wordmark). */
export function BrandMark({ size = 34 }: { size?: number }) {
  return (
    <span className="brandmark" style={{ width: size, height: size }}>
      <svg viewBox="0 0 48 48" width={size} height={size} fill="none" aria-hidden>
        <defs>
          <linearGradient id="bm-stroke" x1="2" y1="2" x2="46" y2="46" gradientUnits="userSpaceOnUse">
            <stop stopColor="var(--brand)" />
            <stop offset="0.5" stopColor="var(--sky)" />
            <stop offset="1" stopColor="var(--violet)" />
          </linearGradient>
        </defs>
        <rect x="3" y="3" width="42" height="42" rx="13" stroke="url(#bm-stroke)" strokeWidth="2.5" />
        {/* "A" monogramı */}
        <path d="M15 34 L24 13 L33 34" stroke="url(#bm-stroke)" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M19 28 H29" stroke="url(#bm-stroke)" strokeWidth="3.2" strokeLinecap="round" />
        {/* yükseliş noktası */}
        <circle cx="33" cy="14" r="2.4" fill="var(--emerald)" />
      </svg>
    </span>
  );
}

/** Logo + "Altay Analysis Bot" wordmark (kenar çubuğu / başlık için). */
export function BrandLockup({ size = 34, subtitle = true }: { size?: number; subtitle?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <BrandMark size={size} />
      <div className="leading-tight">
        <div className="wordmark text-[15px] font-extrabold tracking-tight">Altay Analysis Bot</div>
        {subtitle && <div className="text-[10px] muted">Akıllı Para Kopya İstihbaratı</div>}
      </div>
    </div>
  );
}
