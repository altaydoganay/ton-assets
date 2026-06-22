"""FastAPI uygulaması — Pump.fun Cüzdan & Token Analizcisi API'si."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .security.logging_filters import install_redaction
from .api.routes_wallets import router as wallets_router
from .api.routes_tokens import router as tokens_router
from .api.routes_misc import (
    alerts_router,
    events_router,
    health_router,
    logs_router,
    settings_router,
    trading_router,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
install_redaction()  # tüm loglarda gizli bilgi maskeleme

@asynccontextmanager
async def lifespan(_app: FastAPI):
    from .database import SessionLocal
    from .services.settings_service import seed_defaults

    db = SessionLocal()
    try:
        seed_defaults(db)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("Varsayılan ayarlar yüklenemedi: %s", exc)
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Pump.fun ve Solana üzerinde başarılı cüzdan/token analizi, bildirim ve isteğe bağlı kopya işlem.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

prefix = settings.api_prefix
for r in (
    wallets_router,
    tokens_router,
    events_router,
    alerts_router,
    trading_router,
    settings_router,
    logs_router,
    health_router,
):
    app.include_router(r, prefix=prefix)


@app.get("/")
def root() -> dict:
    return {"name": settings.app_name, "docs": "/docs", "api": settings.api_prefix}
