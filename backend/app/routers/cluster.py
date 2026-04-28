"""
Cluster + nodes endpoints.

Includes per-credential tree, an aggregated view across ALL the user's
credentials (so the sidebar shows every server, not only the active one),
and a thin set of endpoints used by the cluster management page.

Performance notes
─────────────────
• _build_tree now issues only ONE parallel batch to Proxmox (resources +
  cluster_status). The previous second wave of per-node node_status calls
  has been removed: cluster_resources already returns cpu, maxcpu, mem,
  maxmem, uptime for each node.

• GET /api/clusters/all uses stale-while-revalidate:
    1. Credentials with fresh cache → returned immediately (µs)
    2. Credentials with stale cache → returned immediately from stale data;
       a FastAPI BackgroundTask refreshes the cache after the response.
    3. Credentials with no cache    → fetched synchronously in parallel
       (only on first-ever load for that credential).
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_user, require_senior, require_admin
from ..models import User, ProxmoxCredential
from ..schemas import ClusterCreateIn, ClusterJoinIn, ClusterDestroyIn
from ..crypto import decrypt_password
from ..proxmox_client import (
    build_client, cluster_resources, cluster_status,
    node_status, node_rrddata,
)
from ..state import (
    get_cached_tree, get_stale_tree,
    set_cached_tree, get_revision,
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
    """
    Build the tree payload from a connected proxmox client.

    Issues exactly ONE parallel batch of 2 HTTP requests to Proxmox:
      • cluster.resources.get()  — returns nodes, VMs, CTs, storages
      • cluster.status.get()     — returns cluster quorum + node online flags

    Node CPU / RAM / uptime stats are extracted directly from the resources
    response (they are already present there), so no per-node node_status
    calls are required.
    """
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
            "node":    name,
            "status":  "online" if n.get("online") else "offline",
            "id":      n.get("id"),
            "ip":      n.get("ip"),
            "level":   n.get("level"),
            "type":    "node",
            "vms":     [],
            "cts":     [],
            "storages": [],
            # stats populated below from cluster_resources
            "cpu":    None,
            "maxcpu": None,
            "mem":    None,
            "maxmem": None,
            "uptime": None,
        }

    backup_targets: list[dict] = []

    for r in resources:
        t    = r.get("type")
        node = r.get("node")

        if t == "node" and node in by_node:
            # All the stats we need are already in the cluster resources payload —
            # no extra HTTP round-trip to node_status required.
            by_node[node].update({
                "cpu":    r.get("cpu"),
                "maxcpu": r.get("maxcpu"),
                "mem":    r.get("mem"),
                "maxmem": r.get("maxmem"),
                "uptime": r.get("uptime"),
            })

        elif t == "qemu" and node in by_node:
            by_node[node]["vms"].append({
                "vmid":   r.get("vmid"),
                "name":   r.get("name"),
                "status": r.get("status"),
                "cpu":    r.get("cpu"),
                "mem":    r.get("mem"),
                "maxmem": r.get("maxmem"),
                "uptime": r.get("uptime"),
                "node":   node,
                "type":   "qemu",
            })

        elif t == "lxc" and node in by_node:
            by_node[node]["cts"].append({
                "vmid":   r.get("vmid"),
                "name":   r.get("name"),
                "status": r.get("status"),
                "cpu":    r.get("cpu"),
                "mem":    r.get("mem"),
                "maxmem": r.get("maxmem"),
                "uptime": r.get("uptime"),
                "node":   node,
                "type":   "lxc",
            })

        elif t == "storage" and node in by_node:
            storage_obj = {
                "storage":    r.get("storage"),
                "node":       node,
                "type":       "storage",
                "used":       r.get("disk"),
                "total":      r.get("maxdisk"),
                "content":    r.get("content"),
                "plugintype": r.get("plugintype"),
                "shared":     bool(r.get("shared")),
            }
            by_node[node]["storages"].append(storage_obj)
            if r.get("content") and "backup" in (r.get("content") or ""):
                backup_targets.append(storage_obj)

    return {
        "cluster":        cluster_info,
        "nodes":          list(by_node.values()),
        "backup_targets": backup_targets,
    }


def _bg_refresh_cred(user_id: int, cred: ProxmoxCredential) -> None:
    """Background task: silently refresh one credential's tree cache."""
    try:
        px   = build_client(cred)
        tree = _build_tree(px)
        set_cached_tree(user_id, cred.id, tree)
    except Exception:
        pass   # keep stale data; next foreground request will retry


