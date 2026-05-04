"""
Proxmox Manager - FastAPI entrypoint.

Registers all routers, the WebSocket stats endpoint and a healthcheck.
"""

import logging
import os

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .config import settings, ensure_fernet_key
from .database import Base, engine, SessionLocal
from .websocket import stream_stats
from .routers import (
    auth_router, users_router, credentials, cluster, vms,
    snapbackup, tasks_router, create,
)


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Proxmox Manager", version="1.0.0", docs_url="/api/docs",
              redoc_url=None, openapi_url="/api/openapi.json")


# CORS
origins = [o.strip() for o in (settings.CORS_ORIGINS or "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _seed_admin() -> None:
    """
    Crea l'utente admin di default se il database è vuoto.
    Username e password sono configurabili via env:
      ADMIN_USERNAME  (default: admin)
      ADMIN_PASSWORD  (default: admin)
    """
    from .models import User
    from .crypto import hash_password

    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin")

    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            admin = User(
                username=username,
                full_name="Amministratore",
                email="",
                password_hash=hash_password(password),
                role="admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            logger.info(
                "Utente admin creato → username: '%s'  password: '%s'  "
                "(cambia la password dopo il primo accesso!)",
                username, password,
            )
        else:
            logger.info("Database già inizializzato — seed admin saltato.")
    except Exception as exc:
        logger.error("Errore durante il seed admin: %s", exc)
        db.rollback()
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    ensure_fernet_key()                      # genera/carica la chiave Fernet
    Base.metadata.create_all(bind=engine)    # crea le tabelle se non esistono
    _seed_admin()                            # crea l'admin di default al primo avvio


@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version}


# ---------- Routers ----------

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(credentials.router)
app.include_router(cluster.router)
app.include_router(vms.router)
app.include_router(snapbackup.router)
app.include_router(tasks_router.router)
app.include_router(create.router)


# ---------- WebSocket for live stats ----------

@app.websocket("/api/ws/stats")
async def ws_stats(ws: WebSocket, token: str = ""):
    await stream_stats(ws, token)
