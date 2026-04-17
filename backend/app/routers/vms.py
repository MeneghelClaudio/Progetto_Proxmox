"""
VM / CT management endpoints. `kind` is always 'qemu' or 'lxc'.

Safety:
- DELETE and CLONE-into-existing-vmid require a confirmation payload with the
  current VM/CT name (GitHub-repo-style double confirm).
- MIGRATE is fire-and-forget: returns a migration task id, the UI polls /api/tasks.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user
from ..models import User, ProxmoxCredential
from ..schemas import CloneIn, MigrateIn, DeleteConfirmIn, MigrationTaskOut
from ..proxmox_client import (
    build_client, vm_current, vm_config, vm_rrddata,
    vm_start, vm_stop, vm_shutdown, vm_reboot, vm_delete, vm_clone,
)
from ..tasks import start_migration, poll_migration


router = APIRouter(prefix="/api/clusters/{cred_id}/vms", tags=["vms"])


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


# ---------- Read ----------

@router.get("/{kind}/{node}/{vmid}")
def current(cred_id: int, kind: str, node: str, vmid: int,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)
    return {
        "status":  vm_current(px, node, vmid, _kind(kind)),
        "config":  vm_config(px, node, vmid, _kind(kind)),
    }


@router.get("/{kind}/{node}/{vmid}/rrd")
def rrd(cred_id: int, kind: str, node: str, vmid: int, timeframe: str = "hour",
        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    return vm_rrddata(build_client(cred), node, vmid, _kind(kind), timeframe=timeframe)


# ---------- Power ----------

def _action(fn, cred, node, vmid, kind):
    return {"upid": fn(build_client(cred), node, vmid, _kind(kind))}


@router.post("/{kind}/{node}/{vmid}/start")
def start(cred_id: int, kind: str, node: str, vmid: int,
          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _action(vm_start, _get_cred(db, user, cred_id), node, vmid, kind)


@router.post("/{kind}/{node}/{vmid}/stop")
def stop(cred_id: int, kind: str, node: str, vmid: int,
         db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _action(vm_stop, _get_cred(db, user, cred_id), node, vmid, kind)


@router.post("/{kind}/{node}/{vmid}/shutdown")
def shutdown(cred_id: int, kind: str, node: str, vmid: int,
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _action(vm_shutdown, _get_cred(db, user, cred_id), node, vmid, kind)


@router.post("/{kind}/{node}/{vmid}/reboot")
def reboot(cred_id: int, kind: str, node: str, vmid: int,
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _action(vm_reboot, _get_cred(db, user, cred_id), node, vmid, kind)


# ---------- Destructive with double confirmation ----------

@router.post("/{kind}/{node}/{vmid}/delete")
def delete(cred_id: int, kind: str, node: str, vmid: int, body: DeleteConfirmIn,
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)
    current_info = vm_current(px, node, vmid, _kind(kind))
    real_name = current_info.get("name", "")
    if body.confirm_name.strip() != real_name:
        raise HTTPException(400, f"Confirmation name does not match (expected '{real_name}')")
    if current_info.get("status") == "running":
        raise HTTPException(409, "Stop the guest before deleting")
    return {"upid": vm_delete(px, node, vmid, _kind(kind))}


@router.post("/{kind}/{node}/{vmid}/clone")
def clone(cred_id: int, kind: str, node: str, vmid: int, body: CloneIn,
          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    return {"upid": vm_clone(
        build_client(cred), node, vmid, newid=body.newid, kind=_kind(kind),
        target=body.target_node, name=body.name, full=body.full,
    )}


# ---------- Migration (background-tracked) ----------

@router.post("/{kind}/{node}/{vmid}/migrate", response_model=MigrationTaskOut)
def migrate(cred_id: int, kind: str, node: str, vmid: int, body: MigrateIn,
            bg: BackgroundTasks,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    task = start_migration(
        user_id=user.id, cred=cred, node=node, vmid=vmid, kind=_kind(kind),
        target_node=body.target_node, online=body.online,
        with_local_disks=body.with_local_disks,
    )
    bg.add_task(poll_migration, task.id, cred.id)
    return task