@router.get("/all")
def get_all_trees(
    background_tasks: BackgroundTasks,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """
    Aggregated view of ALL servers registered by the current user.

    Strategy (stale-while-revalidate):
      • Fresh cache  → instant response (µs latency)
      • Stale cache  → instant response from stale data + background refresh
      • No cache     → synchronous fetch (parallel across credentials)
    """
    creds = (
        db.query(ProxmoxCredential)
        .filter(ProxmoxCredential.user_id == user.id)
        .all()
    )
    if not creds:
        return []

    results: list[dict[str, Any]]       = []
    missing:  list[ProxmoxCredential]   = []   # no cache — must fetch now
    stale:    list[ProxmoxCredential]   = []   # stale — serve + refresh in bg

    for c in creds:
        data, is_stale = get_stale_tree(user.id, c.id)
        item: dict[str, Any] = {
            "cred_id":   c.id,
            "cred_name": c.name,
            "host":      c.host,
            "port":      c.port,
            "online":    False,
            "tree":      None,
            "error":     None,
        }
        if data is not None:
            item["tree"]   = data
            item["online"] = True
            results.append(item)
            if is_stale:
                stale.append(c)
        else:
            results.append(item)   # placeholder — filled in below
            missing.append(c)

    # Schedule background refresh for stale credentials (response already built)
    for c in stale:
        background_tasks.add_task(_bg_refresh_cred, user.id, c)

    # Synchronously fetch credentials with no cache at all
    if missing:
        def _fetch_one(c: ProxmoxCredential) -> tuple[int, dict]:
            item = next(r for r in results if r["cred_id"] == c.id)
            try:
                px   = build_client(c)
                tree = _build_tree(px)
                set_cached_tree(user.id, c.id, tree)
                item["tree"]   = tree
                item["online"] = True
            except Exception as e:
                item["error"] = f"{type(e).__name__}: {e}"
            return c.id, item

        workers = min(len(missing), 8)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_fetch_one, missing))   # mutates items in results in-place

    return results


@router.get("/revision")
def revision(user: User = Depends(get_current_user)):
    """Returns the current global revision counter."""
    return {"rev": get_revision()}


