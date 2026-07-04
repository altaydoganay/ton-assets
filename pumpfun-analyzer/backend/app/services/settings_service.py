"""Ayar deposu servisi (DB tabanlı, varsayılanlarla).

Puan ağırlıkları, eşikler, uygunluk kuralları ve risk/işlem parametreleri
`settings` tablosunda anahtar-değer olarak tutulur. Panelden güncellenebilir.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.scoring.token_scoring import DEFAULT_WEIGHTS as TOKEN_WEIGHTS
from ..core.scoring.wallet_scoring import DEFAULT_ELIGIBILITY, DEFAULT_WEIGHTS as WALLET_WEIGHTS
from ..models import Setting

DEFAULTS: dict[str, dict] = {
    "wallet_weights": WALLET_WEIGHTS,
    "wallet_eligibility": DEFAULT_ELIGIBILITY,
    "token_weights": TOKEN_WEIGHTS,
    "stats_baseline": {},
    # max_tracked: aynı anda takip edilecek EN FAZLA cüzdan (0 = sınırsız). Eleme
    # (cull) bunu preset'e göre ayarlar; persist_wallet_score yeni takibi bu sınırda
    # tutar — böylece eleme sonrası keşif akışı sayıyı geri şişirmez.
    "thresholds": {"wallet": 55.0, "token": 70.0, "max_tracked": 0},
    "risk": {
        # Paper (simülasyon) işlem motoru varsayılan AÇIK — risksizdir; CANLI
        # (gerçek para) ayrı bir onaya bağlıdır (live_confirmed) ve KAPALI kalır.
        "enabled": True,
        "mode": "paper",
        # Strateji seçimi:
        #   copy = takip edilen cüzdan alım/satımını yansıtır.
        #   ai   = cüzdanı ana karar yapmaz; taze token fırsatını analiz edip kendi sinyalini üretir.
        "strategy_mode": "copy",
        "live_confirmed": False,
        # İşlem kapısı: token bir GÜVENLİK filtresidir, kalite notu DEĞİL — taze
        # pump.fun token'leri (likidite/holder verisi henüz yok) adil puanlanamaz;
        # asıl sinyal CÜZDANDIR. "safety" = güvenlik vetosu (rug/honeypot/aktif
        # mint-freeze/sahte likidite) yoksa işlem açılır; arbitrer bir puan eşiği
        # DAYATILMAZ. Bu "her token" değildir — scam token'leri yine elenir.
        # "safety" | "balanced" (+≥55) | "score" (+tam eşik). Bkz. trading/risk.py.
        "token_gate": "safety",
        "fixed_sol_amount": 0.01,
        "proportional": False,
        "proportional_factor": 1.0,
        "max_position_sol": 0.01,
        "max_daily_spend_sol": 0.10,
        "max_daily_loss_sol": 0.03,
        "max_slippage": 0.15,
        "priority_fee_sol": 0.0005,
        # Motor skor eşikleri: TAKİP kararı (status==tracked) zaten kaliteyi
        # belirlediğinden motorda ek skor engeli UYGULAMAYIZ (0 = engel yok).
        # Token kalitesini "token_gate" yönetir; cüzdan kalitesini takip listesi.
        "min_wallet_score": 0.0,
        "min_token_score": 0.0,    # yalnızca token_gate="score" modunda uygulanır
        "max_open_positions_per_token": 1,
        # GEÇ-GİRİŞ KORUMASI: lider alımından bu kadar saniyeden FAZLA geçtiyse
        # kopya alım yapma (fiyat çoktan pompalanmış olabilir = tepeden alım riski).
        # Poll yolu liderin alımından bu yana geçen GERÇEK süreyi ölçer.
        "max_follow_lag_seconds": 30,
        # PAPER/alerts modunda geç-giriş toleransı (görünürlük). Gerçek-zamanlı WS
        # yoksa copy olayları RPC poll ile gecikmeli gelir; canlı sıkı limit paper
        # testinde tüm copy'leri boğuyordu. Canlıda bu KULLANILMAZ (üstteki sıkı geçerli).
        "max_follow_lag_seconds_paper": 300,
        "min_liquidity_sol": 5.0,  # yalnızca ölçülebildiğinde uygulanır
        "emergency_stop": False,
        "blocked_wallets": [],
        "blocked_tokens": [],
        "only_wallets": [],
        "close_mode": "proportional",
        "take_profit_pct": 0.5,   # +%50'de sat (sert TP)
        "stop_loss_pct": 0.25,    # -%25'te sat (sert SL)
        # SAF KOPYA MODU: açıkken otomatik çıkışlar (TP/SL/trailing/zaman) DEVRE DIŞI;
        # yalnızca lider satınca satılır. Takip ettiğimiz cüzdanların GERÇEK kazancını
        # net ölçmek için ölçüm aşamasında AÇIK gelir.
        "pure_mirror_mode": True,
        # --- AKILLI ÇIKIŞ (kârı belirleyen yer; pure_mirror kapalıyken çalışır) ---
        "trailing_stop_pct": 0.12,   # fiyat zirveden %12 düşerse sat (0 = kapalı)
        "trail_activate_pct": 0.15,  # takip eden stop, +%15 kâra ulaşınca aktifleşir
        "max_hold_minutes": 45,      # bu süre dolunca pozisyonu kapat (0 = kapalı)
        # KADEMELİ KÂR ALIMI: +%35'te pozisyonun yarısı satılır, kalan trailing'de
        # taşınır (erken tam satıp pump'ı kaçırma ↔ hiç satmayıp geri verme dengesi).
        "partial_tp_pct": 0.35,
        "partial_tp_fraction": 0.5,
        # LİKİDİTE WATCHDOG: havuz likiditesi zirveden %60+ düştüyse (rug/çekilme)
        # TP/SL beklemeden ACİL tam çıkış. 0 = kapalı.
        "exit_liq_drop_pct": 0.6,
        # DURGUNLUK ÇIKIŞI: 12 dk boyunca kârsız sürünen pozisyondan erken çık
        # (ölü pump.fun tokeni geri gelmez; sermaye yeni fırsata dönmeli). 0 = kapalı.
        "stagnant_exit_minutes": 12,
        "stagnant_max_pnl_pct": 0.0,
        # --- AI PUMP.FUN AVCISI (hunter) — kademeli giriş + ana-para çıkışı + moonbag ---
        # Yalnızca strategy_mode="ai" ve ai_hunter_enabled iken devrededir. Amaç:
        # erken yakala, körleme büyük girme; 2-3x'te ANA PARAYI çıkar (kalan risksiz),
        # 10x'te kalanın %25'ini kâr al, kalanı moonbag olarak GENİŞ trailing ile taşı;
        # risk bozulunca hızlı çık. Copy modu bu bloktan etkilenmez.
        "ai_hunter_enabled": True,
        # Giriş kademeleri — scout girişi paper_trade_sol'ün çarpanıdır (körleme büyük girme).
        "ai_watch_min_score": 70,          # 70-79: sadece izle (alma)
        "ai_scout_min_score": 80,          # 80+: küçük scout girişi
        "ai_scout_fraction": 0.35,         # 80-94 skor scout büyüklüğü (paper_trade_sol ×)
        "ai_scout_strong_fraction": 0.55,  # 95+ skor: biraz daha büyük, yine kademeli
        # Ana para çıkışı: değer bu çarpana ulaşınca ana para + fee/slippage tamponu geri alınır.
        "ai_principal_mult": 2.5,
        "ai_principal_fee_buffer": 0.08,   # ana para × (1+buffer) kadarını geri al
        # 10x kâr alımı — ana para çıktıktan SONRA kalanın %'i.
        "ai_tp10_mult": 10.0,
        "ai_tp10_fraction": 0.25,
        # Opsiyonel 25x kâr alımı (ayarlanabilir; varsayılan KAPALI).
        "ai_tp25_enabled": False,
        "ai_tp25_mult": 25.0,
        "ai_tp25_fraction": 0.18,
        # Stop — ana para ÇIKMADAN önce SERT, çıktıktan sonra GENİŞ (moonbag panik yapmasın).
        "ai_stop_pre_pct": 0.35,           # ana para öncesi sert stop (-%35)
        "ai_trail_pre_pct": 0.28,          # ana para öncesi trailing (trail_activate_pct sonrası)
        "ai_trail_moon_pct": 0.45,         # moonbag geniş trailing (zirveden -%45)
        # Zaman çıkışları — sadece ana para çıkmadan (sürünen tokende sermaye bekletme).
        "ai_momentum_minutes": 4.0,        # bu süre sonunda mult < momentum_min ise çık
        "ai_momentum_min_mult": 1.3,
        "ai_twox_minutes": 10.0,           # bu süre sonunda 2x'e yaklaşmadıysa çık
        "ai_twox_min_mult": 2.0,
        # --- AKILLI PARA MUTABAKATI (confluence) ---
        "min_confluence": 1,             # 1 = kapalı; 2 = sadece 2+ takip cüzdanı aynı token'i alınca aç
        "live_min_confluence": 1,        # canlıda hızlı giriş için confluence kapalı
        "confluence_window_minutes": 30, # mutabakat penceresi (dk)
        # PAPER (simülasyon) modunda her işlem SABİT bu kadar SOL olsun — net
        # kâr/zarar adil ölçülsün (lider miktarlarından bağımsız). Canlıda
        # fixed_sol_amount / proportional kullanılır. Cüzdan-bazlı elle override
        # (copy_overrides) her ikisini de geçersiz kılar.
        "paper_trade_sol": 0.01,
        "copyability_enabled": True,
        "copyability_delays_seconds": [5, 10, 30],
        "copyability_amount_sol": 0.01,
        "copyability_min_sample": 6,
        "copyability_require_min_sample": False,
        "copyability_min_coverage": 0.70,
        "copyability_max_entry_jump_10s": 0.15,
        "copyability_min_pnl_10s": 0.001,
        # --- Kopya performansına göre OTOMATİK ELEME (bütçeden BAĞIMSIZ) ---
        # Ölçüt BAŞARI ORANI DEĞİL, BİZE GETİRDİĞİ KOPYA PnL'idir: taze pump.fun
        # token'lerinde kârlı bir cüzdan %5-10 isabetle ama yüksek kazanç/kayıp
        # oranıyla kazanabilir; win-rate'e göre eleme bunları yanlışlıkla atardı.
        "copy_prune_enabled": True,
        "copy_max_consecutive_losses": 5,   # N ardışık zarar => cüzdanı engelle (rug sinyali)
        "copy_min_closed_trades": 6,        # PnL yargısı için en az N kapanmış işlem
        "copy_min_pnl_sol": 0.0,            # kopya PnL bunun ALTINDAYSA engelle (vars. 0 = zarar ettiren)
        "copy_min_win_rate": 0.30,          # (bilgilendirme amaçlı; eleme TETİKLEMEZ)
        # --- CANLI İŞLEM KALİTE KAPISI ---
        # Paper aşamasında geniş ağ izlenebilir; canlıda ise sniper/scalper davranışı
        # ve 10 sn gecikmeli copyability zararı işlem açmadan önce sert engellenir.
        "block_sniper_wallets_live": True,
        "live_min_median_hold_seconds": 300,     # 5 dk altı medyan = çok hızlı flip riski
        "live_max_short_hold_ratio": 0.45,       # kapanışların >%45'i <10 dk ise blok
        "live_max_sniper_confidence": 0.50,
        "live_max_scalper_confidence": 0.50,
        "live_min_copyability_score": 65,
        "live_min_copy_sample": 12,
        "live_require_copy_sample": True,
        "live_require_positive_copy_pnl_10s": True,
        "live_max_entry_jump_10s": 0.15,
        "live_fresh_token_only": True,
        "live_max_token_age_minutes": 180,       # 3 saatten eski token alma
        "live_min_token_age_seconds": 30,        # pool/price oturmadan ilk saniyeleri alma
        "live_require_known_token_age": True,    # yaş bilinmiyorsa canlı alım açma
        # --- AI TRADE TOKEN SİNYALİ ---
        # AI Trade modunda cüzdan ana karar değildir. PumpPortal yeni-token akışındaki
        # taze token alımlarını token güvenliği + momentum/yaş/fiyat kalitesiyle süzer.
        # İlk canlı sürümde AI live kapısı ayrı kilitlidir; paper'da serbest ölçülür.
        "ai_min_token_score": 75,
        "ai_token_gate": "score",               # safety | balanced | score
        "ai_min_liquidity_sol": 0.0,             # 0 = bilinmiyorsa engelleme; canlı token yaşı/fiyat daha önemli
        "ai_max_token_age_minutes": 180,
        "ai_min_token_age_seconds": 30,
        "ai_require_known_token_age": True,
        "ai_require_price": True,
        "ai_live_enabled": False,                # gerçek para AI için ayrıca açılmalı
        "ai_auto_manage": True,                  # AI yaş/skor/fiyat kapılarını otomatik profil ile yönetir
        "ai_risk_profile": "balanced",           # safe | balanced | opportunistic
        "ai_show_advanced": False,                # UI'da ham yaş/skor alanlarını gizle/göster
        "ai_hard_age_gate": False,                # eski ad: gelişmiş manuel yaş kapısı
        "ai_fresh_universe_enabled": True,       # AI evreni varsayılan olarak taze tokenlarla sınırlı
        # --- LİDER ELDE TUTMA BEKÇİSİ ---
        # SELL event'i kaçarsa liderin anlık token bakiyesini kontrol edip bizim
        # açık pozisyonu kapatır. Bu özellikle pump.fun rug riskine karşı canlı
        # güvenlik ağıdır.
        "leader_hold_watch_enabled": True,
        "leader_hold_watch_paper": False,
        "leader_hold_grace_seconds": 20,          # yeni alımdan hemen sonra RPC gecikmesine takılma
        "leader_hold_cooldown_seconds": 20,       # failed sell spam'ini önle
        "leader_hold_max_positions_per_run": 30,
        "leader_hold_zero_threshold": 1e-9,       # dust = tokenden çıktı say
        "leader_hold_exit_ratio": 0.05,           # aldığı miktarın %5'i altına düşerse çık
        "leader_hold_exit_confirmations": 1,      # 1 = hızlı, 2 = daha az false-positive
        "leader_hold_verify_own_balance": True,   # satıştan önce bizim cüzdanda token var mı bak
        "leader_hold_own_zero_threshold": 1e-9,   # bizim cüzdanda bu altı = token yok
        "leader_hold_own_zero_confirmations": 2,  # 2 tur sıfır görmeden ghost kapatma yapma
    },
    "leader_hold_watch_state": {},
    # Cüzdan-bazlı elle SOL override: {cüzdan_adresi: sol_miktarı}
    "copy_overrides": {},
    # Akıllı çıkış için pozisyon başına zirve fiyat + giriş zamanı (otomatik tutulur)
    "position_state": {},
}


def get_setting(db: Session, key: str) -> dict:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        # Varsayılanların üzerine kaydı uygula (yeni alanlar eklendiğinde uyum)
        base = dict(DEFAULTS.get(key, {}))
        if isinstance(row.value, dict):
            base.update(row.value)
            return base
        return row.value
    return dict(DEFAULTS.get(key, {}))


def get_runtime_flag(db: Session, name: str, default: bool) -> bool:
    """Panelden açılıp kapatılabilen çalışma-zamanı bayrağı (DB). Kayıt yoksa
    `default` (genelde .env değeri) döner. Örn. keşif akışını (firehose) canlıyken
    durdurmak için — yeniden derlemeye gerek kalmadan."""
    row = db.query(Setting).filter(Setting.key == "runtime").first()
    if row and isinstance(row.value, dict) and name in row.value:
        return bool(row.value[name])
    return default


def set_runtime_flag(db: Session, name: str, value: bool) -> dict:
    row = db.query(Setting).filter(Setting.key == "runtime").first()
    val = dict(row.value) if row and isinstance(row.value, dict) else {}
    val[name] = bool(value)
    return set_setting(db, "runtime", val)


def set_setting(db: Session, key: str, value: dict) -> dict:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value
    else:
        row = Setting(key=key, value=value)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row.value


def seed_defaults(db: Session) -> None:
    for key, value in DEFAULTS.items():
        if not db.query(Setting).filter(Setting.key == key).first():
            db.add(Setting(key=key, value=value))
    db.commit()
    # wallet_eligibility panelden düzenlenemez; ilk kurulumda DB'ye yazılan eski
    # değerler kod güncellemelerini gölgeliyordu. Her açılışta kod değerine
    # senkronla ki güncel (pump.fun'a uyarlı) kriterler uygulansın.
    elig = db.query(Setting).filter(Setting.key == "wallet_eligibility").first()
    if elig and elig.value != DEFAULTS["wallet_eligibility"]:
        elig.value = DEFAULTS["wallet_eligibility"]
        db.commit()

    # Tek seferlik risk politikası yükseltmesi (v5): GÜVENLİK (safety) işlem kapısı.
    # Saha verisi gösterdi ki "balanced" (≥55) eşiği, takip cüzdanlarının aldığı
    # TAZE token'leri (henüz likidite/holder verisi yok) geçiremiyor → 0 işlem.
    # safety = scam vetosu yoksa işlem aç (cüzdan = alpha). Paper motoru açık.
    # Yalnızca BİR KEZ uygulanır; sonradan paneldeki tercih ezilmez, CANLI'ya
    # (live_confirmed) dokunulmaz.
    if not db.query(Setting).filter(Setting.key == "_meta_risk_policy_v5").first():
        risk = get_setting(db, "risk")
        risk["token_gate"] = "safety"
        if not risk.get("live_confirmed"):
            risk["enabled"] = True
            risk["mode"] = "paper"
        if not risk.get("take_profit_pct"):
            risk["take_profit_pct"] = 0.6
        if not risk.get("stop_loss_pct"):
            risk["stop_loss_pct"] = 0.3
        if risk.get("max_daily_spend_sol", 0) > 1.0:
            risk["max_daily_spend_sol"] = 1.0
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_risk_policy_v5", {"applied": True})

    # v6: İŞLEM-DOSTU hizalama. Takip kararı + safety vetosu zaten kaliteyi
    # belirlediğinden motordaki SKOR engellerini kaldırır (tracked cüzdanın 65-70
    # bandındaki puanı işlemi engellemesin). enabled=paper açık tutulur; CANLI'ya
    # dokunulmaz. Yüksek-frekans/küçük-kâr stratejisine uygundur.
    if not db.query(Setting).filter(Setting.key == "_meta_risk_policy_v6").first():
        risk = get_setting(db, "risk")
        risk["token_gate"] = risk.get("token_gate", "safety") or "safety"
        risk["min_wallet_score"] = 0.0
        risk["min_token_score"] = 0.0
        if not risk.get("live_confirmed"):
            risk["enabled"] = True
            risk["mode"] = "paper"
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_risk_policy_v6", {"applied": True})

    # v7: DAHA ÇOK cüzdan + kopya-performansı elemesi. Takip eşiği 70->65 (paper
    # aşamasında geniş al; kaybedenleri otomatik eleme temizler). Prune varsayılanları
    # mevcut risk kaydına eklenir (panelden değiştirilebilir).
    if not db.query(Setting).filter(Setting.key == "_meta_risk_policy_v7").first():
        th = get_setting(db, "thresholds")
        if float(th.get("wallet", 70.0)) >= 70.0:
            th["wallet"] = 65.0
            set_setting(db, "thresholds", th)
        risk = get_setting(db, "risk")
        risk.setdefault("copy_prune_enabled", True)
        risk.setdefault("copy_max_consecutive_losses", 5)
        risk.setdefault("copy_min_closed_trades", 6)
        risk.setdefault("copy_min_win_rate", 0.30)
        risk.setdefault("paper_trade_sol", 0.01)
        risk.pop("copy_max_drawdown_sol", None)  # SOL miktarına göre yargılama kaldırıldı
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_risk_policy_v7", {"applied": True})

    # v8: GENİŞ AĞ — paper aşamasında çok daha fazla cüzdan takip et. Takip eşiği
    # 65->55 (filtrelerimize takılan ama kâr eden cüzdanları da görüp kopya
    # performansıyla elememiz için). Canlıya geçilmediğinden risk yok; kaybedenleri
    # otomatik eleme + manuel inceleme temizler. CANLI'ya (live_confirmed) dokunulmaz.
    if not db.query(Setting).filter(Setting.key == "_meta_risk_policy_v8").first():
        th = get_setting(db, "thresholds")
        if float(th.get("wallet", 65.0)) >= 60.0:
            th["wallet"] = 55.0
            set_setting(db, "thresholds", th)
        # Geç-giriş koruması artık GERÇEK lag ölçüyor; eski 60sn poll alımlarını
        # boğardı — poll penceresine uygun 600sn'ye yükselt (panelden değişebilir).
        risk = get_setting(db, "risk")
        if int(risk.get("max_follow_lag_seconds", 60)) <= 120:
            risk["max_follow_lag_seconds"] = 600
            set_setting(db, "risk", risk)
        set_setting(db, "_meta_risk_policy_v8", {"applied": True})

    # v9: ELEME ÖLÇÜTÜ win-rate -> kopya PnL. Düşük isabetli ama yüksek kazanç/kayıp
    # oranıyla bize PARA KAZANDIRAN cüzdanlar win-rate eşiğine takılıp eleniyordu.
    # Artık yalnızca bize ZARAR ettiren (kopya PnL < 0) cüzdanlar elenir; win-rate
    # bilgilendirme amaçlı kalır. Ardışık-zarar koruması aynen sürer.
    if not db.query(Setting).filter(Setting.key == "_meta_risk_policy_v9").first():
        risk = get_setting(db, "risk")
        risk.setdefault("copy_min_pnl_sol", 0.0)
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_risk_policy_v9", {"applied": True})

    # v10: HIZLI İZLEME + geçmiş-gün filtresi kaldırma. Cüzdanın 30/1 gün geçmişe
    # sahip olması artık takip için şart değil; copyability + örneklem kalitesi karar
    # verir. Backlog autodrain varsayılan açık gelir ki eski Claude datası hızlı
    # şekilde yeniden skorlanabilsin.
    if not db.query(Setting).filter(Setting.key == "_meta_risk_policy_v10").first():
        elig = get_setting(db, "wallet_eligibility")
        elig["min_history_days"] = 0.0
        set_setting(db, "wallet_eligibility", elig)
        runtime = get_setting(db, "runtime") if db.query(Setting).filter(Setting.key == "runtime").first() else {}
        runtime["backlog_autodrain"] = True
        runtime["discovery_enabled"] = True
        set_setting(db, "runtime", runtime)
        set_setting(db, "_meta_risk_policy_v10", {"applied": True})

    # v11: Copyability eklendikten sonra bazı DB'lerde eski weight kaydı toplamı
    # 1.05 kalmıştı. Scoring kodu normalize etse de panel bunu hata gibi gösterir.
    # Kodla uyumlu 1.00 toplamına senkronla.
    if not db.query(Setting).filter(Setting.key == "_meta_wallet_weights_v11").first():
        weights = get_setting(db, "wallet_weights")
        total = sum(float(v or 0) for v in weights.values()) if isinstance(weights, dict) else 0.0
        if abs(total - 1.0) > 0.001 or set(weights.keys()) != set(WALLET_WEIGHTS.keys()):
            set_setting(db, "wallet_weights", WALLET_WEIGHTS)
        set_setting(db, "_meta_wallet_weights_v11", {"applied": True})

    # v12: CANLIYA GEÇİŞ GÜVENLİ BAŞLANGIÇ. Küçük bakiye testinde yanlışlıkla
    # 0.05+ SOL işlem açılmasın; bayat sinyal de alınmasın. Kullanıcı panelden
    # sonradan yükseltebilir.
    if not db.query(Setting).filter(Setting.key == "_meta_live_safety_v12").first():
        risk = get_setting(db, "risk")
        if float(risk.get("fixed_sol_amount", 0.05) or 0.05) > 0.01:
            risk["fixed_sol_amount"] = 0.01
        if float(risk.get("max_position_sol", 0.2) or 0.2) > 0.01:
            risk["max_position_sol"] = 0.01
        if float(risk.get("max_daily_spend_sol", 1.0) or 1.0) > 0.10:
            risk["max_daily_spend_sol"] = 0.10
        if float(risk.get("max_daily_loss_sol", 0.5) or 0.5) > 0.03:
            risk["max_daily_loss_sol"] = 0.03
        if int(risk.get("max_follow_lag_seconds", 600) or 600) > 30:
            risk["max_follow_lag_seconds"] = 30
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_live_safety_v12", {"applied": True})

    # v13: Zarar sonrası canlı kalite sıkılaştırması. Geniş takip havuzu canlıda
    # çok fazla düşük marjlı/sniper cüzdanı işlem açtırdı. Varsayılanı elite
    # copyability politikasına çeker: copy örneklemi yoksa canlı alım yok, 10sn PnL
    # pozitif ve entry jump düşük olmalı.
    if not db.query(Setting).filter(Setting.key == "_meta_elite_copyability_v13").first():
        elig = get_setting(db, "wallet_eligibility")
        elig.update({
            "min_closed_positions": 10,
            "min_distinct_tokens": 5,
            "min_history_days": 0.0,
            "min_realized_pnl_sol": 0.0,
            "min_profit_factor": 1.15,
            "min_win_rate": 0.40,
            "min_median_hold_seconds": 300,
            "max_short_hold_ratio": 0.55,
            "max_single_trade_pnl_share": 0.60,
            "max_days_since_last_trade": 7,
            "copyability_min_sample": 6,
            "copyability_require_min_sample": False,
            "copyability_min_coverage": 0.55,
            "copyability_max_entry_jump_10s": 0.20,
            "copyability_min_pnl_10s": 0.001,
            "copyability_min_score": 60,
            "copyability_min_profit_factor_10s": 1.25,
            "max_sniper_confidence": 0.50,
            "max_scalper_confidence": 0.50,
        })
        set_setting(db, "wallet_eligibility", elig)
        th = get_setting(db, "thresholds")
        th["wallet"] = max(float(th.get("wallet", 55.0) or 55.0), 72.0)
        th["max_tracked"] = min(int(th.get("max_tracked", 0) or 50), 50) if int(th.get("max_tracked", 0) or 0) > 0 else 50
        set_setting(db, "thresholds", th)
        risk = get_setting(db, "risk")
        risk.update({
            "copyability_require_min_sample": False,
            "copyability_min_coverage": 0.55,
            "copyability_max_entry_jump_10s": 0.20,
            "copyability_min_pnl_10s": 0.001,
            "block_sniper_wallets_live": True,
            "live_min_median_hold_seconds": 300,
            "live_max_short_hold_ratio": 0.55,
            "live_max_sniper_confidence": 0.50,
            "live_max_scalper_confidence": 0.50,
            "live_min_copyability_score": 60,
            "live_min_copy_sample": 6,
            "live_require_copy_sample": True,
            "live_require_positive_copy_pnl_10s": True,
            "live_max_entry_jump_10s": 0.20,
            "live_fresh_token_only": True,
            "live_max_token_age_minutes": 360,
        })
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_elite_copyability_v13", {"applied": True})

    # v14: Canlı güvenlik sıkılaştırması. Kayıp serisi sonrası canlı modda yalnızca
    # gecikmeli copy simülasyonu güçlü, yeterli örneklemli, düşük entry-jump'lı ve
    # taze token işlemleri açılsın. .env'e dokunmaz; sadece DB ayarlarını yükseltir.
    if not db.query(Setting).filter(Setting.key == "_meta_live_safety_v14").first():
        elig = get_setting(db, "wallet_eligibility")
        elig.update({
            "min_closed_positions": 12,
            "min_distinct_tokens": 6,
            "min_history_days": 0.0,
            "min_realized_pnl_sol": 0.0,
            "min_profit_factor": 1.20,
            "min_win_rate": 0.40,
            "min_median_hold_seconds": 300,
            "max_short_hold_ratio": 0.45,
            "max_single_trade_pnl_share": 0.55,
            "max_days_since_last_trade": 7,
            "copyability_min_sample": 6,
            "copyability_require_min_sample": False,
            "copyability_min_coverage": 0.70,
            "copyability_max_entry_jump_10s": 0.15,
            "copyability_min_pnl_10s": 0.001,
            "copyability_min_score": 65,
            "copyability_min_profit_factor_10s": 1.40,
            "max_sniper_confidence": 0.45,
            "max_scalper_confidence": 0.45,
        })
        set_setting(db, "wallet_eligibility", elig)

        th = get_setting(db, "thresholds")
        th["wallet"] = max(float(th.get("wallet", 55.0) or 55.0), 74.0)
        th["max_tracked"] = min(int(th.get("max_tracked", 0) or 40), 40) if int(th.get("max_tracked", 0) or 0) > 0 else 40
        set_setting(db, "thresholds", th)

        risk = get_setting(db, "risk")
        risk.update({
            "copyability_min_sample": 6,
            "copyability_require_min_sample": False,
            "copyability_min_coverage": 0.70,
            "copyability_max_entry_jump_10s": 0.15,
            "copyability_min_pnl_10s": 0.001,
            "block_sniper_wallets_live": True,
            "live_min_median_hold_seconds": 300,
            "live_max_short_hold_ratio": 0.45,
            "live_max_sniper_confidence": 0.45,
            "live_max_scalper_confidence": 0.45,
            "live_min_copyability_score": 65,
            "live_min_copy_sample": 12,
            "live_require_copy_sample": True,
            "live_require_positive_copy_pnl_10s": True,
            "live_max_entry_jump_10s": 0.15,
            "live_fresh_token_only": True,
            "live_max_token_age_minutes": 180,
            "live_min_token_age_seconds": 30,
            "live_require_known_token_age": True,
            "live_min_confluence": 1,
            "fixed_sol_amount": 0.01,
            "max_position_sol": 0.01,
            "max_follow_lag_seconds": min(int(risk.get("max_follow_lag_seconds", 30) or 30), 30),
        })
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_live_safety_v14", {"applied": True})

    # v15: Canlı confluence kapısını kaldır. 2. kaliteli cüzdanı beklemek taze
    # pump.fun tokenlerde girişi geciktirip entry jump riskini artırabilir.
    if not db.query(Setting).filter(Setting.key == "_meta_live_confluence_v15").first():
        risk = get_setting(db, "risk")
        risk["live_min_confluence"] = 1
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_live_confluence_v15", {"applied": True})


    # v16: Lider elde tutma bekçisi. SELL event'i kaçarsa açık canlı copy pozisyonu
    # lider cüzdanın anlık token bakiyesiyle korunur; lider tokenı boşalttıysa
    # bizim pozisyon PumpPortal üzerinden acil kapatılır.
    if not db.query(Setting).filter(Setting.key == "_meta_leader_hold_watch_v16").first():
        risk = get_setting(db, "risk")
        risk.update({
            "leader_hold_watch_enabled": True,
            "leader_hold_watch_paper": False,
            "leader_hold_grace_seconds": 20,
            "leader_hold_cooldown_seconds": 20,
            "leader_hold_max_positions_per_run": 30,
            "leader_hold_zero_threshold": 1e-9,
            "leader_hold_exit_ratio": 0.05,
            "leader_hold_exit_confirmations": 1,
            "leader_hold_verify_own_balance": True,
            "leader_hold_own_zero_threshold": 1e-9,
            "leader_hold_own_zero_confirmations": 2,
        })
        set_setting(db, "risk", risk)
        if not db.query(Setting).filter(Setting.key == "leader_hold_watch_state").first():
            set_setting(db, "leader_hold_watch_state", {})
        set_setting(db, "_meta_leader_hold_watch_v16", {"applied": True})

    # v17: Watchdog ghost pozisyon temizliği. DB açık sanıyor ama gerçek trading
    # cüzdanında token yoksa PumpPortal'a anlamsız sell denemesi yapma; sentetik
    # close ile muhasebeyi temizle.
    if not db.query(Setting).filter(Setting.key == "_meta_leader_hold_ghost_cleanup_v17").first():
        risk = get_setting(db, "risk")
        risk.update({
            "leader_hold_verify_own_balance": True,
            "leader_hold_own_zero_threshold": 1e-9,
            "leader_hold_own_zero_confirmations": 2,
        })
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_leader_hold_ghost_cleanup_v17", {"applied": True})


    # v18: Strateji seçimi + AI Trade varsayılanları. Mevcut DB risk kaydına
    # yeni alanları güvenli şekilde ekler; seçim varsayılan copy kalır.
    if not db.query(Setting).filter(Setting.key == "_meta_risk_policy_v18").first():
        risk = get_setting(db, "risk")
        risk.setdefault("strategy_mode", "copy")
        risk.setdefault("ai_min_token_score", 75)
        risk.setdefault("ai_token_gate", "score")
        risk.setdefault("ai_min_liquidity_sol", 0.0)
        risk.setdefault("ai_max_token_age_minutes", 180)
        risk.setdefault("ai_min_token_age_seconds", 30)
        risk.setdefault("ai_require_known_token_age", True)
        risk.setdefault("ai_require_price", True)
        risk.setdefault("ai_live_enabled", False)
        risk.setdefault("ai_auto_manage", True)
        risk.setdefault("ai_risk_profile", "balanced")
        risk.setdefault("ai_show_advanced", False)
        risk.setdefault("ai_hard_age_gate", False)
        risk.setdefault("ai_fresh_universe_enabled", True)
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_risk_policy_v18", {"applied": True})

    # v19: Mod izolasyonu + AI otomatik yönetim. Mevcut DB'lerde yeni alanları
    # ekler; copy varsayılan kalır ama AI seçilince cüzdan/copy worker'ları erken
    # çıkar.
    if not db.query(Setting).filter(Setting.key == "_meta_mode_isolation_ai_auto_v19").first():
        risk = get_setting(db, "risk")
        risk.setdefault("strategy_mode", "copy")
        risk.setdefault("ai_auto_manage", True)
        risk.setdefault("ai_risk_profile", "balanced")
        risk.setdefault("ai_show_advanced", False)
        risk.setdefault("ai_hard_age_gate", False)
        risk.setdefault("ai_fresh_universe_enabled", True)
        risk.setdefault("ai_live_enabled", False)
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_mode_isolation_ai_auto_v19", {"applied": True})


    # v20: AI Trade yaş kapısı artık manuel hard-block değildir. Yaş bilgisi AI
    # fırsat değerlendirmesinin girdisi olarak kalır; eski token diye AI kararının
    # önünde ayrı bir canlı blok oluşmaz. Copy Trade taze-token kapısı korunur.
    if not db.query(Setting).filter(Setting.key == "_meta_ai_authoritative_age_v20").first():
        risk = get_setting(db, "risk")
        risk["ai_hard_age_gate"] = False
        risk.setdefault("ai_auto_manage", True)
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_ai_authoritative_age_v20", {"applied": True})


    # v21: AI Trade artık "her yaştaki token" taramaz. Yaş filtresi manuel
    # override olarak değil, AI fırsat evreninin parçası olarak çalışır: sistem
    # varsayılan olarak taze launch tokenlarına odaklanır. Eski tokenlar
    # COPY tarafında olduğu gibi değil; AI tarafında "fırsat evreni dışında"
    # sebebiyle ALMADI olarak kayda geçer.
    if not db.query(Setting).filter(Setting.key == "_meta_ai_fresh_universe_v21").first():
        risk = get_setting(db, "risk")
        risk["ai_fresh_universe_enabled"] = True
        risk.setdefault("ai_auto_manage", True)
        # Auto profilde balanced varsayılanı taze fırsata odaklansın. Kullanıcı
        # manuel override açmadıkça ham ayarlar paneli karmaşıklaştırmaz.
        risk.setdefault("ai_risk_profile", "balanced")
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_ai_fresh_universe_v21", {"applied": True})

    # v22: PAPER copy görünürlüğü. Gerçek-zamanlı WS yoksa copy olayları RPC poll
    # ile dakikalar gecikmeyle gelir; tek sıkı max_follow_lag_seconds (30sn) PAPER
    # testinde TÜM copy'leri "gecikme aştı" ile boğuyordu. Moda duyarlı yeni alan:
    # canlı sıkı kalır, paper cömert (300sn) olur ki test işlemleri GÖRÜNÜR.
    if not db.query(Setting).filter(Setting.key == "_meta_paper_follow_lag_v22").first():
        risk = get_setting(db, "risk")
        risk.setdefault("max_follow_lag_seconds_paper", 300)
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_paper_follow_lag_v22", {"applied": True})

    # v23: AKILLI ÇIKIŞ paketi (kademeli TP + likidite watchdog + durgunluk çıkışı).
    # AI'ın zarar kaynağı çıkış yönetimiydi: sabit TP/SL taze tokende ya erken tam
    # satıyor ya rug'da geç kalıyordu. Mevcut kurulumlara varsayılanlar eklenir.
    if not db.query(Setting).filter(Setting.key == "_meta_smart_exit_v23").first():
        risk = get_setting(db, "risk")
        risk.setdefault("partial_tp_pct", 0.35)
        risk.setdefault("partial_tp_fraction", 0.5)
        risk.setdefault("exit_liq_drop_pct", 0.6)
        risk.setdefault("stagnant_exit_minutes", 12)
        risk.setdefault("stagnant_max_pnl_pct", 0.0)
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_smart_exit_v23", {"applied": True})

    # v24: AI PUMP.FUN AVCISI — kademeli giriş + ana-para çıkışı + moonbag.
    if not db.query(Setting).filter(Setting.key == "_meta_ai_hunter_v24").first():
        risk = get_setting(db, "risk")
        for k, v in {
            "ai_hunter_enabled": True,
            "ai_watch_min_score": 70, "ai_scout_min_score": 80,
            "ai_scout_fraction": 0.35, "ai_scout_strong_fraction": 0.55,
            "ai_principal_mult": 2.5, "ai_principal_fee_buffer": 0.08,
            "ai_tp10_mult": 10.0, "ai_tp10_fraction": 0.25,
            "ai_tp25_enabled": False, "ai_tp25_mult": 25.0, "ai_tp25_fraction": 0.18,
            "ai_stop_pre_pct": 0.35, "ai_trail_pre_pct": 0.28, "ai_trail_moon_pct": 0.45,
            "ai_momentum_minutes": 4.0, "ai_momentum_min_mult": 1.3,
            "ai_twox_minutes": 10.0, "ai_twox_min_mult": 2.0,
        }.items():
            risk.setdefault(k, v)
        set_setting(db, "risk", risk)
        set_setting(db, "_meta_ai_hunter_v24", {"applied": True})

def get_strategy_mode(db: Session) -> str:
    """Aktif işlem motoru: copy veya ai. Hatalı/boş değerlerde copy'ye düşer."""
    risk = get_setting(db, "risk")
    mode = str(risk.get("strategy_mode", "copy") or "copy").lower()
    return "ai" if mode == "ai" else "copy"


