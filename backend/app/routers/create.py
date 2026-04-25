"""
Per-node resources, VM/CT creation, and storage helpers (content list +
ISO/template upload).

Role gates:
- GET resources/content: any authenticated user
- POST qemu/lxc/upload : senior+
"""

from __future__ import annotations

import os
import shutil
import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user, require_senior
from ..models import User, ProxmoxCredential
from ..schemas import CreateVMIn, CreateCTIn
from ..proxmox_client import (
    build_client, next_vmid, node_storages, node_iso_list,
    node_ct_templates, node_networks, create_qemu, create_lxc,
    vm_start,
)


router = APIRouter(prefix="/api/clusters/{cred_id}/nodes/{node}", tags=["create"])


def _get_cred(db: Session, user: User, cred_id: int) -> ProxmoxCredential:
    cred = db.query(ProxmoxCredential).filter(
        ProxmoxCredential.id == cred_id,
        ProxmoxCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(404, "Credential not found")
    return cred


def _proxmox_error(e: Exception) -> str:
    """Extract the most informative message from a proxmoxer/Resty error."""
    msg = str(e)
    for attr in ("content", "errors", "data"):
        v = getattr(e, attr, None)
        if v: msg = f"{msg} | {attr}={v}"
    return msg


# ---------- Resource discovery ----------

@router.get("/resources")
def get_resources(cred_id: int, node: str,
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)

    def _safe(fn, *a, **kw):
        try: return fn(*a, **kw)
        except Exception: return []

    storages_all   = _safe(node_storages, px, node)
    storages_vm    = [s for s in storages_all if "images"  in (s.get("content") or "")]
    storages_ct    = [s for s in storages_all if "rootdir" in (s.get("content") or "")]
    storages_iso   = [s for s in storages_all if "iso"     in (s.get("content") or "")]
    storages_tmpl  = [s for s in storages_all if "vztmpl"  in (s.get("content") or "")]

    return {
        "next_vmid": _safe(next_vmid, px) or 100,
        "storages": {
            "all":       storages_all,
            "vm_images": storages_vm,
            "ct_rootfs": storages_ct,
            "iso":       storages_iso,
            "ct_tmpl":   storages_tmpl,
        },
        "iso_images":   _safe(node_iso_list, px, node),
        "ct_templates": _safe(node_ct_templates, px, node),
        "networks":     _safe(node_networks, px, node),
        "ostypes": [
            {"value": "l26",   "label": "Linux 6.x/5.x/4.x/3.x/2.6 (l26)"},
            {"value": "l24",   "label": "Linux 2.4"},
            {"value": "win11", "label": "Windows 11"},
            {"value": "win10", "label": "Windows 10"},
            {"value": "win8",  "label": "Windows 8 / 2012 r2"},
            {"value": "win7",  "label": "Windows 7 / 2008"},
            {"value": "other", "label": "Altro"},
        ],
        "bios_options": [
            {"value": "seabios", "label": "SeaBIOS (default)"},
            {"value": "ovmf",    "label": "OVMF (UEFI)"},
        ],
        "scsihw_options": [
            "virtio-scsi-single", "virtio-scsi-pci", "lsi", "lsi53c810", "pvscsi",
        ],
        "net_models": ["virtio", "e1000", "rtl8139", "vmxnet3"],
        "disk_formats": ["qcow2", "raw", "vmdk"],
    }


# ---------- Storage content (list ISO/templates/backups on a storage) ----------

@router.get("/storage/{storage}/content")
def storage_content(cred_id: int, node: str, storage: str, content: str = "iso,vztmpl",
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """
    Mirror of `GET /nodes/{node}/storage/{storage}/content`.
    `content` may be a comma list: 'iso', 'vztmpl', 'backup', 'images'...
    """
    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)
    out: list[dict] = []
    for kind in [c.strip() for c in content.split(",") if c.strip()]:
        try:
            items = px.nodes(node).storage(storage).content.get(content=kind) or []
            for it in items:
                it["_query_kind"] = kind
                out.append(it)
        except Exception:
            continue
    return out


# ---------- Storage upload (ISO / vztmpl) ----------

@router.post("/storage/{storage}/upload", status_code=201)
async def storage_upload(cred_id: int, node: str, storage: str,
                         file: UploadFile = File(...),
                         filename: str | None = Form(None),
                         db: Session = Depends(get_db),
                         user: User = Depends(require_senior)):
    """
    Upload a file (ISO / disk image / LXC template) to a Proxmox storage.

    Streams the upload to a temp file, then forwards it to the Proxmox
    storage API using proxmoxer's multipart upload helper.
    """
    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)

    name = filename or file.filename or "upload.bin"
    # Heuristic content type based on extension
    lower = name.lower()
    if lower.endswith((".iso", ".img")):
        content_type = "iso"
    elif lower.endswith((".tar.gz", ".tar.xz", ".tar.zst", ".tgz")):
        content_type = "vztmpl"
    elif lower.endswith((".qcow2", ".raw", ".vmdk")):
        content_type = "import"
    else:
        content_type = "iso"

    tmp_dir = tempfile.mkdtemp(prefix="pmx_up_")
    tmp_path = os.path.join(tmp_dir, name)
    try:
        with open(tmp_path, "wb") as fp:
            shutil.copyfileobj(file.file, fp, length=1024 * 1024)

        try:
            with open(tmp_path, "rb") as fp:
                upid = px.nodes(node).storage(storage).upload.post(
                    content=content_type,
                    filename=fp,
                )
        except Exception as e:
            raise HTTPException(400, f"Upload failed: {_proxmox_error(e)}")

        return {"upid": upid, "name": name, "content": content_type, "storage": storage}
    finally:
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except Exception:
            pass


