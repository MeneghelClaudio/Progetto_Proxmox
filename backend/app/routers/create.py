"""
Per-node resources + VM/CT creation.

Role gates:
- GET resources: any authenticated user (needed for any form)
- POST qemu/lxc: senior+
"""

from fastapi import APIRouter, Depends, HTTPException
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


# ---------- Create VM (senior+) ----------

@router.post("/qemu")
def create_vm(cred_id: int, node: str, body: CreateVMIn,
              db: Session = Depends(get_db),
              user: User = Depends(require_senior)):
    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)

    net_parts = [f"model={body.net_model}", f"bridge={body.net_bridge}"]
    if body.net_vlan:
        net_parts.append(f"tag={body.net_vlan}")

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
        "scsi0":   f"{body.disk_storage}:{body.disk_size},format={body.disk_format}",
        "net0":    ",".join(net_parts),
    }
    if body.machine:
        params["machine"] = body.machine
    if body.iso_volid:
        params["ide2"]    = f"{body.iso_volid},media=cdrom"
        params["boot"]    = "order=scsi0;ide2;net0"
    else:
        params["boot"]    = "order=scsi0;net0"

    try:
        upid = create_qemu(px, node, params)
    except Exception as e:
        raise HTTPException(400, f"Create failed: {e}")

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

    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)

    net_parts = [
        f"name={body.net_name}",
        f"bridge={body.net_bridge}",
        f"ip={body.net_ip}",
    ]
    if body.net_gw and body.net_ip != "dhcp":
        net_parts.append(f"gw={body.net_gw}")

    params: dict = {
        "vmid":         body.vmid,
        "hostname":     body.hostname,
        "ostemplate":   body.ostemplate,
        "cores":        body.cores,
        "memory":       body.memory,
        "swap":         body.swap,
        "rootfs":       f"{body.storage}:{body.disk_size}",
        "unprivileged": 1 if body.unprivileged else 0,
        "onboot":       1 if body.onboot else 0,
        "net0":         ",".join(net_parts),
    }
    if body.password:
        params["password"] = body.password
    if body.ssh_public_keys:
        params["ssh-public-keys"] = body.ssh_public_keys
    if body.features:
        params["features"] = body.features

    try:
        upid = create_lxc(px, node, params)
    except Exception as e:
        raise HTTPException(400, f"Create failed: {e}")

    if body.start_after_create:
        try: vm_start(px, node, body.vmid, "lxc")
        except Exception: pass

    return {"upid": upid, "vmid": body.vmid, "node": node}