def is_ai_mode(db: Session) -> bool:
    return get_strategy_mode(db) == "ai"


def is_copy_mode(db: Session) -> bool:
    return get_strategy_mode(db) == "copy"


AI_POLICY_PRESETS: dict[str, dict] = {
    # Güvenli: daha az işlem, daha yüksek token skoru ve ilk saniyeleri bekleme.
    "safe": {
        "ai_min_token_score": 84,
        "ai_token_gate": "score",
        "ai_min_token_age_seconds": 45,
        "ai_max_token_age_minutes": 45,
        "ai_require_known_token_age": True,
        "ai_require_price": True,
        # Likidite ÖLÇÜLEBİLİYORSA taban: sığ havuzda slippage+fee kârı yer.
        # (0/bilinmiyor = engelleme yok; taze bonding tokeni ölçülemez.)
        "ai_min_liquidity_sol": 10.0,
        # Sahiplik yoğunlaşması (ÖLÇÜLEBİLİYORSA): top-10 cüzdan arzın bu
        # yüzdesinden fazlasını tutuyorsa insider/rug riski → alma.
        "ai_max_top10_pct": 35.0,
        "ai_max_insider_pct": 20.0,
        "ai_hard_age_gate": False,
        "ai_fresh_universe_enabled": True,
    },
    # Dengeli: varsayılan. Taze pump potansiyelini kaçırmadan temel güvenlik ister.
    "balanced": {
        "ai_min_token_score": 76,
        "ai_token_gate": "score",
        "ai_min_token_age_seconds": 25,
        "ai_max_token_age_minutes": 90,
        "ai_require_known_token_age": True,
        "ai_require_price": True,
        "ai_min_liquidity_sol": 5.0,
        "ai_max_top10_pct": 45.0,
        "ai_max_insider_pct": 30.0,
        "ai_hard_age_gate": False,
        "ai_fresh_universe_enabled": True,
    },
    # Fırsatçı: daha fazla sinyal üretir; paper araştırma için uygundur.
    "opportunistic": {
        "ai_min_token_score": 68,
        "ai_token_gate": "balanced",
        "ai_min_token_age_seconds": 10,
        "ai_max_token_age_minutes": 180,
        "ai_require_known_token_age": False,
        "ai_require_price": True,
        "ai_min_liquidity_sol": 2.0,
        "ai_max_top10_pct": 60.0,
        "ai_max_insider_pct": 45.0,
        "ai_hard_age_gate": False,
        "ai_fresh_universe_enabled": True,
    },
}