@router.get("/{cred_id}/tree")
def get_tree(
    cred_id: int,
    background_tasks: BackgroundTasks,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Returns the full sidebar tree for a single credential (SWR cached)."""
    cred = _get_cred(db, user, cred_id)
    data, is_stale = get_stale_tree(user.id, cred_id)
    if data is not None:
        if is_stale:
            background_tasks.add_task(_bg_refresh_cred, user.id, cred)
        return data
    try:
        px     = build_client(cred)
        result = _build_tree(px)
        set_cached_tree(user.id, cred_id, result)
        return result
    except Exception as e:
        raise HTTPException(502, f"Proxmox API error: {type(e).__name__}: {e}")


@router.get("/{cred_id}/status")
def get_status(
    cred_id: int,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    cred = _get_cred(db, user, cred_id)
    return cluster_status(build_client(cred))


@router.get("/{cred_id}/nodes/{node}")
def get_node(
    cred_id: int, node: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    cred = _get_cred(db, user, cred_id)
    return node_status(build_client(cred), node)


@router.get("/{cred_id}/nodes/{node}/rrd")
def get_node_rrd(
    cred_id: int, node: str, timeframe: str = "hour",
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    cred = _get_cred(db, user, cred_id)
    return node_rrddata(build_client(cred), node, timeframe=timeframe)


# ---------- Logical cluster management ----------

@router.post("", status_code=201)
def create_cluster(
    payload: ClusterCreateIn,
    db:   Session = Depends(get_db),
    user: User    = Depends(require_senior),
):
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
        "name":    payload.name,
        "primary": {"id": primary.id, "name": primary.name, "host": primary.host},
        "nodes":   nodes_ok,
        "status":  "ok",
    }


@router.post("/{cred_id}/cluster/join")
def cluster_join(
    cred_id: int, payload: ClusterJoinIn,
    db:   Session = Depends(get_db),
    user: User    = Depends(require_senior),
):
    joining = _get_cred(db, user, payload.node_cred_id)
    master  = _get_cred(db, user, cred_id)

    try:
        master_px   = build_client(master)
        fingerprint = None

        # Strategy 1: standard endpoint — returns nodelist with pve_fp fingerprint.
        # This can fail with a 500 if the Proxmox node cannot resolve its own
        # hostname internally (misconfigured /etc/hosts or DNS).
        try:
            info = master_px.cluster.config.join.get()
            fingerprint = (
                info.get("nodelist", [{}])[0].get("pve_fp")
                or info.get("totem", {}).get("cluster_name")
            )
        except Exception:
            pass   # fallback below

        # Strategy 2: get the fingerprint from the node's TLS certificate.
        # This call does NOT trigger hostname resolution, so it works even when
        # the node's own hostname is not resolvable via DNS.
        if not fingerprint:
            nodes_list = master_px.nodes.get()
            node_name  = nodes_list[0]["node"] if nodes_list else None
            if node_name:
                certs = master_px.nodes(node_name).certificates.info.get()
                # Prefer the pve-ssl certificate; fall back to any cert with a fingerprint
                fingerprint = next(
                    (c.get("fingerprint") for c in certs
                     if c.get("filename", "").endswith("pve-ssl.pem") and c.get("fingerprint")),
                    None,
                ) or next(
                    (c.get("fingerprint") for c in certs if c.get("fingerprint")),
                    None,
                )

        if not fingerprint:
            raise HTTPException(502, "Could not determine cluster fingerprint from master node")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Could not read master join info: {type(e).__name__}: {e}")

    # Master password is decrypted from stored credentials — no need to send it
    # from the frontend.  link0 defaults to the joining node's registered host.
    try:
        master_password = decrypt_password(master.encrypted_password)
    except Exception as e:
        raise HTTPException(500, f"Could not decrypt master credentials: {e}")

    link0 = payload.link0_address or joining.host

    try:
        joining_px = build_client(joining)
        upid = joining_px.cluster.config.join.post(
            hostname=master.host,
            password=master_password,
            fingerprint=fingerprint,
            link0=link0,
        )
    except Exception as e:
        raise HTTPException(400, f"Join failed: {type(e).__name__}: {e}")

    return {"upid": upid, "joined": joining.name, "to": master.name, "link0": link0}


@router.post("/{cred_id}/cluster/destroy")
def cluster_destroy(
    cred_id: int, payload: ClusterDestroyIn,
    db:   Session = Depends(get_db),
    user: User    = Depends(require_admin),
):
    import paramiko

    all_ids: list[int] = list(dict.fromkeys([cred_id] + list(payload.node_cred_ids)))

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
            results.append({
                "cred_id": cid, "name": f"id={cid}", "host": "?",
                "success": False, "output": "", "error": "Credential not found",
            })
            continue

        node_result: dict = {
            "cred_id": cred.id, "name": cred.name, "host": cred.host,
            "success": False, "output": "", "error": None,
        }

        try:
            password = decrypt_password(cred.encrypted_password)
            client   = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=cred.host, port=22, username="root",
                password=password, timeout=30, banner_timeout=30,
            )
            output_lines: list[str] = []
            for cmd in CLEANUP_CMDS:
                _, stdout, stderr = client.exec_command(cmd, timeout=30)
                out = stdout.read().decode("utf-8", errors="replace").strip()
                err = stderr.read().decode("utf-8", errors="replace").strip()
                if out: output_lines.append(out)
                if err: output_lines.append(f"[stderr] {err}")
            client.close()
            node_result["output"]  = "\n".join(output_lines)
            node_result["success"] = True
        except Exception as exc:
            node_result["error"] = f"{type(exc).__name__}: {exc}"

        results.append(node_result)

    return {
        "nodes":     results,
        "destroyed": all(r["success"] for r in results),
    }