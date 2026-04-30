"""
Per-node resources, VM/CT creation, and storage helpers (content list +
ISO/template upload).

Role gates:
- GET resources/content: any authenticated user
- POST qemu/lxc/upload : senior+
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from functools import partial

import requests as _requests
import urllib3 as _urllib3
from requests_toolbelt import MultipartEncoder

_upload_log = logging.getLogger(__name__ + ".upload")

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user, require_senior
from ..crypto import decrypt_password as _decrypt_password
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


# ---------- Storage content delete (ISO / template removal) ----------

@router.delete("/storage/{storage}/content", status_code=200)
def delete_storage_content(
    cred_id: int, node: str, storage: str,
    volid: str,
    db: Session = Depends(get_db),
    user: User  = Depends(require_senior),
):
    """
    Delete a file from Proxmox storage (ISO image, LXC template, etc.).

    `volid` is the full Proxmox volume identifier as returned by the content
    list, e.g. ``local:iso/virtio-win-0.1.285.iso``.  The ``storage:`` prefix
    is stripped automatically before calling the API, since the storage name
    is already part of the URL path.
    """
    cred = _get_cred(db, user, cred_id)
    px   = build_client(cred)

    # Strip "storage:" prefix — Proxmox content API uses the path portion only
    volume = volid.split(":", 1)[1] if ":" in volid else volid

    try:
        px.nodes(node).storage(storage).content(volume).delete()
    except Exception as e:
        raise HTTPException(400, f"Errore eliminazione: {_proxmox_error(e)}")

    return {"deleted": True, "volid": volid}


# ---------- Storage upload (ISO / vztmpl) ----------

@router.post("/storage/{storage}/upload", status_code=201)
async def storage_upload(cred_id: int, node: str, storage: str,
                         file: UploadFile = File(...),
                         filename: str | None = Form(None),
                         db: Session = Depends(get_db),
                         user: User = Depends(require_senior)):
    """
    Upload a file (ISO / disk image / LXC template) to a Proxmox storage.

    Strategy
    ────────
    1. Stream incoming multipart to a real temp file on disk (more reliable than
       seeking the SpooledTemporaryFile, which has edge-cases on large files).
    2. Forward to Proxmox via requests + MultipartEncoder in a thread-pool
       executor so the asyncio event loop is never blocked during the transfer.
       This completely bypasses proxmoxer's hardcoded 2 GiB limit.
    """
    cred = _get_cred(db, user, cred_id)

    name = filename or file.filename or "upload.bin"
    lower = name.lower()
    if lower.endswith((".iso", ".img")):
        content_type = "iso"
    elif lower.endswith((".tar.gz", ".tar.xz", ".tar.zst", ".tgz")):
        content_type = "vztmpl"
    elif lower.endswith((".qcow2", ".raw", ".vmdk")):
        content_type = "import"
    else:
        content_type = "iso"

    tmp_dir  = tempfile.mkdtemp(prefix="pmx_up_")
    tmp_path = os.path.join(tmp_dir, name)
    try:
        # ── 1. Write incoming bytes to a real temp file (non-blocking chunks) ─
        with open(tmp_path, "wb") as fp:
            shutil.copyfileobj(file.file, fp, length=4 * 1024 * 1024)

        # ── 2. Forward to Proxmox in a thread-pool (non-blocking) ────────────
        loop = asyncio.get_event_loop()
        try:
            upid = await loop.run_in_executor(
                None,
                partial(_stream_upload_to_proxmox,
                        cred=cred, node=node, storage=storage,
                        content_type=content_type,
                        file_path=tmp_path, file_name=name),
            )
        except Exception as e:
            raise HTTPException(400, f"Upload failed: {e}")

        return {"upid": upid, "name": name, "content": content_type, "storage": storage}
    finally:
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except Exception:
            pass


def _stream_upload_to_proxmox(*, cred, node: str, storage: str,
                               content_type: str, file_path: str,
                               file_name: str) -> str:
    """
    Upload a file to Proxmox storage using requests + MultipartEncoder.

    Reads from a real file on disk (file_path).  Completely bypasses proxmoxer
    so there is no 2 GiB size limit.  MultipartEncoder streams in chunks; the
    full file is never loaded into memory.  Returns the Proxmox task UPID.

    Timeouts:
      connect: 30 s
      read (response after upload finishes): 1800 s (30 min)
    The upload send time itself is not limited — it depends on network speed.
    """
    if not cred.verify_ssl:
        _urllib3.disable_warnings(_urllib3.exceptions.InsecureRequestWarning)

    password = _decrypt_password(cred.encrypted_password)
    base     = f"https://{cred.host}:{cred.port}/api2/json"
    sess     = _requests.Session()
    sess.verify = cred.verify_ssl

    # ── Authenticate ──────────────────────────────────────────────────────────
    r = sess.post(
        f"{base}/access/ticket",
        data={
            "username": f"{cred.pve_username}@{cred.pve_realm}",
            "password": password,
        },
        timeout=30,
    )
    r.raise_for_status()
    d      = r.json()["data"]
    ticket = d["ticket"]
    csrf   = d["CSRFPreventionToken"]

    # ── Stream file to Proxmox ────────────────────────────────────────────────
    file_size = os.path.getsize(file_path)
    _upload_log.info(
        "Starting Proxmox upload: node=%s storage=%s file=%s size=%d content=%s",
        node, storage, file_name, file_size, content_type,
    )
    url = f"{base}/nodes/{node}/storage/{storage}/upload"
    with open(file_path, "rb") as fp:
        encoder = MultipartEncoder(fields={
            "content":  content_type,
            "filename": (file_name, fp, "application/octet-stream"),
        })
        r = sess.post(
            url,
            headers={
                "Cookie":              f"PVEAuthCookie={ticket}",
                "CSRFPreventionToken": csrf,
                "Content-Type":        encoder.content_type,
            },
            data=encoder,
            # connect_timeout=30s, response_timeout=1800s (30 min max wait)
            timeout=(30, 1800),
        )

    _upload_log.info(
        "Proxmox upload response: status=%d body=%s",
        r.status_code, r.text[:500],
    )

    if r.status_code >= 400:
        try:
            detail = r.json().get("errors") or r.json().get("message") or r.text
        except Exception:
            detail = r.text
        raise RuntimeError(detail or f"HTTP {r.status_code}")

    upid = r.json().get("data", "")
    _upload_log.info("Proxmox upload accepted, UPID=%s", upid)
    return upid


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
