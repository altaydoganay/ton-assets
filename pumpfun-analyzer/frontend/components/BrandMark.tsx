"use client";

/** TradeFable logosu — boğa boynuzu + yıldızlı "FF" markası (kullanıcı marka
 *  varlığı). Nefes-alma animasyonu CSS'te (.brandmark). */
export function BrandMark({ size = 34 }: { size?: number }) {
  return (
    <span className="brandmark" style={{ width: size, height: size }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/brand/tradefable-mark.png"
        width={size}
        height={size}
        alt="TradeFable"
        style={{ display: "block", width: size, height: size, borderRadius: Math.round(size * 0.28) }}
      />
    </span>
  );
}

/** Logo + "TradeFable" wordmark (kenar çubuğu / başlık için). */
export function BrandLockup({ size = 34, subtitle = true }: { size?: number; subtitle?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <BrandMark size={size} />
      <div className="leading-tight">
        <div className="text-[16px] font-extrabold tracking-tight">
          Trade<span style={{ color: "#22c55e" }}>Fable</span>
        </div>
        {subtitle && <div className="text-[10px] muted">AI &amp; Copy Trade paneli</div>}
      </div>
    </div>
  );
}
