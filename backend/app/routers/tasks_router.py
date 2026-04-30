"""
Tasks endpoints for the bottom task bar.

The UI polls /api/tasks?active=true every few seconds to render progress.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..auth import get_current_user
from ..models import User, MigrationTask, ProxmoxCredential
from ..schemas import MigrationTaskOut
from ..proxmox_client import build_client, task_log as _pve_task_log


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=List[MigrationTaskOut])
def list_tasks(active: bool = False, limit: int = 50,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(MigrationTask).filter(MigrationTask.user_id == user.id)
    if active:
        q = q.filter(MigrationTask.status.in_(["pending", "running"]))
    return q.order_by(MigrationTask.created_at.desc()).limit(limit).all()


@router.get("/{task_id}/log")
def get_task_log(task_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """
    Return the full Proxmox task log for a migration task.
    Used by the frontend to show detailed error information.
    """
    row = db.query(MigrationTask).filter(
        MigrationTask.id == task_id, MigrationTask.user_id == user.id,
    ).first()
    if not row:
        raise HTTPException(404, "Task not found")
    if not row.upid or not row.source_node:
        return {"lines": [], "raw": ""}

    cred = db.query(ProxmoxCredential).filter(
        ProxmoxCredential.id == row.cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "Credential not found")

    try:
        px    = build_client(cred)
        lines = _pve_task_log(px, row.source_node, row.upid, start=0, limit=1000)
        texts = [entry.get("t") or entry.get("text") or "" for entry in lines]
        return {"lines": texts, "raw": "\n".join(texts)}
    except Exception as exc:
        raise HTTPException(502, f"Impossibile recuperare il log Proxmox: {exc}")


@router.post("/{task_id}/stop")
def stop_task(task_id: str, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """
    Abort a running migration task.

    Sends a SIGTERM to the Proxmox task process via
    DELETE /nodes/{node}/tasks/{upid}, then immediately marks the DB row as
    failed so the UI updates without waiting for the next poll cycle.

    The background poll_migration loop will also detect the stopped state and
    handle HA restore / CD-ROM re-attach — stopping the task here does not
    short-circuit that cleanup.
    """
    row = db.query(MigrationTask).filter(
        MigrationTask.id == task_id, MigrationTask.user_id == user.id,
    ).first()
    if not row:
        raise HTTPException(404, "Task not found")
    if row.status not in ("pending", "running"):
        raise HTTPException(400, "Il task non è in esecuzione")
    if not row.upid or not row.source_node:
        raise HTTPException(400, "Task senza UPID — impossibile fermarlo")

    cred = db.query(ProxmoxCredential).filter(
        ProxmoxCredential.id == row.cred_id,
    ).first()
    if not cred:
        raise HTTPException(404, "Credential not found")

    try:
        px = build_client(cred)
        # Proxmox: DELETE /nodes/{node}/tasks/{upid} → SIGTERM to the task
        px.nodes(row.source_node).tasks(row.upid).delete()
    except Exception as exc:
        raise HTTPException(502, f"Impossibile fermare il task Proxmox: {exc}")

    row.status  = "failed"
    row.message = "migrazione annullata dall'utente"
    db.commit()

    return {"stopped": True, "task_id": task_id}


@router.delete("/{task_id}", status_code=204)
def dismiss_task(task_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    row = db.query(MigrationTask).filter(
        MigrationTask.id == task_id, MigrationTask.user_id == user.id,
    ).first()
    if row and row.status not in ("pending", "running"):
        db.delete(row)
        db.commit()
