"""
Cluster + nodes endpoints.

Includes per-credential tree, an aggregated view across ALL the user's
credentials (so the sidebar shows every server, not only the active one),
and a thin set of endpoints used by the cluster management page
(POST /api/clusters, POST /api/clusters/{id}/cluster/join,
 GET /api/clusters/all).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any

from ..database import get_db
from ..auth import get_current_user, require_senior, require_admin
from ..models import User, ProxmoxCredential
from ..schemas import ClusterCreateIn, ClusterJoinIn, ClusterDestroyIn
from ..crypto import decrypt_password
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


def _build_tree(px) -> dict:
    """Build the tree payload from a connected proxmox client. Parallelises I/O."""

    # Fetch resources + status concurrently
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_res = ex.submit(cluster_resources, px)
        f_st  = ex.submit(cluster_status, px)
        resources = f_res.result()
        status    = f_st.result()

    cluster_info = next((s for s in status if s.get("type") == "cluster"), None)
    node_entries = [s for s in status if s.get("type") == "node"]

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

    # Fetch per-node stats in parallel (one request per online node)
    online_names = [n["name"] for n in node_entries if n.get("online") and n["name"] in by_node]
    if online_names:
        with ThreadPoolExecutor(max_workers=min(len(online_names), 8)) as ex:
            future_map = {ex.submit(node_status, px, name): name for name in online_names}
            for future in as_completed(future_map):
                name = future_map[future]
                try:
                    ns = future.result()
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


@router.get("/all")
def get_all_trees(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    Aggregated view of ALL servers registered by the current user.

    Even servers that are unreachable / powered off are included as a
    placeholder so the sidebar can still show them with an "offline" badge.
    Each entry: { cred_id, cred_name, host, online, tree, error }.
    All credentials are queried in parallel to minimise latency.
    """
    creds = db.query(ProxmoxCredential).filter(ProxmoxCredential.user_id == user.id).all()
    if not creds:
        return []

    def _fetch_one(c) -> dict[str, Any]:
        item: dict[str, Any] = {
            "cred_id": c.id,
            "cred_name": c.name,
            "host": c.host,
            "port": c.port,
            "online": False,
            "tree": None,
            "error": None,
        }
        try:
            px = build_client(c)
            item["tree"] = _build_tree(px)
            item["online"] = True
        except Exception as e:
            item["error"] = f"{type(e).__name__}: {e}"
        return item

    workers = min(len(creds), 8)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        # preserve original registration order
        out = list(ex.map(_fetch_one, creds))
    return out


