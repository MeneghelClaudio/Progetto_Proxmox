"""
Snapshots (per guest) and backups (per storage) endpoints.

Role gates:
- read (list): any authenticated user
- create snapshot / backup:   senior+
- delete snapshot:            admin only
- rollback snapshot:          senior+
"""

import re as _re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user, require_senior, require_admin
from ..models import User, ProxmoxCredential
from ..schemas import SnapshotCreateIn, BackupIn, PBSAddIn
from ..proxmox_client import (
    build_client, snapshots_list, snapshot_create,
    snapshot_delete, snapshot_rollback,
    backup_create, backup_list,
    task_status as _task_status, task_log as _task_log,
)

_PROGRESS_RE = _re.compile(r"(\d{1,3})\s*%")


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


@router.delete("/backups/{node}/{storage}/content", status_code=200)
def delete_backup(
    cred_id: int,
    node: str,
    storage: str,
    volid: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """
    Elimina un backup dallo storage Proxmox / PBS.

    volid: identificatore completo del volume, es.
      Proxmox-Buckup-Server:backup/ct/102/2026-05-04T08:56:14Z
      local:backup/vzdump-qemu-103-2026_05_04-09_06_09.vma.zst

    Richiede ruolo admin.
    """
    cred = _get_cred(db, user, cred_id)
    px   = build_client(cred)
    try:
        px.nodes(node).storage(storage).content(volid).delete()
    except Exception as exc:
        msg = str(exc)
        if "404" in msg or "does not exist" in msg.lower():
            raise HTTPException(404, "Backup non trovato")
        raise HTTPException(400, f"Impossibile eliminare il backup: {msg}")
    return {"deleted": True, "volid": volid}


# ---------- Proxmox Backup Server ----------

@router.post("/pbs", status_code=201)
def add_pbs_storage(
    cred_id: int,
    body: PBSAddIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_senior),
):
    """
    Aggiunge un Proxmox Backup Server come storage nel nodo/cluster Proxmox
    identificato da cred_id.

    Chiama POST /storage sul datacenter PVE con type=pbs.  Se il nodo appartiene
    a un cluster, lo storage diventa visibile su tutti i nodi del cluster.

    Richiede ruolo senior o admin.
    """
    cred = _get_cred(db, user, cred_id)
    px   = build_client(cred)

    params: dict = {
        "storage":   body.storage_id,
        "type":      "pbs",
        "server":    body.server,
        "datastore": body.datastore,
        "username":  body.username,
        "password":  body.password,
        "port":      body.port,
        "content":   "backup",
    }
    params["fingerprint"] = body.fingerprint

    try:
        px.storage.post(**params)
    except Exception as exc:
        msg = str(exc)
        if "already exists" in msg.lower() or "duplicate" in msg.lower():
            raise HTTPException(409, f"Uno storage con ID '{body.storage_id}' esiste già su questo server")
        raise HTTPException(400, f"Impossibile aggiungere il PBS: {msg}")

    return {"storage": body.storage_id, "server": body.server, "status": "added"}


# ---------- Task status polling (backup / snapshot) ----------

@router.get("/pvetask")
def poll_pve_task(
    cred_id: int,
    node: str,
    upid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Restituisce lo stato aggiornato di un task Proxmox (UPID) per backup/snapshot.

    Risposta:
      running   bool   – il task è ancora in esecuzione
      ok        bool   – completato con successo
      error     bool   – terminato con errore
      progress  int    – percentuale 0-100 (da log se disponibile, altrimenti 0)
      last_log  str    – ultima riga del log Proxmox
      exitstatus str|None
    """
    cred = _get_cred(db, user, cred_id)
    px   = build_client(cred)

    try:
        st = _task_status(px, node, upid)
    except Exception as exc:
        raise HTTPException(502, f"Impossibile leggere lo stato del task: {exc}")

    status     = st.get("status", "running")   # "running" | "stopped"
    exitstatus = st.get("exitstatus")           # "OK" | error string | None

    progress = 0
    last_log = ""
    try:
        lines = _task_log(px, node, upid, start=0, limit=300)
        for entry in lines:
            text = entry.get("t") or entry.get("text") or ""
            m = _PROGRESS_RE.search(text)
            if m:
                progress = max(progress, int(m.group(1)))
        if lines:
            last_log = (lines[-1].get("t") or lines[-1].get("text") or "").strip()
    except Exception:
        pass

    running = status == "running"
    ok      = status == "stopped" and exitstatus == "OK"
    error   = status == "stopped" and exitstatus not in ("OK", None)

    return {
        "running":    running,
        "ok":         ok,
        "error":      error,
        "progress":   progress,
        "last_log":   last_log,
        "exitstatus": exitstatus,
    }
