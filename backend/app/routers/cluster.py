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
from ..schemas import ClusterCreateIn, ClusterJoinIn, ClusterLeaveIn, ClusterDestroyIn
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
            # True only for the node this credential directly connects to.
            # Used by the frontend to deduplicate physical servers: when the same
            # node appears in multiple credential trees (cluster members), the entry
            # marked local=True carries the authoritative stats for that machine.
            "local":   n.get("local", 0) == 1,
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

    # Deduplicate backup_targets by storage name.
    # A shared PBS storage appears once per cluster node in cluster_resources,
    # but it is the same physical target — keep only one entry per storage name.
    seen_bt: set[str] = set()
    unique_backup_targets: list[dict] = []
    for bt in backup_targets:
        key = bt["storage"]
        if key not in seen_bt:
            seen_bt.add(key)
            unique_backup_targets.append(bt)

    return {
        "cluster":        cluster_info,
        "nodes":          list(by_node.values()),
        "backup_targets": unique_backup_targets,
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
    payload:          ClusterCreateIn,
    background_tasks: BackgroundTasks,
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
        #
        # FIX: use `pvecm status | grep Quorate` instead of bare `pvecm status`
        # so we only skip when a *valid, quorate* cluster is already running.
        # A bare `pvecm status` exits 0 even when corosync is running with a
        # broken/empty corosync.conf (left over from a previous failed attempt),
        # which would cause `pvecm create` to be silently skipped and leave the
        # master with an invalid config that causes every subsequent join to fail
        # with "invalid corosync.conf ! no nodes found".
        create_cmd = (
            f"pvecm status 2>&1 | grep -q 'Quorate:' && "
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

    combined = "\n".join(part for part in (out, err) if part).strip()
    if "__PMX_CLUSTER_ALREADY_EXISTS__" in combined:
        client.close()
        raise HTTPException(
            400,
            f"Il nodo primario '{primary.name}' appartiene già a un cluster Proxmox. "
            "Apri o aggiorna quel cluster invece di crearne uno nuovo dallo stesso nodo.",
        )

    # Auto-cleanup + retry: if pvecm create failed because a stale corosync.conf
    # already exists (left by a previous partial create that timed out), remove
    # the file and try once more.  This lets the user hit "Nuovo cluster" a second
    # time without having to manually SSH in and delete the file.
    if exit_code != 0 and (
        "already exists" in combined or "corosync.conf" in combined
    ):
        try:
            # /etc/pve/ is a FUSE fs managed by pve-cluster — plain `rm` is
            # denied even as root while the service is running.  We must stop
            # pve-cluster, remount pmxcfs in local mode, delete, then restart.
            for cleanup_cmd in [
                "systemctl stop pve-cluster 2>/dev/null; true",
                "systemctl stop corosync 2>/dev/null; true",
                "pmxcfs -l >/dev/null 2>&1 &",
                "sleep 2",
                "rm -f /etc/pve/corosync.conf 2>/dev/null; true",
                "rm -f /etc/corosync/authkey 2>/dev/null; true",
                "killall pmxcfs 2>/dev/null; true",
                "systemctl start pve-cluster 2>/dev/null; true",
                "sleep 2",
            ]:
                _, cs, ce = client.exec_command(cleanup_cmd, timeout=30)
                cs.read(); ce.read()

            retry_cmd = (
                f"pvecm create {shlex.quote(cluster_name)} --link0 {shlex.quote(link0)}"
            )
            _, rs, re_ = client.exec_command(retry_cmd, timeout=120)
            r_out  = rs.read().decode("utf-8", errors="replace").strip()
            r_err  = re_.read().decode("utf-8", errors="replace").strip()
            exit_code = rs.channel.recv_exit_status()
            combined  = "\n".join(p for p in (r_out, r_err) if p).strip()
        except Exception as exc:
            client.close()
            raise HTTPException(
                400,
                f"Pulizia corosync.conf fallita su {primary.host}: {exc}\n"
                "Rimuovi manualmente /etc/pve/corosync.conf sul nodo e riprova.",
            )

    if exit_code != 0:
        client.close()
        raise HTTPException(400, f"Creazione cluster fallita.\n{combined}".strip())

    # Wait for corosync to fully initialise before returning.
    # `pvecm create` can exit 0 before corosync has written a valid nodelist
    # to corosync.conf; a join attempt arriving seconds later would then see
    # "invalid corosync.conf ! no nodes found" on the master side.
    # We poll `pvecm status` until "Cluster information" appears (up to 30 s).
    try:
        _, v_stdout, _ = client.exec_command(
            "for i in $(seq 1 30); do "
            "  pvecm status 2>&1 | grep -q 'Cluster information' && exit 0; "
            "  sleep 1; "
            "done; exit 1",
            timeout=40,
        )
        v_stdout.read()   # drain output
        v_exit = v_stdout.channel.recv_exit_status()
    except Exception:
        v_exit = -1
    finally:
        client.close()

    if v_exit != 0:
        raise HTTPException(
            400,
            "Cluster creato ma corosync non si è avviato entro 30 secondi. "
            "Controlla i log su proxmox (journalctl -u corosync) e riprova.",
        )

    invalidate_client(primary.id)

    # ── Schedule automatic Ceph setup in the background ──────────────────────
    # Run after the HTTP response is sent so the cluster creation call returns
    # instantly without waiting for the (potentially multi-minute) Ceph install.
    background_tasks.add_task(_bg_ceph_setup, primary.id, user.id, True)

    return {
        "name":    cluster_name,
        "primary": {"id": primary.id, "name": primary.name, "host": primary.host},
        "nodes":   [],
        "status":  "ok",
        "link0":   link0,
        "output":  combined,
    }


import logging as _logging
_ceph_log = _logging.getLogger(__name__ + ".ceph")


def _ssh_exec(client, cmd: str, timeout: int = 300) -> tuple[int, str, str]:
    """Run a command over an open paramiko SSH connection and return (rc, stdout, stderr)."""
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out  = stdout.read().decode("utf-8", errors="replace").strip()
    err  = stderr.read().decode("utf-8", errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _ssh_setup_ceph(client, host: str, is_primary: bool) -> None:
    """
    Install and configure Ceph on a Proxmox node via an already-open SSH connection.

    is_primary=True  → full setup: install + init + mon + mgr + OSD + pool
    is_primary=False → joining node: install + mon + mgr + OSD (init/pool on primary)

    OSD disk selection
    ──────────────────
    We pick the first disk that:
      • is not the OS boot disk
      • has no partitions (completely blank)
    If no such disk is found we skip OSD creation (the cluster still works, just
    without local OSD on that node — operators can add OSDs manually later).

    All errors are logged but never raised — Ceph setup failure must not break
    the cluster creation/join that already succeeded.
    """
    def run(cmd, timeout=300):
        rc, out, err = _ssh_exec(client, cmd, timeout)
        _ceph_log.debug("[%s] rc=%d cmd=%r out=%r err=%r", host, rc, cmd[:80], out[:200], err[:200])
        return rc, out, err

    try:
        # ── 0. Fix apt sources: disable enterprise repo (needs paid key) ─────
        # Fresh Proxmox installs ship with enterprise.proxmox.com enabled.
        # Without a valid subscription key it returns 401, breaking apt-get
        # update and therefore pveceph install.  We comment it out and add the
        # no-subscription community repo instead, then update the package lists.
        _ceph_log.info("[%s] Configuring apt: disabling enterprise repo, enabling no-subscription…", host)
        run(
            r"""
set -e
# Detect distro codename (bookworm / trixie / …)
CODENAME=$(. /etc/os-release 2>/dev/null && echo "$VERSION_CODENAME")
[ -z "$CODENAME" ] && CODENAME=$(lsb_release -sc 2>/dev/null || echo "bookworm")

# Disable enterprise PVE repo (comment out all non-comment lines)
ENT=/etc/apt/sources.list.d/pve-enterprise.list
if [ -f "$ENT" ]; then
    sed -i 's|^deb |# deb |g' "$ENT"
fi

# Disable enterprise Ceph repo if present
CENT=/etc/apt/sources.list.d/ceph.list
if [ -f "$CENT" ]; then
    sed -i 's|^deb https://enterprise\.proxmox\.com|# deb https://enterprise.proxmox.com|g' "$CENT"
fi

# Add no-subscription PVE repo if not already present
NOSUB=/etc/apt/sources.list.d/pve-no-subscription.list
if ! grep -qs 'pve-no-subscription' "$NOSUB" 2>/dev/null; then
    echo "deb http://download.proxmox.com/debian/pve $CODENAME pve-no-subscription" > "$NOSUB"
fi
""",
            timeout=15,
        )
        run("apt-get update -qq 2>&1 | grep -v '^Hit' | head -20 || true", timeout=120)

        # ── 1. Install Ceph packages ─────────────────────────────────────────
        # PVE 8.x ships Reef; PVE 9.x ships Squid. Detect from pveversion.
        _, pve_ver_out, _ = run("pveversion --verbose 2>/dev/null | grep pve-manager | head -1", timeout=10)
        pve_major = 9  # safe default
        try:
            pve_major = int(pve_ver_out.strip().split("/")[1].split(".")[0])
        except Exception:
            pass
        ceph_version = "squid" if pve_major >= 9 else "reef"

        _ceph_log.info("[%s] PVE major=%d — installing Ceph %s (no-subscription)…", host, pve_major, ceph_version)
        rc, out, err = run(
            f"pveceph install --version {ceph_version} --repository no-subscription",
            timeout=900,  # installation can take 5-10 min on slow mirrors
        )
        if rc != 0:
            _ceph_log.warning("[%s] pveceph install exited %d: %s", host, rc, err[:300])

        if is_primary:
            # ── 2. Detect cluster network (first non-default, non-link-local) ─
            _, net_out, _ = run(
                "ip -4 route | grep -v default | awk '{print $1}'"
                " | grep '/' | grep -v '^169\\.' | head -1",
                timeout=10,
            )
            network = net_out.strip() or "10.0.0.0/8"

            # ── 3. Init Ceph (idempotent: skip if already initialised) ────────
            _ceph_log.info("[%s] Initialising Ceph on network %s…", host, network)
            run(
                f"pveceph status 2>/dev/null | grep -q 'health' || "
                f"pveceph init --network {shlex.quote(network)}",
                timeout=60,
            )

        # ── 4. Create monitor ────────────────────────────────────────────────
        _ceph_log.info("[%s] Creating Ceph monitor…", host)
        run("pveceph createmon 2>/dev/null; true", timeout=60)

        # ── 5. Create manager ────────────────────────────────────────────────
        _ceph_log.info("[%s] Creating Ceph manager…", host)
        run("pveceph createmgr 2>/dev/null; true", timeout=60)

        # ── 6. Find first blank disk for OSD ─────────────────────────────────
        _, disk_out, _ = run(
            r"""
BOOT=$(lsblk -n -o PKNAME $(findmnt -n -o SOURCE / 2>/dev/null) 2>/dev/null | head -1)
for DEV in $(lsblk -n -d -o NAME,TYPE 2>/dev/null | awk '$2=="disk"{print $1}'); do
    [ "$DEV" = "$BOOT" ] && continue
    PARTS=$(lsblk -n -o NAME /dev/$DEV 2>/dev/null | wc -l)
    [ "$PARTS" -le 1 ] && echo "/dev/$DEV" && break
done
""",
            timeout=15,
        )
        disk = disk_out.strip()
        if disk and disk.startswith("/dev/"):
            _ceph_log.info("[%s] Creating OSD on %s…", host, disk)
            run(f"pveceph createosd {shlex.quote(disk)} 2>/dev/null; true", timeout=180)
        else:
            _ceph_log.warning("[%s] No blank disk found for Ceph OSD — skipping OSD creation.", host)

        if is_primary:
            # ── 7. Wait for OSD to come up, then create pool + storage ────────
            run("sleep 15", timeout=20)
            _ceph_log.info("[%s] Creating Ceph pool 'ceph-pool'…", host)
            run(
                "pveceph pool create ceph-pool --pg_num 128 --add_storages 1 2>/dev/null; true",
                timeout=120,
            )

        _ceph_log.info("[%s] Ceph setup done (is_primary=%s).", host, is_primary)

    except Exception as exc:
        _ceph_log.error("[%s] Ceph setup failed: %s", host, exc)
        # Never propagate — cluster join/create must not be invalidated by Ceph errors.


def _bg_ceph_setup(cred_id: int, user_id: int, is_primary: bool) -> None:
    """
    Background task: open a fresh SSH connection to the node and run Ceph setup.
    Uses its own DB session so it can be scheduled as a FastAPI BackgroundTask.
    """
    import paramiko
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        from ..models import ProxmoxCredential
        cred = db.query(ProxmoxCredential).get(cred_id)
        if not cred:
            return
        password = decrypt_password(cred.encrypted_password)
        client   = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=cred.host, port=22, username="root",
            password=password, timeout=30, banner_timeout=30,
        )
        try:
            _ssh_setup_ceph(client, cred.host, is_primary=is_primary)
        finally:
            client.close()
    except Exception as exc:
        _ceph_log.error("bg_ceph_setup failed for cred_id=%s: %s", cred_id, exc)
    finally:
        db.close()


def _ssh_cleanup_corosync(cred: "ProxmoxCredential") -> None:  # noqa: F821
    """
    SSH into a node and remove stale corosync/cluster configuration files.

    Called automatically when a join task fails with a corosync config error
    (invalid corosync.conf, authkey already exists, corosync already running).
    The credential must belong to root (root@pam) because only root can stop
    corosync and delete files under /etc/pve and /etc/corosync.

    /etc/pve/ is a FUSE filesystem managed by pve-cluster (pmxcfs).
    Files inside it cannot be removed with plain `rm` while pve-cluster is
    running — even as root.  The correct procedure is:
      1. Stop pve-cluster (unmounts the FUSE fs)
      2. Stop corosync
      3. Re-mount pmxcfs in local (standalone) mode so /etc/pve is writable
      4. Delete the stale files
      5. Kill the temporary pmxcfs process
      6. Restart pve-cluster normally
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
        "systemctl stop pve-cluster 2>/dev/null; true",
        "systemctl stop corosync 2>/dev/null; true",
        "pmxcfs -l >/dev/null 2>&1 &",
        "sleep 2",
        "rm -f /etc/pve/corosync.conf 2>/dev/null; true",
        "rm -f /etc/corosync/authkey 2>/dev/null; true",
        "killall pmxcfs 2>/dev/null; true",
        "systemctl start pve-cluster 2>/dev/null; true",
    ]
    for cmd in cmds:
        _, stdout, stderr = client.exec_command(cmd, timeout=20)
        stdout.read()   # drain so the channel doesn't block
        stderr.read()
    client.close()


# Substrings that identify corosync errors on the *joining* node.
# These are safe to auto-clean (remove stale files from the joiner) and retry.
_JOINING_COROSYNC_ERRORS = (
    "corosync.conf already exists",
    "authkey already exists",
    "corosync is already running",
)

# Substrings that identify corosync errors on the *master/cluster* node.
# Cleaning the joining node won't help here — the master itself has a broken
# config. Surface a clear error instead of silently retrying the wrong fix.
_MASTER_COROSYNC_ERRORS = (
    "An error occurred on the cluster node: invalid corosync.conf",
    "cluster node: invalid corosync",
    "no nodes found",
)

# Legacy alias kept for any other callers (covers both sides).
_COROSYNC_ERRORS = _JOINING_COROSYNC_ERRORS + _MASTER_COROSYNC_ERRORS


@router.post("/{cred_id}/cluster/join")
def cluster_join(
    cred_id: int, payload: ClusterJoinIn,
    background_tasks: BackgroundTasks,
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
            f"Il nodo master '{master.name}' ({master.host}) non è in nessun cluster Proxmox "
            f"(dettaglio: {type(exc).__name__}: {exc}).\n\n"
            "Soluzione: nel pannello 'Gestione Cluster' usa prima 'Elimina Cluster' per "
            "rimuovere la voce locale, poi clicca 'Nuovo cluster' per creare il cluster "
            "reale su Proxmox (il pulsante ora esegue pvecm create via SSH).",
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

    # ── 5. Auto-retry / error routing after corosync failures ────────────────
    if exitstatus not in ("OK", "unknown", "timeout", None):

        # 5a. Error is on the MASTER — the master's corosync.conf is invalid.
        #     Cleaning the joining node won't help; surface a clear message.
        if any(e in log_snippet for e in _MASTER_COROSYNC_ERRORS):
            raise HTTPException(
                400,
                f"Join fallito ({exitstatus}): la configurazione corosync del "
                f"nodo master '{master.name}' ({master.host}) è invalida "
                f"(no nodes found).\n\n"
                "Soluzione: usa 'Elimina Cluster' per ripulire il nodo master, "
                "poi ricrea il cluster e riprova il join.\n\n"
                f"Dettaglio Proxmox: {log_snippet}".strip(),
            )

        # 5b. Error is on the JOINING node — stale local corosync files.
        #     Auto-clean and retry once, transparently.
        if any(e in log_snippet for e in _JOINING_COROSYNC_ERRORS):
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

    # ── Schedule automatic Ceph setup in the background ──────────────────────
    # Both the master node and the joining node need Ceph installed/configured.
    # We schedule two background tasks — one for each — so the HTTP response
    # returns immediately without blocking on the (potentially lengthy) install.
    #
    # master (is_primary=True):  ensures the primary has init + pool created.
    # joining (is_primary=False): installs packages + mon + mgr + OSD only;
    #                             init and pool creation happen on the primary.
    background_tasks.add_task(_bg_ceph_setup, master.id,  user.id, True)
    background_tasks.add_task(_bg_ceph_setup, joining.id, user.id, False)

    return {
        "upid":        upid,
        "joined":      joining.name,
        "to":          master.name,
        "link0":       link0,
        "fingerprint": fingerprint,
        "task":        task_result,
    }


@router.post("/{cred_id}/cluster/leave")
def cluster_node_leave(
    cred_id: int, payload: ClusterLeaveIn,
    db:   Session = Depends(get_db),
    user: User    = Depends(require_senior),
):
    """
    Remove a node from the cluster it belongs to.

    Why NOT pvecm delnode
    ─────────────────────
    `pvecm delnode` writes to /etc/pve/ atomically by creating a temp file
    (corosync.conf.new.tmp.XXXX).  The pmxcfs FUSE layer only allows writes to
    a specific whitelist of known paths — arbitrary temp-file names are denied
    even as root, so `pvecm delnode` reliably fails with "Permission denied".

    Instead we:
      1. Stop pve-cluster on the master (unmounts the FUSE, /etc/pve becomes a
         plain directory that root can write).
      2. Mount pmxcfs in local/standalone mode (-l flag) so the directory is
         accessible while we edit it.
      3. Use a small inline Python script to remove the leaving node's block
         from corosync.conf and update expected_votes accordingly.
      4. Kill the temporary pmxcfs process and restart pve-cluster + corosync.

    Steps 5-8 mirror the same procedure on the leaving node so it becomes a
    standalone Proxmox host again.
    """
    import paramiko

    master  = _get_cred(db, user, cred_id)
    leaving = _get_cred(db, user, payload.node_cred_id)

    if master.pve_username != "root" or master.pve_realm != "pam":
        raise HTTPException(400, "Il master richiede credenziali root@pam.")
    if leaving.pve_username != "root" or leaving.pve_realm != "pam":
        raise HTTPException(400, "Il nodo da rimuovere richiede credenziali root@pam.")

    try:
        master_password  = decrypt_password(master.encrypted_password)
        leaving_password = decrypt_password(leaving.encrypted_password)
    except Exception as e:
        raise HTTPException(500, f"Errore decifratura credenziali: {e}")

    # ── 1. Get the Proxmox node name from the leaving node via SSH ───────────
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname=leaving.host, port=22, username="root",
                    password=leaving_password, timeout=20, banner_timeout=20)
        _, hs, _ = ssh.exec_command("hostname", timeout=10)
        leaving_node_name = hs.read().decode("utf-8", errors="replace").strip()
    except Exception as e:
        raise HTTPException(400, f"Impossibile connettersi a {leaving.host} via SSH: {e}")
    finally:
        ssh.close()

    if not leaving_node_name:
        raise HTTPException(400, f"Impossibile determinare il nome Proxmox del nodo {leaving.host}.")

    # ── 2. Edit corosync.conf on the master to remove the node ───────────────
    #
    # Inline Python script that:
    #   • removes the node { ... } block whose name matches the leaving node
    #   • decrements expected_votes by 1 (minimum 1)
    # Written as a single-quoted shell argument so it survives SSH quoting.
    py_edit = (
        "import re, sys; "
        "n=sys.argv[1]; "
        "p='/etc/pve/corosync.conf'; "
        "c=open(p).read(); "
        "c=re.sub(r'\\n[ \\t]+node[ \\t]*\\{[^}]*\\bname:[ \\t]+'+re.escape(n)+'\\b[^}]*\\}','',c,flags=re.DOTALL); "
        "rem=len(re.findall(r'^\\s+node\\s*\\{',c,re.MULTILINE)); "
        "c=re.sub(r'(expected_votes:\\s*)\\d+',lambda m:m.group(1)+str(max(1,rem)),c); "
        "open(p,'w').write(c); "
        "print('OK',rem,'nodes remain')"
    )

    ssh_master = paramiko.SSHClient()
    ssh_master.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    del_output = ""
    try:
        ssh_master.connect(hostname=master.host, port=22, username="root",
                           password=master_password, timeout=30, banner_timeout=30)
        # Correct restart order:
        #   corosync MUST start before pve-cluster.
        #   If pve-cluster starts first, it syncs from the running corosync
        #   which might still hold the old node in its membership ring,
        #   causing it to re-create /etc/pve/nodes/<leaving_node>/ and
        #   show the red-X ghost in the web UI.
        for cmd in [
            # 1. Stop in reverse dependency order
            "systemctl stop pve-cluster 2>/dev/null; true",
            "systemctl stop corosync 2>/dev/null; true",
            # 2. Mount pmxcfs in local (writable) mode
            "pmxcfs -l >/dev/null 2>&1 &",
            "sleep 3",
            # 3. Edit corosync.conf — remove node block + update expected_votes
            f"python3 -c {shlex.quote(py_edit)} {shlex.quote(leaving_node_name)}",
            # 4. Delete node data dir — prevents ghost red-X in Proxmox web UI
            f"rm -rf /etc/pve/nodes/{shlex.quote(leaving_node_name)} 2>/dev/null; true",
            # 5. Unmount local pmxcfs
            "killall pmxcfs 2>/dev/null; true",
            "sleep 1",
            # 6. Start corosync FIRST with the new single-node config
            "systemctl start corosync 2>/dev/null; true",
            "sleep 3",
            # 7. Start pve-cluster — syncs from corosync (now 1 node only)
            "systemctl start pve-cluster 2>/dev/null; true",
        ]:
            _, so, se = ssh_master.exec_command(cmd, timeout=30)
            out = so.read().decode("utf-8", errors="replace").strip()
            err = se.read().decode("utf-8", errors="replace").strip()
            rc  = so.channel.recv_exit_status()
            if out: del_output += out + "\n"
            if err: del_output += err + "\n"
            # Abort if the Python edit step fails
            if "python3" in cmd and rc != 0:
                raise RuntimeError(
                    f"Modifica corosync.conf fallita (exit {rc}): {err or out}"
                )
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Errore SSH sul master ({master.host}): {e}")
    finally:
        ssh_master.close()

    del_combined = del_output.strip()

    # ── 3. Cleanup cluster config on the leaving node ────────────────────────
    cleanup_warning: str | None = None
    ssh_leave = paramiko.SSHClient()
    ssh_leave.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh_leave.connect(hostname=leaving.host, port=22, username="root",
                          password=leaving_password, timeout=30, banner_timeout=30)
        for cmd in [
            "systemctl stop pve-cluster 2>/dev/null; true",
            "systemctl stop corosync 2>/dev/null; true",
            # Mount pmxcfs in local mode so /etc/pve/ is writable
            "pmxcfs -l >/dev/null 2>&1 &",
            "sleep 3",
            # Remove cluster config from both locations:
            # /etc/pve/corosync.conf  — managed by pve-cluster (pmxcfs)
            # /etc/corosync/corosync.conf — used directly by corosync daemon
            # Without removing both, corosync can still restart and try to
            # re-join the cluster after pve-cluster restores the config.
            "rm -f /etc/pve/corosync.conf 2>/dev/null; true",
            "rm -f /etc/corosync/corosync.conf 2>/dev/null; true",
            "rm -f /etc/corosync/authkey 2>/dev/null; true",
            "killall pmxcfs 2>/dev/null; true",
            "sleep 1",
            # Start pve-cluster standalone (no corosync.conf → standalone mode)
            "systemctl start pve-cluster 2>/dev/null; true",
        ]:
            _, cs, ce = ssh_leave.exec_command(cmd, timeout=20)
            cs.read(); ce.read()
    except Exception as e:
        # delnode succeeded on master — the node IS removed from the cluster.
        # Cleanup failure is non-fatal: report as a warning.
        cleanup_warning = (
            f"Nodo rimosso dal cluster, ma la pulizia del config su {leaving.host} "
            f"è fallita ({e}). Potrebbe essere necessario rimuovere manualmente "
            "/etc/pve/corosync.conf sul nodo."
        )
    finally:
        ssh_leave.close()

    invalidate_client(master.id)
    invalidate_client(leaving.id)

    return {
        "node":                  leaving_node_name,
        "removed_from_cluster":  True,
        "cleanup_warning":       cleanup_warning,
        "master":                master.name,
        "output":                del_combined,
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
