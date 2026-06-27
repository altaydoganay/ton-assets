"""Uygulama yapılandırması.

Tüm gizli anahtarlar ve sağlayıcı ayarları ortam değişkenlerinden (.env)
okunur. Hiçbir API anahtarı veya özel anahtar kaynak koduna gömülmez.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Genel ---
    app_name: str = "Pump.fun Cüzdan Analizcisi"
    # SÜRÜM/BUILD numarası — her anlamlı güncellemede artar. Panelin üst barında
    # ve /health'te gösterilir; deploy'un doğru kodu aldığını buradan doğrularsın.
    app_build: str = "24"
    app_build_label: str = "cüzdanları yeniden tara (kredisiz) + PnL-temelli eleme + geniş ağ"
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
    solana_ws_url: str = "wss://api.mainnet-beta.solana.com"
    helius_api_key: str = ""
    helius_rpc_url: str = ""
    helius_ws_url: str = ""  # boşsa api-key'den üretilir
    # Canlı dinleyici sağlayıcısı: "helius" (ücretsiz, SOL yakmaz) | "pumpportal"
    listener_provider: str = "helius"
    # RPC hız limiti koruması: istekler arası asgari süre (sn) ve 429 tekrar sayısı.
    # Helius ücretsiz katman ~10 istek/sn; 0.12 ≈ 8 istek/sn güvenli.
    # NOT: Bu throttle yalnızca arka plan KEŞİF analizinde uygulanır; canlı alım
    # yolunda (hız kritik) throttle KAPALIDIR.
    # Developer planı 50 RPS; 0.04 ≈ 25 istek/sn güvenli ve hızlı.
    rpc_min_interval_seconds: float = 0.04
    rpc_rate_limit_retries: int = 6
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
    # Aynı anda izlenen (trade aboneliği açık) maksimum token sayısı
    discovery_max_watched_tokens: int = 120
    # Her arka plan döngüsünde analiz edilecek aday sayısı (geniş ağ için yüksek).
    discovery_batch_size: int = 8
    # Aday analizinde taranacak işlem sayısı (DERİNLİK). Helius Enhanced
    # Transactions ile 100'er işlem TEK istekte gelir; bu yüzden derin geçmiş
    # (150) ucuzdur ve "8 kapalı pozisyon / 4 farklı token" eleme kriterlerinin
    # gerçek trader'larca karşılanabilmesi için derinlik şarttır. RPC fallback'te
    # bu değer imza-başına çağrı demektir (Helius dışı sağlayıcıda küçült).
    discovery_ingest_limit: int = 150
    # Aday analiz döngüsü aralığı (saniye) — Celery beat. Geniş ağ için sık tara.
    discovery_interval_seconds: int = 120
    # Helius keşfinde dakikada en fazla kaç işlem detayı çekilsin. Geniş ağ
    # (paper aşaması) için yüksek: daha çok cüzdan keşfet/analiz et. Canlıya
    # geçerken bütçeyi korumak için düşürülebilir.
    # Bu, keşif `getTransaction` kredisinin ana kalemidir; bütçeye göre ayarla.
    discovery_max_lookups_per_min: int = 20

    # --- Takip edilen cüzdan izleme (poll) ---
    # Canlı WS dinleyicisi olay kaçırabildiğinden, takip edilen cüzdanların taze
    # alımları periyodik POLL ile de yakalanır (işlem tetikleyici güvencesi).
    # UCUZ yol: cüzdan başına getSignaturesForAddress (~1 kredi) + yalnızca taze/yeni
    # imza için getTransaction (~1 kredi). Boştaki cüzdan döngü başına ~1 kredi.
    tracked_poll_seconds: int = 60            # poll döngü aralığı (sn)
    tracked_poll_per_wallet: int = 6          # her cüzdandan çekilecek son imza sayısı
    tracked_poll_fresh_seconds: int = 900     # yalnızca son N sn içindeki alımlar işlenir
    # Bir poll döngüsünde en fazla kaç takip cüzdanı taransın. Geniş ağda yüzlerce
    # cüzdan olabilir; en yüksek puanlılar önce taranır (öncelik). Bütçe koruması.
    tracked_poll_max_wallets: int = 150

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
