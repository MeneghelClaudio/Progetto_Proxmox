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
import shlex

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
    get_tls_fingerprint, wait_for_task, upid_node, invalidate_client,
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
    if primary.pve_username != "root" or primary.pve_realm != "pam":
        raise HTTPException(
            400,
            f"La creazione del cluster richiede le credenziali root@pam del nodo primario, "
            f"ma la credenziale salvata usa '{primary.pve_username}@{primary.pve_realm}'.",
        )

    import paramiko

    try:
        password = decrypt_password(primary.encrypted_password)
    except Exception as e:
        raise HTTPException(500, f"Errore decifratura credenziali del nodo primario: {e}")

    link0 = (payload.link0_address or primary.host or "").strip()
    cluster_name = (payload.name or "").strip()
    if not cluster_name:
        raise HTTPException(400, "Il nome del cluster è obbligatorio.")
    if not link0:
        raise HTTPException(400, "L'indirizzo corosync del nodo primario è obbligatorio.")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=primary.host, port=22, username="root",
            password=password, timeout=30, banner_timeout=30,
        )
        # A local-only cluster created from the UI is not enough: the primary
        # node must run `pvecm create` so the following join has a valid
        # corosync configuration and nodelist.
        create_cmd = (
            f"pvecm status >/dev/null 2>&1 && "
            f"echo '__PMX_CLUSTER_ALREADY_EXISTS__' || "
            f"pvecm create {shlex.quote(cluster_name)} --link0 {shlex.quote(link0)}"
        )
        _, stdout, stderr = client.exec_command(create_cmd, timeout=120)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
    except Exception as exc:
        raise HTTPException(
            400,
            f"Creazione cluster fallita sul nodo primario {primary.host}: {type(exc).__name__}: {exc}",
        )
    finally:
        client.close()

    combined = "\n".join(part for part in (out, err) if part).strip()
    if "__PMX_CLUSTER_ALREADY_EXISTS__" in combined:
        raise HTTPException(
            400,
            f"Il nodo primario '{primary.name}' appartiene già a un cluster Proxmox. "
            "Apri o aggiorna quel cluster invece di crearne uno nuovo dallo stesso nodo.",
        )
    if exit_code != 0:
        raise HTTPException(400, f"Creazione cluster fallita.\n{combined}".strip())

    invalidate_client(primary.id)

    return {
        "name":    cluster_name,
        "primary": {"id": primary.id, "name": primary.name, "host": primary.host},
        "nodes":   [],
        "status":  "ok",
        "link0":   link0,
        "output":  combined,
    }


def _ssh_cleanup_corosync(cred: "ProxmoxCredential") -> None:  # noqa: F821
    """
    SSH into a node and remove stale corosync/cluster configuration files.

    Called automatically when a join task fails with a corosync config error
    (invalid corosync.conf, authkey already exists, corosync already running).
    The credential must belong to root (root@pam) because only root can stop
    corosync and delete files under /etc/pve and /etc/corosync.
    """
    import paramiko

    password = decrypt_password(cred.encrypted_password)
    client   = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=cred.host, port=22, username="root",
        password=password, timeout=20, banner_timeout=20,
    )
    cmds = [
        "systemctl stop corosync 2>/dev/null; true",
        "rm -f /etc/pve/corosync.conf 2>/dev/null; true",
        "rm -f /etc/corosync/authkey 2>/dev/null; true",
    ]
    for cmd in cmds:
        _, stdout, stderr = client.exec_command(cmd, timeout=20)
        stdout.read()   # drain so the channel doesn't block
        stderr.read()
    client.close()


# Substrings in the Proxmox task log that indicate stale corosync state on
# the joining node — we auto-clean and retry exactly once in this case.
_COROSYNC_ERRORS = (
    "invalid corosync.conf",
    "corosync.conf already exists",
    "authkey already exists",
    "corosync is already running",
)


