"""
VM / CT management endpoints. `kind` is always 'qemu' or 'lxc'.

Role gates:
- read:    any authenticated user
- power (start/stop/shutdown/reboot): senior+
- clone:   senior+
- migrate: senior+
- delete:  admin only
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user, require_senior, require_admin
from ..models import User, ProxmoxCredential
from ..schemas import CloneIn, MigrateIn, DeleteConfirmIn, MigrationTaskOut, VMConfigUpdateIn
from ..proxmox_client import (
    build_client, vm_current, vm_config, vm_rrddata,
    vm_start, vm_stop, vm_shutdown, vm_reboot, vm_delete, vm_clone,
    vm_update_config,
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


# ---------- Power (senior+) ----------

def _action(fn, cred, node, vmid, kind):
    return {"upid": fn(build_client(cred), node, vmid, _kind(kind))}


@router.post("/{kind}/{node}/{vmid}/start")
def start(cred_id: int, kind: str, node: str, vmid: int,
          db: Session = Depends(get_db), user: User = Depends(require_senior)):
    return _action(vm_start, _get_cred(db, user, cred_id), node, vmid, kind)


@router.post("/{kind}/{node}/{vmid}/stop")
def stop(cred_id: int, kind: str, node: str, vmid: int,
         db: Session = Depends(get_db), user: User = Depends(require_senior)):
    return _action(vm_stop, _get_cred(db, user, cred_id), node, vmid, kind)


@router.post("/{kind}/{node}/{vmid}/shutdown")
def shutdown(cred_id: int, kind: str, node: str, vmid: int,
             db: Session = Depends(get_db), user: User = Depends(require_senior)):
    return _action(vm_shutdown, _get_cred(db, user, cred_id), node, vmid, kind)


@router.post("/{kind}/{node}/{vmid}/reboot")
def reboot(cred_id: int, kind: str, node: str, vmid: int,
           db: Session = Depends(get_db), user: User = Depends(require_senior)):
    return _action(vm_reboot, _get_cred(db, user, cred_id), node, vmid, kind)


# ---------- Destructive (admin only) ----------

@router.post("/{kind}/{node}/{vmid}/delete")
def delete(cred_id: int, kind: str, node: str, vmid: int, body: DeleteConfirmIn,
           db: Session = Depends(get_db), user: User = Depends(require_admin)):
    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)
    current_info = vm_current(px, node, vmid, _kind(kind))
    real_name = current_info.get("name", "")
    if body.confirm_name.strip() != real_name:
        raise HTTPException(400, f"Confirmation name does not match (expected '{real_name}')")
    if current_info.get("status") == "running":
        raise HTTPException(409, "Stop the guest before deleting")
    return {"upid": vm_delete(px, node, vmid, _kind(kind))}


# ---------- Config update (senior+) ----------

@router.put("/{kind}/{node}/{vmid}/config")
def update_config(cred_id: int, kind: str, node: str, vmid: int, body: VMConfigUpdateIn,
                  db: Session = Depends(get_db), user: User = Depends(require_senior)):
    """Live-update CPU, memory, boot flag, and description of a VM/CT."""
    cred = _get_cred(db, user, cred_id)
    k = _kind(kind)
    params: dict = {}
    if body.cores       is not None: params["cores"]       = body.cores
    if body.memory      is not None: params["memory"]      = body.memory
    if body.onboot      is not None: params["onboot"]      = 1 if body.onboot else 0
    if body.description is not None: params["description"] = body.description
    if body.cpulimit    is not None: params["cpulimit"]    = body.cpulimit
    if body.balloon     is not None: params["balloon"]     = body.balloon
    if k == "qemu":
        if body.sockets  is not None: params["sockets"]  = body.sockets
        if body.name     is not None: params["name"]     = body.name
    else:
        if body.swap     is not None: params["swap"]     = body.swap
        if body.hostname is not None: params["hostname"] = body.hostname
    if not params:
        raise HTTPException(400, "No parameters to update")
    result = vm_update_config(build_client(cred), node, vmid, k, params)
    return {"upid": result, "updated": list(params.keys())}


# ---------- Clone (senior+) ----------

@router.post("/{kind}/{node}/{vmid}/clone")
def clone(cred_id: int, kind: str, node: str, vmid: int, body: CloneIn,
          db: Session = Depends(get_db), user: User = Depends(require_senior)):
    cred = _get_cred(db, user, cred_id)
    return {"upid": vm_clone(
        build_client(cred), node, vmid, newid=body.newid, kind=_kind(kind),
        target=body.target_node, name=body.name, full=body.full,
    )}


# ---------- Migration (senior+) ----------

@router.post("/{kind}/{node}/{vmid}/migrate", response_model=MigrationTaskOut)
def migrate(cred_id: int, kind: str, node: str, vmid: int, body: MigrateIn,
            bg: BackgroundTasks,
            db: Session = Depends(get_db), user: User = Depends(require_senior)):
    cred = _get_cred(db, user, cred_id)
    task = start_migration(
        user_id=user.id, cred=cred, node=node, vmid=vmid, kind=_kind(kind),
        target_node=body.target_node, online=body.online,
        with_local_disks=body.with_local_disks,
    )
    bg.add_task(poll_migration, task.id, cred.id)
    return task
