"""
Background migration runner.

A migration in Proxmox is an asynchronous PVE task identified by a UPID.
We kick it off, then poll its status/log endpoints from a FastAPI BackgroundTask
to update progress in the DB, which the UI fetches via /api/tasks.
"""

from __future__ import annotations

import re
import time
import uuid
import logging
from typing import Optional

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import ProxmoxCredential, MigrationTask
from .proxmox_client import build_client, vm_migrate, task_status, task_log


log = logging.getLogger(__name__)
PROGRESS_RE = re.compile(r"(\d{1,3})\s*%")


def start_migration(
    user_id: int,
    cred: ProxmoxCredential,
    node: str,
    vmid: int,
    kind: str,
    target_node: str,
    online: bool = True,
    with_local_disks: bool = True,
) -> MigrationTask:
    """Create DB row, launch PVE migration, return the task row (status=running)."""
    px = build_client(cred)
    upid = vm_migrate(px, node, vmid, target_node, kind=kind,
                      online=online, with_local_disks=with_local_disks)
    row = MigrationTask(
        id=uuid.uuid4().hex,
        user_id=user_id,
        cred_id=cred.id,
        vmid=vmid,
        kind=kind,
        source_node=node,
        target_node=target_node,
        status="running",
        progress=1,
        upid=upid,
        message="migration started",
    )
    db: Session = SessionLocal()
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def poll_migration(task_id: str, cred_id: int, max_seconds: int = 60 * 60) -> None:
    """Run in a BackgroundTask thread: poll PVE until the task finishes."""
    db: Session = SessionLocal()
    try:
        task = db.query(MigrationTask).get(task_id)
        cred = db.query(ProxmoxCredential).get(cred_id)
        if not task or not cred:
            return
        px = build_client(cred)
        started = time.time()

        while time.time() - started < max_seconds:
            try:
                st = task_status(px, task.source_node, task.upid)
            except Exception as e:
                log.warning("task_status failed: %s", e)
                time.sleep(2)
                continue

            status = st.get("status", "running")
            exitstatus = st.get("exitstatus")

            # Parse progress from the log
            try:
                lines = task_log(px, task.source_node, task.upid, start=0, limit=500)
                highest = task.progress
                for entry in lines:
                    text = entry.get("t") or entry.get("text") or ""
                    m = PROGRESS_RE.search(text)
                    if m:
                        highest = max(highest, int(m.group(1)))
                task.progress = min(highest, 99 if status == "running" else 100)
                if lines:
                    tail = lines[-1]
                    task.message = tail.get("t") or tail.get("text") or task.message
            except Exception as e:
                log.debug("task_log failed: %s", e)

            if status == "stopped":
                if exitstatus == "OK":
                    task.status = "success"
                    task.progress = 100
                    task.message = "migration completed"
                else:
                    task.status = "failed"
                    task.message = f"exit: {exitstatus}"
                db.commit()
                return

            db.commit()
            time.sleep(2)

        task.status = "timeout"
        task.message = "polling timed out"
        db.commit()
    finally:
        db.close()
