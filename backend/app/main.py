"""
Proxmox Manager - FastAPI entrypoint.

Registers all routers, the WebSocket stats endpoint and a healthcheck.
"""

import logging
import os

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .config import settings, ensure_fernet_key
from .database import Base, engine
from .websocket import stream_stats
from .routers import (
    auth_router, credentials, cluster, vms, snapbackup, tasks_router,
)


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s :: %(message)s")

app = FastAPI(title="Proxmox Manager", version="0.1.0", docs_url="/api/docs",
              redoc_url=None, openapi_url="/api/openapi.json")


# CORS - frontend and backend are served from the same origin in production
# but during local dev (e.g. vite on 5173) you may want permissive settings.
origins = [o.strip() for o in (settings.CORS_ORIGINS or "*").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    ensure_fernet_key()       # generate + persist key on first run
    Base.metadata.create_all(bind=engine)  # no-op if init.sql already ran


@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version}


# ---------- Routers ----------

app.include_router(auth_router.router)
app.include_router(credentials.router)
app.include_router(cluster.router)
app.include_router(vms.router)
app.include_router(snapbackup.router)
app.include_router(tasks_router.router)


# ---------- WebSocket for live stats ----------

@app.websocket("/api/ws/stats")
async def ws_stats(ws: WebSocket, token: str = ""):
    await stream_stats(ws, token)
