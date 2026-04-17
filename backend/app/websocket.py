"""
Push live stats (CPU / RAM / disk / net) over WebSocket once per second.

The client sends an initial JSON message:
    {"type": "subscribe", "cred_id": 1, "target": "node/pve1"}
    {"type": "subscribe", "cred_id": 1, "target": "qemu/pve1/100"}
    {"type": "subscribe", "cred_id": 1, "target": "lxc/pve1/201"}

The server pushes at 1 Hz:
    {"t": 1712000000, "cpu": 0.12, "mem": 0.34, "memBytes": ..., "disk": 0.56,
     "netin": 1234, "netout": 456, "status": "running"}

Internally we simply poll the PVE REST API; keeping it at 1 s is safe for small
homelab clusters, tune via POLL_INTERVAL env var.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import ProxmoxCredential
from .auth import ws_user_from_token
from .proxmox_client import build_client, vm_current, node_status


POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))


async def stream_stats(ws: WebSocket, token: str) -> None:
    """Main loop for a single WebSocket connection."""
    db: Session = SessionLocal()
    try:
        user = ws_user_from_token(token, db)
        if not user:
            await ws.close(code=1008)
            return
        await ws.accept()

        subscription: dict[str, Any] | None = None
        cred: ProxmoxCredential | None = None
        client = None

        async def reader():
            nonlocal subscription, cred, client
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "subscribe":
                    cred_id = int(msg["cred_id"])
                    cred = db.query(ProxmoxCredential).filter(
                        ProxmoxCredential.id == cred_id,
                        ProxmoxCredential.user_id == user.id,
                    ).first()
                    if not cred:
                        await ws.send_json({"error": "credential not found"})
                        continue
                    client = build_client(cred)
                    subscription = {"target": msg["target"]}

        async def pusher():
            while True:
                await asyncio.sleep(POLL_INTERVAL)
                if not subscription or not client:
                    continue
                try:
                    payload = _sample(client, subscription["target"])
                    payload["t"] = int(time.time())
                    await ws.send_json(payload)
                except Exception as e:
                    await ws.send_json({"error": str(e), "t": int(time.time())})

        await asyncio.gather(reader(), pusher())

    except WebSocketDisconnect:
        pass
    finally:
        db.close()


def _sample(client, target: str) -> dict[str, Any]:
    """Take a single point from Proxmox for the given target."""
    parts = target.split("/")
    if parts[0] == "node":
        _, node = parts
        s = node_status(client, node)
        total_mem = s.get("memory", {}).get("total", 1) or 1
        used_mem = s.get("memory", {}).get("used", 0) or 0
        total_root = s.get("rootfs", {}).get("total", 1) or 1
        used_root = s.get("rootfs", {}).get("used", 0) or 0
        return {
            "cpu": float(s.get("cpu", 0.0)),
            "mem": used_mem / total_mem,
            "memBytes": used_mem,
            "memTotal": total_mem,
            "disk": used_root / total_root,
            "uptime": s.get("uptime", 0),
            "loadavg": s.get("loadavg", []),
            "status": "online",
        }
    elif parts[0] in ("qemu", "lxc"):
        _, node, vmid = parts
        s = vm_current(client, node, int(vmid), kind=parts[0])
        maxmem = s.get("maxmem", 1) or 1
        mem = s.get("mem", 0) or 0
        maxdisk = s.get("maxdisk", 1) or 1
        disk = s.get("disk", 0) or 0
        return {
            "cpu": float(s.get("cpu", 0.0)),
            "mem": mem / maxmem,
            "memBytes": mem,
            "memTotal": maxmem,
            "disk": disk / maxdisk,
            "netin": s.get("netin", 0),
            "netout": s.get("netout", 0),
            "diskread": s.get("diskread", 0),
            "diskwrite": s.get("diskwrite", 0),
            "status": s.get("status", "unknown"),
            "uptime": s.get("uptime", 0),
        }
    return {"error": f"unknown target {target}"}
