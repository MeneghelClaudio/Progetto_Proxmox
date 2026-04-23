"""
Snapshots (per guest) and backups (per storage) endpoints.

Role gates:
- read (list): any authenticated user
- create snapshot / backup:   senior+
- delete snapshot:            admin only
- rollback snapshot:          senior+
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user, require_senior, require_admin
from ..models import User, ProxmoxCredential
from ..schemas import SnapshotCreateIn, BackupIn
from ..proxmox_client import (
    build_client, snapshots_list, snapshot_create,
    snapshot_delete, snapshot_rollback,
    backup_create, backup_list,
)


router = APIRouter(prefix="/api/clusters/{cred_id}", tags=["snapshots-backups"])


def _get_cred(db: Session, user: User, cred_id: int) -> ProxmoxCredential:
    cred = db.query(ProxmoxCredential).filter(
        ProxmoxCredential.id == cred_id,
        ProxmoxCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(404, "Credential not found")
    return cred


def _kind(kind: str) -> str:
    if kind not in ("qemu", "lxc"):
        raise HTTPException(400, "kind must be 'qemu' or 'lxc'")
    return kind


# ---------- Snapshots ----------

@router.get("/snapshots/{kind}/{node}/{vmid}")
def list_snapshots(cred_id: int, kind: str, node: str, vmid: int,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    return snapshots_list(build_client(cred), node, vmid, _kind(kind))


@router.post("/snapshots/{kind}/{node}/{vmid}")
def create_snapshot(cred_id: int, kind: str, node: str, vmid: int, body: SnapshotCreateIn,
                    db: Session = Depends(get_db), user: User = Depends(require_senior)):
    cred = _get_cred(db, user, cred_id)
    return {"upid": snapshot_create(
        build_client(cred), node, vmid,
        snapname=body.snapname, description=body.description or "",
        vmstate=body.vmstate, kind=_kind(kind),
    )}


@router.delete("/snapshots/{kind}/{node}/{vmid}/{snapname}")
def delete_snapshot(cred_id: int, kind: str, node: str, vmid: int, snapname: str,
                    db: Session = Depends(get_db), user: User = Depends(require_admin)):
    cred = _get_cred(db, user, cred_id)
    return {"upid": snapshot_delete(build_client(cred), node, vmid, snapname, _kind(kind))}


@router.post("/snapshots/{kind}/{node}/{vmid}/{snapname}/rollback")
def rollback_snapshot(cred_id: int, kind: str, node: str, vmid: int, snapname: str,
                      db: Session = Depends(get_db), user: User = Depends(require_senior)):
    cred = _get_cred(db, user, cred_id)
    return {"upid": snapshot_rollback(build_client(cred), node, vmid, snapname, _kind(kind))}


# ---------- Backups ----------

@router.post("/backups/{node}/{vmid}")
def create_backup(cred_id: int, node: str, vmid: int, body: BackupIn,
                  db: Session = Depends(get_db), user: User = Depends(require_senior)):
    cred = _get_cred(db, user, cred_id)
    return {"upid": backup_create(
        build_client(cred), node, vmid,
        storage=body.storage, mode=body.mode,
        compress=body.compress, notes=body.notes,
    )}


@router.get("/backups/{node}/{storage}")
def list_backups(cred_id: int, node: str, storage: str, vmid: int | None = None,
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    return backup_list(build_client(cred), node, storage, vmid=vmid)
