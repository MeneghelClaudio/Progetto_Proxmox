"""
Cluster + nodes endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user
from ..models import User, ProxmoxCredential
from ..proxmox_client import (
    build_client, cluster_resources, cluster_status,
    node_status, node_rrddata,
)


router = APIRouter(prefix="/api/clusters", tags=["cluster"])


def _get_cred(db: Session, user: User, cred_id: int) -> ProxmoxCredential:
    cred = db.query(ProxmoxCredential).filter(
        ProxmoxCredential.id == cred_id,
        ProxmoxCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(404, "Credential not found")
    return cred


@router.get("/{cred_id}/tree")
def get_tree(cred_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Returns the full sidebar tree."""
    cred = _get_cred(db, user, cred_id)
    px = build_client(cred)

    try:
        resources = cluster_resources(px)
        status = cluster_status(px)
    except Exception as e:
        raise HTTPException(502, f"Proxmox API error: {e}")

    cluster_info = next((s for s in status if s.get("type") == "cluster"), None)
    node_entries = [s for s in status if s.get("type") == "node"]

    # Group VMs / CTs / storage per node
    by_node: dict[str, dict] = {}
    for n in node_entries:
        name = n["name"]
        by_node[name] = {
            "node": name,
            "status": "online" if n.get("online") else "offline",
            "id": n.get("id"),
            "ip": n.get("ip"),
            "level": n.get("level"),
            "type": "node",
            "vms": [],
            "cts": [],
            "storages": [],
        }

    backup_targets: list[dict] = []
    for r in resources:
        t = r.get("type")
        node = r.get("node")
        if t == "qemu" and node in by_node:
            by_node[node]["vms"].append({
                "vmid": r.get("vmid"), "name": r.get("name"),
                "status": r.get("status"), "cpu": r.get("cpu"),
                "mem": r.get("mem"), "maxmem": r.get("maxmem"),
                "uptime": r.get("uptime"), "node": node, "type": "qemu",
            })
        elif t == "lxc" and node in by_node:
            by_node[node]["cts"].append({
                "vmid": r.get("vmid"), "name": r.get("name"),
                "status": r.get("status"), "cpu": r.get("cpu"),
                "mem": r.get("mem"), "maxmem": r.get("maxmem"),
                "uptime": r.get("uptime"), "node": node, "type": "lxc",
            })
        elif t == "storage" and node in by_node:
            storage_obj = {
                "storage": r.get("storage"), "node": node,
                "type": "storage", "used": r.get("disk"),
                "total": r.get("maxdisk"), "content": r.get("content"),
                "plugintype": r.get("plugintype"),
                "shared": bool(r.get("shared")),
            }
            by_node[node]["storages"].append(storage_obj)
            if r.get("content") and "backup" in (r.get("content") or ""):
                backup_targets.append(storage_obj)

    # Fill live CPU/RAM for each node
    for n in node_entries:
        name = n["name"]
        if name in by_node and n.get("online"):
            try:
                ns = node_status(px, name)
                by_node[name].update({
                    "cpu": ns.get("cpu"),
                    "maxcpu": ns.get("cpuinfo", {}).get("cpus"),
                    "mem": ns.get("memory", {}).get("used"),
                    "maxmem": ns.get("memory", {}).get("total"),
                    "uptime": ns.get("uptime"),
                    "loadavg": ns.get("loadavg", []),
                    "pve_version": ns.get("pveversion"),
                })
            except Exception:
                pass

    return {
        "cluster": cluster_info,
        "nodes": list(by_node.values()),
        "backup_targets": backup_targets,
    }


@router.get("/{cred_id}/status")
def get_status(cred_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    return cluster_status(build_client(cred))


@router.get("/{cred_id}/nodes/{node}")
def get_node(cred_id: int, node: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    return node_status(build_client(cred), node)


@router.get("/{cred_id}/nodes/{node}/rrd")
def get_node_rrd(cred_id: int, node: str, timeframe: str = "hour",
                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cred = _get_cred(db, user, cred_id)
    return node_rrddata(build_client(cred), node, timeframe=timeframe)
