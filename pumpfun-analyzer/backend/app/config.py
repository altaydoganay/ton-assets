"""Uygulama yapılandırması.

Tüm gizli anahtarlar ve sağlayıcı ayarları ortam değişkenlerinden (.env)
okunur. Hiçbir API anahtarı veya özel anahtar kaynak koduna gömülmez.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Genel ---
    app_name: str = "Pump.fun Cüzdan Analizcisi"
    # SÜRÜM/BUILD numarası — her anlamlı güncellemede artar. Panelin üst barında
    # ve /health'te gösterilir; deploy'un doğru kodu aldığını buradan doğrularsın.
    app_build: str = "95"
    app_build_label: str = "UI bilgi mimarisi: 5 ana bölüm + bölüm sekmeleri + tek Sıfırlama Merkezi + isim düzeltmeleri"
    environment: Literal["development", "production", "test"] = "development"
    api_prefix: str = "/api"
    secret_key: str = Field(default="degistir-bu-anahtari", description="Uygulama imza anahtarı")

    # --- Veritabanı ---
    database_url: str = Field(
        default="postgresql+psycopg://pump:pump@localhost:5432/pumpfun",
        description="SQLAlchemy bağlantı dizesi",
    )

    # --- Redis / Kuyruk ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- Veri sağlayıcıları (adapter seçimi) ---
    # Birincil zincir verisi sağlayıcısı: "helius" | "rpc"
    # Varsayılan "helius": HELIUS_API_KEY varsa Enhanced Transactions ile derin +
    # ucuz alım (cüzdan başına ~100 RPC çağrısı yerine TEK istek) kullanılır.
    # Anahtar yoksa otomatik olarak standart RPC'ye düşülür (registry'de ele alınır).
    chain_provider: str = "helius"
    # Fiyat/piyasa verisi sağlayıcısı: "birdeye" | "dexscreener"
    market_provider: str = "dexscreener"

    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    # Yedek RPC havuzu (VİRGÜLLE ayrık, sırayla): birincil bir metodu plan/arşiv
    # limitiyle (403/-32002) reddederse o metod METOD-BAZLI buraya yönlenir; birincil
    # tümden çökerse (kota 403) tüm istekler havuza düşer. Varsayılan iki ÜCRETSİZ,
    # anahtarsız node: Solana Labs public + publicnode (Allnodes). İkisi de canlı
    # doğrulandı (getSignaturesForAddress dahil — arşiv bloğu yok). Yük dağılır,
    # 429'a karşı dayanıklılık artar; istersen kendi node'larını virgülle ekle.
    solana_rpc_fallback_url: str = "https://api.mainnet-beta.solana.com,https://solana-rpc.publicnode.com"
    solana_ws_url: str = "wss://api.mainnet-beta.solana.com"
    # Yedek WS havuzu (VİRGÜLLE ayrık): birincil WS reddedilirse (örn. Chainstack
    # aylık kota 403) dinleyici sırayla bunlara döner. Public node'lar blockSubscribe
    # DESTEKLEMEZ ama logsSubscribe(mentions) İLETİR (ikisi de canlı doğrulandı) →
    # mod merdiveni: block → mentions → all. İkisi de ÜCRETSİZ ve anahtarsız.
    solana_ws_fallback_url: str = "wss://api.mainnet-beta.solana.com,wss://solana-rpc.publicnode.com"
    helius_api_key: str = ""
    helius_rpc_url: str = ""
    helius_ws_url: str = ""  # boşsa api-key'den üretilir

    @field_validator("helius_api_key", mode="after")
    @classmethod
    def _sanitize_helius_key(cls, v: str) -> str:
        """Bozuk/yanlış yapıştırılmış Helius anahtarını YOK SAY.

        Yaygın .env hatası: iki satırın birleşmesi (örn.
        `HELIUS_API_KEY=HELIUS_RPC_URL=https://...`) anahtara çöp bir değer atar.
        Bu değer 'dolu' sayılınca kod Chainstack/RPC'yi yok sayıp bozuk Helius'a
        gider. Anahtar '=', 'http' veya boşluk içeriyorsa geçersizdir → boş kabul
        edip standart RPC (SOLANA_RPC_URL) yoluna güvenle döneriz."""
        v = (v or "").strip()
        if not v:
            return ""
        if "=" in v or "http" in v.lower() or " " in v or "\t" in v:
            import logging
            logging.getLogger(__name__).warning(
                "HELIUS_API_KEY bozuk görünüyor (=/http/boşluk içeriyor); yok sayılıyor. "
                ".env'de HELIUS_API_KEY ve HELIUS_RPC_URL AYRI satırlarda olmalı."
            )
            return ""
        return v
    # Canlı dinleyici sağlayıcısı: "helius" (ücretsiz, SOL yakmaz) | "pumpportal"
    listener_provider: str = "auto"
    # WS abonelik modu:
    #  "mentions" → logsSubscribe adres filtreli (yalnız Helius/Triton destekler).
    #  "block"    → blockSubscribe(mentionsAccountOrProgram=pump.fun, full):
    #               SUNUCU filtreli + işlemler META'sıyla GÖMÜLÜ gelir →
    #               getTransaction ÇAĞRISI YOK, "all"e göre ~100× az bildirim.
    #               Chainstack'te canlı doğrulandı. EN UCUZ + EN HIZLI yol.
    #  "all"      → logsSubscribe["all"]: tüm Solana logları, client-side filtre.
    #               Çok kredi yakar; yalnız block da mentions da çalışmayan node
    #               için son çare (block başarısız olursa otomatik buna düşülür).
    #  "auto"     → Helius anahtarı varsa mentions, yoksa block.
    ws_logs_mode: Literal["auto", "mentions", "all", "block"] = "auto"
    # RPC hız limiti koruması: istekler arası asgari süre (sn) ve 429 tekrar sayısı.
    # Helius ücretsiz katman ~10 istek/sn; 0.12 ≈ 8 istek/sn güvenli.
    # NOT: Bu throttle yalnızca arka plan KEŞİF analizinde uygulanır; canlı alım
    # yolunda (hız kritik) throttle KAPALIDIR.
    # Developer planı 50 RPS; 0.04 ≈ 25 istek/sn güvenli ve hızlı.
    rpc_min_interval_seconds: float = 0.01
    rpc_rate_limit_retries: int = 8
    # Canlı alımda token analizi önbelleği: token bu süre içinde puanlandıysa
    # yeniden analiz edilmez (anında karar = düşük gecikme).
    token_score_cache_seconds: int = 45
    birdeye_api_key: str = ""
    dexscreener_base_url: str = "https://api.dexscreener.com"

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_enabled: bool = False

    # --- Güvenlik / Cüzdan kasası ---
    # Trading cüzdanı keystore'unu şifrelemek için kullanılan parola.
    # Boş bırakılırsa canlı işlem devre dışı kalır.
    keystore_passphrase: str = ""
    keystore_path: str = "./data/keystore.json"
    # Panelde gerçek cüzdan portföyünü okumak için public adres. Özel anahtar değil.
    trading_wallet_address: str = ""

    # --- İşlem modu ---
    # "paper" | "alerts_only" | "live"
    trading_mode: Literal["paper", "alerts_only", "live"] = "paper"
    live_trading_confirmed: bool = False

    # --- PumpPortal (canlı veri akışı + işlem gönderimi) ---
    # İşlem gönderimi sağlayıcısı: şimdilik "pumpportal"
    trade_provider: str = "pumpportal"
    pumpportal_api_key: str = ""              # Lightning işlem API anahtarı (GİZLİ)
    pumpportal_data_ws: str = "wss://pumpportal.fun/api/data"
    pumpportal_trade_url: str = "https://pumpportal.fun/api/trade"
    pumpportal_default_pool: str = "auto"     # pump | pumpswap | auto
    # Canlı olay akışı dinleyicisi açık mı (listener servisi)
    live_listener_enabled: bool = True
    # PumpPortal WS bazen bağlı görünürken event akışı sessiz kalabilir.
    # Bu süre boyunca hiç ham mesaj gelmezse bağlantı kontrollü kapatılıp yeniden kurulur.
    pumpportal_idle_reconnect_seconds: int = 90

    # --- Otomatik cüzdan keşfi ---
    # Canlı akıştan (yeni token -> o tokenin alıcıları) aday cüzdan toplama.
    discovery_enabled: bool = True
    # Bir cüzdanın aday sayılması için kaç FARKLI token alımında görülmesi gerek.
    # 2 = ÜCRETSİZ ön filtre: tek bir tokeni alıp kaybolan snipe/bot'lar yerine
    # birden çok farklı tokende görülen (tutarlılık sinyali) cüzdanları aday yapar.
    # Böylece kredi yalnızca daha umut vadeden cüzdanların analizine harcanır.
    # GENİŞ AĞ (paper aşaması): 1 = her alıcıyı aday yap (daha çok cüzdan; kaliteyi
    # otomatik eleme + kopya performansı temizler). Canlıya geçerken 2'ye çıkarılabilir.
    discovery_min_token_hits: int = 1
    # Aynı anda izlenen (trade aboneliği açık) maksimum token sayısı.
    # AI modunda yeni token kaçırmamak için daha yüksek tutulur; eski tokenlar
    # yaş penceresi dolunca otomatik abonelikten çıkarılır.
    discovery_max_watched_tokens: int = 1500
    # AI canlı token akışını kaçırmamak için PumpPortal mesajları event-loop'u
    # kilitlemeden kuyrukla işlenir. Çok düşük değer yeni token kaçırır; çok
    # yüksek değer gecikmiş sinyalleri biriktirir.
    ai_signal_workers: int = 8
    ai_signal_queue_size: int = 5000
    ai_signal_token_cooldown_seconds: float = 1.5
    ai_signal_drop_if_older_seconds: int = 25
    # Her arka plan döngüsünde analiz edilecek aday sayısı (geniş ağ için yüksek).
    discovery_batch_size: int = 25
    # Aday analizinde taranacak işlem sayısı (DERİNLİK). Helius Enhanced
    # Transactions ile 100'er işlem TEK istekte gelir; bu yüzden derin geçmiş
    # (150) ucuzdur ve "8 kapalı pozisyon / 4 farklı token" eleme kriterlerinin
    # gerçek trader'larca karşılanabilmesi için derinlik şarttır. RPC fallback'te
    # bu değer imza-başına çağrı demektir (Helius dışı sağlayıcıda küçült).
    discovery_ingest_limit: int = 150
    # Aday analiz döngüsü aralığı (saniye) — Celery beat. Geniş ağ için sık tara.
    discovery_interval_seconds: int = 15
    # Helius keşfinde dakikada en fazla kaç işlem detayı çekilsin. Geniş ağ
    # (paper aşaması) için yüksek: daha çok cüzdan keşfet/analiz et. Canlıya
    # geçerken bütçeyi korumak için düşürülebilir.
    # Bu, keşif `getTransaction` kredisinin ana kalemidir; bütçeye göre ayarla.
    discovery_max_lookups_per_min: int = 120

    # --- Takip edilen cüzdan izleme (poll) ---
    # Canlı WS dinleyicisi olay kaçırabildiğinden, takip edilen cüzdanların taze
    # alımları periyodik POLL ile de yakalanır (işlem tetikleyici güvencesi).
    # UCUZ yol: cüzdan başına getSignaturesForAddress (~1 kredi) + yalnızca taze/yeni
    # imza için getTransaction (~1 kredi). Boştaki cüzdan döngü başına ~1 kredi.
    tracked_poll_seconds: int = 5             # poll döngü aralığı (sn)
    tracked_poll_per_wallet: int = 12         # her cüzdandan çekilecek son imza sayısı
    tracked_poll_fresh_seconds: int = 1200    # yalnızca son N sn içindeki alımlar işlenir
    # Bir poll döngüsünde en fazla kaç takip cüzdanı taransın. Geniş ağda yüzlerce
    # cüzdan olabilir; en yüksek puanlılar önce taranır (öncelik). Bütçe koruması.
    tracked_poll_max_wallets: int = 1000

    # --- Lider elde tutma bekçisi ---
    # Açık copy pozisyonlarında lider tokenı hâlâ tutuyor mu periyodik kontrol eder.
    # SELL olayı kaçarsa bizim pozisyonu acil kapatmak için güvenlik ağıdır.
    leader_hold_watch_seconds: int = 10

    # --- Eşikler (varsayılan; veritabanındaki settings tablosu önceliklidir) ---
    min_wallet_score: float = 70.0
    min_token_score: float = 70.0

    cors_origins: str = "*"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