# ---------- Create VM (senior+) ----------

@router.post("/qemu")
def create_vm(cred_id: int, node: str, body: CreateVMIn,
              db: Session = Depends(get_db),
              user: User = Depends(require_senior)):
    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)

    extras = body.model_dump(exclude_none=True)

    # Build params for Proxmox: prefer raw passthrough fields when present,
    # fall back to convenience builders otherwise.
    params: dict = {
        "vmid":    body.vmid,
        "name":    body.name,
        "cores":   body.cores,
        "sockets": body.sockets,
        "memory":  body.memory,
        "ostype":  body.ostype,
        "scsihw":  body.scsihw,
        "bios":    body.bios,
        "agent":   1 if body.agent else 0,
    }

    # scsi0 — convenience: build from disk_storage/disk_size if not provided raw
    if body.scsi0:
        params["scsi0"] = body.scsi0
    elif body.disk_storage and body.disk_size:
        suffix = ",discard=on" if body.discard else ""
        params["scsi0"] = f"{body.disk_storage}:{body.disk_size}{suffix}"

    # net0
    if body.net0:
        params["net0"] = body.net0
    else:
        net_parts = [f"model={body.net_model}", f"bridge={body.net_bridge}"]
        if body.net_vlan:
            net_parts.append(f"tag={body.net_vlan}")
        params["net0"] = ",".join(net_parts)

    # ide2 / iso
    if body.ide2:
        params["ide2"] = body.ide2
    elif body.iso_volid:
        params["ide2"] = f"{body.iso_volid},media=cdrom"

    # boot
    if body.boot:
        params["boot"] = body.boot
    elif params.get("ide2"):
        params["boot"] = "order=scsi0;ide2;net0"
    else:
        params["boot"] = "order=scsi0;net0"

    if body.machine:
        params["machine"] = body.machine
    if body.efidisk0:
        params["efidisk0"] = body.efidisk0
    elif body.bios == "ovmf" and body.disk_storage:
        # EFI requires an efidisk; create a small one on the same storage.
        params["efidisk0"] = f"{body.disk_storage}:1,efitype=4m,pre-enrolled-keys=0"

    # Forward any extra fields (e.g. virtio0, sata0, kvm, numa, etc) untouched
    KNOWN = {
        "vmid", "name", "cores", "sockets", "memory", "ostype", "disk_storage",
        "disk_size", "disk_format", "discard", "scsi0", "ide2", "net0",
        "efidisk0", "boot", "net_bridge", "net_model", "net_vlan", "iso_volid",
        "scsihw", "bios", "machine", "start_after_create", "agent",
    }
    for k, v in extras.items():
        if k not in KNOWN and k not in params:
            params[k] = v

    try:
        upid = create_qemu(px, node, params)
    except Exception as e:
        raise HTTPException(400, f"Create failed: {_proxmox_error(e)}")

    if body.start_after_create:
        try: vm_start(px, node, body.vmid, "qemu")
        except Exception: pass

    return {"upid": upid, "vmid": body.vmid, "node": node}


# ---------- Create CT (senior+) ----------

@router.post("/lxc")
def create_ct(cred_id: int, node: str, body: CreateCTIn,
              db: Session = Depends(get_db),
              user: User = Depends(require_senior)):
    if not body.password and not body.ssh_public_keys:
        raise HTTPException(400, "Provide at least a password or an SSH public key")
    if not body.ostemplate:
        raise HTTPException(400, "ostemplate is required (e.g. 'local:vztmpl/...')")

    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)

    extras = body.model_dump(exclude_none=True)

    params: dict = {
        "vmid":         body.vmid,
        "hostname":     body.hostname or f"ct-{body.vmid}",
        "ostemplate":   body.ostemplate,
        "cores":        body.cores,
        "memory":       body.memory,
        "swap":         body.swap,
        "unprivileged": 1 if body.unprivileged else 0,
        "onboot":       1 if body.onboot else 0,
    }

    # rootfs
    if body.rootfs:
        params["rootfs"] = body.rootfs
    elif body.storage and body.disk_size:
        params["rootfs"] = f"{body.storage}:{body.disk_size}"

    # net
    if body.net0:
        params["net0"] = body.net0
    else:
        net_parts = [
            f"name={body.net_name}",
            f"bridge={body.net_bridge}",
            f"ip={body.net_ip}",
        ]
        if body.net_gw and body.net_ip != "dhcp":
            net_parts.append(f"gw={body.net_gw}")
        params["net0"] = ",".join(net_parts)

    if body.password:
        params["password"] = body.password
    if body.ssh_public_keys:
        params["ssh-public-keys"] = body.ssh_public_keys
    if body.features:
        params["features"] = body.features

    KNOWN = {
        "vmid", "hostname", "ostemplate", "cores", "memory", "swap", "storage",
        "disk_size", "rootfs", "unprivileged", "net_name", "net_bridge", "net_ip",
        "net_gw", "net0", "password", "ssh_public_keys", "start_after_create",
        "onboot", "features",
    }
    for k, v in extras.items():
        if k not in KNOWN and k not in params:
            params[k] = v

    try:
        upid = create_lxc(px, node, params)
    except Exception as e:
        raise HTTPException(400, f"Create failed: {_proxmox_error(e)}")

    if body.start_after_create:
        try: vm_start(px, node, body.vmid, "lxc")
        except Exception: pass

    return {"upid": upid, "vmid": body.vmid, "node": node}