def resolve_ai_policy(risk: dict) -> dict:
    """AI Trade için etkin karar profilini döndürür.

    Kullanıcı ana ekranda 'risk profili' seçer; token yaşı/skor/fiyat gibi ham
    değerleri varsayılan olarak AI otomatik yönetir. `ai_auto_manage=False` ise
    paneldeki manuel override değerleri aynen kullanılır.
    """
    if not bool(risk.get("ai_auto_manage", True)):
        return {
            "ai_min_token_score": float(risk.get("ai_min_token_score", 75) or 75),
            "ai_token_gate": str(risk.get("ai_token_gate", "score") or "score"),
            "ai_min_token_age_seconds": float(risk.get("ai_min_token_age_seconds", 30) or 0),
            "ai_max_token_age_minutes": float(risk.get("ai_max_token_age_minutes", 180) or 0),
            "ai_require_known_token_age": bool(risk.get("ai_require_known_token_age", True)),
            "ai_require_price": bool(risk.get("ai_require_price", True)),
            "ai_min_liquidity_sol": float(risk.get("ai_min_liquidity_sol", 0.0) or 0.0),
            "ai_max_top10_pct": float(risk.get("ai_max_top10_pct", 0.0) or 0.0),
            "ai_max_insider_pct": float(risk.get("ai_max_insider_pct", 0.0) or 0.0),
            "ai_hard_age_gate": bool(risk.get("ai_hard_age_gate", False)),
            "ai_fresh_universe_enabled": bool(risk.get("ai_fresh_universe_enabled", True)),
            "source": "manual",
            "profile": "manual",
        }
    profile = str(risk.get("ai_risk_profile", "balanced") or "balanced").lower()
    if profile not in AI_POLICY_PRESETS:
        profile = "balanced"
    out = dict(AI_POLICY_PRESETS[profile])
    out["source"] = "auto"
    out["profile"] = profile
    return out