@router.get("/{cred_id}/tree")
def get_tree(cred_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Returns the full sidebar tree for a single credential."""
    cred = _get_cred(db, user, cred_id)
    try:
        px = build_client(cred)
        return _build_tree(px)
    except Exception as e:
        # Return an empty tree with error info so the UI doesn't blow up
        # when the server is down / unreachable.
        raise HTTPException(502, f"Proxmox API error: {type(e).__name__}: {e}")


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


# ---------- Logical cluster management (frontend-side cluster groupings) ----------

@router.post("", status_code=201)
def create_cluster(payload: ClusterCreateIn,
                   db: Session = Depends(get_db),
                   user: User = Depends(require_senior)):
    """
    Create a *logical* cluster grouping (server bundle).

    The Proxmox cluster on the wire is created/managed via the primary node's
    `pvecm` command — but persisting the bundle on the manager side allows
    the UI to show drag&drop groupings even when the underlying servers are
    standalone. We don't have a dedicated DB table for it, so for now we
    simply validate the inputs and return the payload (the frontend keeps it
    in localStorage). A future migration can add a `clusters` table.
    """
    primary = _get_cred(db, user, payload.primary_cred_id)
    nodes_ok = []
    for nid in payload.node_cred_ids:
        c = db.query(ProxmoxCredential).filter(
            ProxmoxCredential.id == nid,
            ProxmoxCredential.user_id == user.id,
        ).first()
        if c:
            nodes_ok.append({"id": c.id, "name": c.name, "host": c.host})
    return {
        "name": payload.name,
        "primary": {"id": primary.id, "name": primary.name, "host": primary.host},
        "nodes": nodes_ok,
        "status": "ok",
    }


@router.post("/{cred_id}/cluster/join")
def cluster_join(cred_id: int, payload: ClusterJoinIn,
                 db: Session = Depends(get_db),
                 user: User = Depends(require_senior)):
    """
    Join a node into an existing PVE cluster.

    This calls `POST /cluster/config/join` on the joining node with the
    master fingerprint, link0 address and root password.
    """
    joining = _get_cred(db, user, payload.node_cred_id)
    master  = _get_cred(db, user, cred_id)

    try:
        master_px = build_client(master)
        # Get cluster join info (fingerprint + nodelist) from the master
        info = master_px.cluster.config.join.get()
        fingerprint = info.get("nodelist", [{}])[0].get("pve_fp") or info.get("totem", {}).get("cluster_name")
    except Exception as e:
        raise HTTPException(502, f"Could not read master join info: {type(e).__name__}: {e}")

    try:
        joining_px = build_client(joining)
        upid = joining_px.cluster.config.join.post(
            hostname=payload.master_host,
            password=payload.master_password,
            fingerprint=fingerprint,
            link0=payload.link0_address,
        )
    except Exception as e:
        raise HTTPException(400, f"Join failed: {type(e).__name__}: {e}")

    return {"upid": upid, "joined": joining.name, "to": master.name}


@router.post("/{cred_id}/cluster/destroy")
def cluster_destroy(cred_id: int, payload: ClusterDestroyIn,
                    db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    """
    Dissolve a PVE cluster on all nodes via SSH.

    Runs the official cluster-removal sequence on every credential
    supplied (primary + node_cred_ids). Uses the stored root password
    for SSH authentication on port 22.
    """
    import paramiko

    # Deduplicated list: primary first, then extra nodes
    all_ids: list[int] = list(dict.fromkeys([cred_id] + list(payload.node_cred_ids)))

    # Commands run sequentially on each node
    CLEANUP_CMDS = [
        "systemctl stop pve-cluster 2>/dev/null; true",
        "systemctl stop corosync 2>/dev/null; true",
        "pmxcfs -l >/dev/null 2>&1 &",
        "sleep 2",
        "rm -f /etc/pve/corosync.conf 2>/dev/null; true",
        "rm -rf /etc/corosync/* 2>/dev/null; true",
        "rm -f /etc/pve/cluster.conf 2>/dev/null; true",
        "killall pmxcfs 2>/dev/null; true",
        "systemctl start pve-cluster 2>/dev/null; true",
    ]

    results: list[dict] = []

    for cid in all_ids:
        cred = db.query(ProxmoxCredential).filter(
            ProxmoxCredential.id == cid,
            ProxmoxCredential.user_id == user.id,
        ).first()
        if not cred:
            results.append({"cred_id": cid, "name": f"id={cid}", "host": "?",
                             "success": False, "output": "", "error": "Credential not found"})
            continue

        node_result: dict = {
            "cred_id": cred.id,
            "name": cred.name,
            "host": cred.host,
            "success": False,
            "output": "",
            "error": None,
        }

        try:
            password = decrypt_password(cred.encrypted_password)
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=cred.host,
                port=22,
                username="root",
                password=password,
                timeout=30,
                banner_timeout=30,
            )
            output_lines: list[str] = []
            for cmd in CLEANUP_CMDS:
                _, stdout, stderr = client.exec_command(cmd, timeout=30)
                out = stdout.read().decode("utf-8", errors="replace").strip()
                err = stderr.read().decode("utf-8", errors="replace").strip()
                if out:
                    output_lines.append(out)
                if err:
                    output_lines.append(f"[stderr] {err}")
            client.close()
            node_result["output"] = "\n".join(output_lines)
            node_result["success"] = True
        except Exception as exc:
            node_result["error"] = f"{type(exc).__name__}: {exc}"

        results.append(node_result)

    return {
        "nodes": results,
        "destroyed": all(r["success"] for r in results),
    }