@router.post("/{cred_id}/cluster/join")
def cluster_join(
    cred_id: int, payload: ClusterJoinIn,
    db:   Session = Depends(get_db),
    user: User    = Depends(require_senior),
):
    """
    Join a node (payload.node_cred_id) to the cluster managed by cred_id.

    Fingerprint resolution order (most → least reliable):
      1. Direct TLS socket inspection of master:port  ← no DNS required, exact cert
      2. GET /cluster/config/join on the master        ← standard Proxmox API
      3. GET /nodes/{n}/certificates/info              ← last-resort fallback

    After posting the join task on the joining node, we poll the task UPID
    until it completes or times out, so silent background failures are surfaced
    as proper HTTP errors rather than a misleading 200 OK.

    Auto-retry logic:
      If the task fails because of stale corosync configuration on the joining
      node (invalid corosync.conf / authkey already exists / corosync running),
      the backend automatically SSHes in, removes the stale files, and retries
      the join once — no user interaction required.
    """
    joining = _get_cred(db, user, payload.node_cred_id)
    master  = _get_cred(db, user, cred_id)
    mpx = build_client(master)

    try:
        join_info = mpx.cluster.config.join.get()
    except Exception as exc:
        raise HTTPException(
            400,
            "Il nodo master non ha ancora un cluster Proxmox valido. "
            "Crea prima il cluster reale sul nodo primario, poi riprova il join. "
            f"(dettaglio API: {type(exc).__name__}: {exc})",
        )

    if not (join_info.get("nodelist") or []):
        raise HTTPException(
            400,
            "Il nodo master non ha ancora una configurazione corosync valida "
            "(nodelist vuota). Crea prima il cluster reale sul nodo primario, poi riprova il join.",
        )

    # ── 1. Get fingerprint ───────────────────────────────────────────────────
    fingerprint: str | None = None

    # Strategy A: direct TLS inspection — works regardless of DNS, gives the
    # exact SHA-256 pve_fp that Proxmox uses for cluster join verification.
    try:
        fingerprint = get_tls_fingerprint(master.host, master.port)
    except Exception:
        pass

    # Strategy B: GET /cluster/config/join (can fail if node DNS is broken)
    if not fingerprint:
        try:
            fingerprint = (join_info.get("nodelist") or [{}])[0].get("pve_fp")
        except Exception:
            pass

    # Strategy C: node certificates API
    if not fingerprint:
        try:
            nodes_list = mpx.nodes.get()
            node_name  = nodes_list[0]["node"] if nodes_list else None
            if node_name:
                certs = mpx.nodes(node_name).certificates.info.get()
                fingerprint = next(
                    (c.get("fingerprint") for c in certs
                     if c.get("filename", "").endswith("pve-ssl.pem")
                     and c.get("fingerprint")),
                    None,
                ) or next(
                    (c.get("fingerprint") for c in certs if c.get("fingerprint")),
                    None,
                )
        except Exception:
            pass

    if not fingerprint:
        raise HTTPException(
            502,
            "Impossibile leggere il fingerprint del nodo master. "
            "Verifica che il server sia raggiungibile.",
        )

    # ── 2. Decrypt stored master password ───────────────────────────────────
    # Proxmox cluster join requires the root@pam (Linux root) password of the
    # master node.  Warn if the stored credential uses a different user.
    if master.pve_username != "root" or master.pve_realm != "pam":
        raise HTTPException(
            400,
            f"Il join richiede le credenziali root@pam del master, "
            f"ma la credenziale salvata usa '{master.pve_username}@{master.pve_realm}'. "
            f"Aggiorna le credenziali del server master con utente 'root' e realm 'pam'.",
        )

    # The POST /cluster/config/join endpoint on the joining node also requires
    # root@pam — any other user gets a 401 "invalid PVE ticket" from Proxmox.
    if joining.pve_username != "root" or joining.pve_realm != "pam":
        raise HTTPException(
            400,
            f"Il join richiede le credenziali root@pam anche sul nodo entrante, "
            f"ma la credenziale salvata usa '{joining.pve_username}@{joining.pve_realm}'. "
            f"Aggiorna le credenziali del server '{joining.name}' con utente 'root' e realm 'pam'.",
        )

    try:
        master_password = decrypt_password(master.encrypted_password)
    except Exception as e:
        raise HTTPException(500, f"Errore decifratura credenziali master: {e}")

    link0 = payload.link0_address or joining.host

    # ── 3. Helper: attempt one join and return the polled result ─────────────
    def _attempt_join() -> tuple[str, dict | None]:
        """Build a fresh client and post the join. Returns (upid, task_result)."""
        invalidate_client(joining.id)
        invalidate_client(master.id)
        jpx = build_client(joining)
        params: dict = {
            "hostname":    master.host,
            "password":    master_password,
            "fingerprint": fingerprint,
            "link0":       link0,
        }
        if payload.force:
            params["force"] = 1
        uid = jpx.cluster.config.join.post(**params)

        result: dict | None = None
        poll_node = upid_node(uid) if isinstance(uid, str) else None
        if poll_node:
            try:
                result = wait_for_task(jpx, poll_node, uid, timeout=120)
            except Exception:
                pass
        return uid, result

    # ── 4. First attempt ─────────────────────────────────────────────────────
    try:
        upid, task_result = _attempt_join()
    except Exception as e:
        raise HTTPException(400, f"Join fallito: {type(e).__name__}: {e}")

    exitstatus = (task_result or {}).get("exitstatus", "unknown")
    log_snippet = (task_result or {}).get("log", "")

    # ── 5. Auto-retry after corosync cleanup ─────────────────────────────────
    # If the task log contains a stale-config indicator we SSH in, remove the
    # offending files, and retry once — transparently, no user action needed.
    if exitstatus not in ("OK", "unknown", "timeout", None) and any(
        err in log_snippet for err in _COROSYNC_ERRORS
    ):
        if joining.pve_username != "root" or joining.pve_realm != "pam":
            raise HTTPException(
                400,
                "Il nodo da aggiungere ha configurazione corosync residua che "
                "deve essere rimossa, ma le credenziali salvate non sono root@pam. "
                f"({joining.pve_username}@{joining.pve_realm}) — "
                "Aggiorna le credenziali del nodo con utente 'root' e realm 'pam' "
                "oppure rimuovi manualmente i file /etc/pve/corosync.conf e "
                "/etc/corosync/authkey sul nodo.",
            )
        try:
            _ssh_cleanup_corosync(joining)
        except Exception as ssh_exc:
            raise HTTPException(
                400,
                f"Pulizia corosync fallita via SSH ({joining.host}): {ssh_exc}\n"
                "Rimuovi manualmente /etc/pve/corosync.conf e /etc/corosync/authkey "
                "sul nodo, poi riprova.",
            )

        # Retry the join now that stale config is gone
        try:
            upid, task_result = _attempt_join()
        except Exception as e:
            raise HTTPException(400, f"Join fallito dopo pulizia corosync: {type(e).__name__}: {e}")

        exitstatus  = (task_result or {}).get("exitstatus", "unknown")
        log_snippet = (task_result or {}).get("log", "")

    # ── 6. Final status check ────────────────────────────────────────────────
    if exitstatus not in ("OK", "unknown", "timeout", None):
        raise HTTPException(
            400,
            f"Join task fallito ({exitstatus}).\n{log_snippet}".strip(),
        )

    return {
        "upid":        upid,
        "joined":      joining.name,
        "to":          master.name,
        "link0":       link0,
        "fingerprint": fingerprint,
        "task":        task_result,
    }


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