def all_settings(db: Session) -> dict[str, dict]:
    return {key: get_setting(db, key) for key in DEFAULTS}


# Hazır risk profilleri — panelden tek tıkla uygulanır.
RISK_PROFILES: dict[str, dict] = {
    "temkinli": {
        "fixed_sol_amount": 0.02, "max_position_sol": 0.05, "max_daily_spend_sol": 0.3,
        "max_daily_loss_sol": 0.1, "max_slippage": 0.08, "min_wallet_score": 80,
        "min_token_score": 80, "min_liquidity_sol": 15, "max_open_positions_per_token": 1,
        "take_profit_pct": 0.4, "stop_loss_pct": 0.25,
    },
    "dengeli": {
        "fixed_sol_amount": 0.05, "max_position_sol": 0.2, "max_daily_spend_sol": 1.0,
        "max_daily_loss_sol": 0.5, "max_slippage": 0.15, "min_wallet_score": 70,
        "min_token_score": 70, "min_liquidity_sol": 5, "max_open_positions_per_token": 1,
        "take_profit_pct": 0.6, "stop_loss_pct": 0.3,
    },
    "agresif": {
        "fixed_sol_amount": 0.1, "max_position_sol": 0.5, "max_daily_spend_sol": 3.0,
        "max_daily_loss_sol": 1.5, "max_slippage": 0.25, "min_wallet_score": 65,
        "min_token_score": 65, "min_liquidity_sol": 3, "max_open_positions_per_token": 2,
        "take_profit_pct": 1.0, "stop_loss_pct": 0.35,
    },
}


def apply_risk_profile(db: Session, name: str) -> dict:
    preset = RISK_PROFILES.get(name)
    if preset is None:
        raise KeyError(name)
    risk = get_setting(db, "risk")
    risk.update(preset)
    return set_setting(db, "risk", risk)


def set_heartbeat(db: Session, key: str = "listener_heartbeat") -> None:
    from datetime import datetime, timezone
    set_setting(db, "_meta_" + key, {"ts": datetime.now(timezone.utc).isoformat()})


def get_heartbeat(db: Session, key: str = "listener_heartbeat") -> str | None:
    row = db.query(Setting).filter(Setting.key == "_meta_" + key).first()
    return (row.value or {}).get("ts") if row else None
