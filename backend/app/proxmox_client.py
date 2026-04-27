"""
Proxmox API wrapper.

Builds a `proxmoxer.ProxmoxAPI` client from a stored credential, correctly
handling self-signed certificates. Exposes a thin collection of helpers used
by the routers (cluster resources, node stats, vm actions, migrations...).
"""

from __future__ import annotations

import threading
import time
import urllib3
from typing import Any, Optional

from proxmoxer import ProxmoxAPI

from .crypto import decrypt_password
from .models import ProxmoxCredential

# Cache authenticated ProxmoxAPI clients to avoid re-doing the auth-ticket
# handshake on every request (saves one HTTP round-trip each time).
_client_cache: dict[int, tuple[ProxmoxAPI, float]] = {}
_client_lock = threading.Lock()
CLIENT_TTL = 270.0  # seconds (Proxmox tickets last 2 h; we refresh well before)


def build_client(cred: ProxmoxCredential) -> ProxmoxAPI:
    """Return a cached (or freshly-created) ProxmoxAPI client."""
    now = time.monotonic()
    with _client_lock:
        entry = _client_cache.get(cred.id)
        if entry and (now - entry[1]) < CLIENT_TTL:
            return entry[0]

    if not cred.verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    password = decrypt_password(cred.encrypted_password)
    user = f"{cred.pve_username}@{cred.pve_realm}"

    client = ProxmoxAPI(
        host=f"{cred.host}:{cred.port}",
        user=user,
        password=password,
        verify_ssl=cred.verify_ssl,
        timeout=15,
    )
    with _client_lock:
        _client_cache[cred.id] = (client, now)
    return client


def invalidate_client(cred_id: int) -> None:
    """Drop the cached client (call on credential update / deletion)."""
    with _client_lock:
        _client_cache.pop(cred_id, None)


# ---------------- High level helpers ----------------

def cluster_resources(px: ProxmoxAPI, kind: Optional[str] = None) -> list[dict]:
    """
    Return a list of cluster resources.
    kind: 'vm', 'node', 'storage', 'sdn', 'pool', or None for everything.
    """
    params = {"type": kind} if kind else {}
    return px.cluster.resources.get(**params)


def cluster_status(px: ProxmoxAPI) -> list[dict]:
    return px.cluster.status.get()


def node_status(px: ProxmoxAPI, node: str) -> dict:
    return px.nodes(node).status.get()


def node_rrddata(px: ProxmoxAPI, node: str, timeframe: str = "hour") -> list[dict]:
    return px.nodes(node).rrddata.get(timeframe=timeframe, cf="AVERAGE")


def vm_rrddata(px: ProxmoxAPI, node: str, vmid: int, kind: str = "qemu",
               timeframe: str = "hour") -> list[dict]:
    branch = px.nodes(node).qemu if kind == "qemu" else px.nodes(node).lxc
    return branch(vmid).rrddata.get(timeframe=timeframe, cf="AVERAGE")


def vm_current(px: ProxmoxAPI, node: str, vmid: int, kind: str = "qemu") -> dict:
    branch = px.nodes(node).qemu if kind == "qemu" else px.nodes(node).lxc
    return branch(vmid).status.current.get()


def vm_config(px: ProxmoxAPI, node: str, vmid: int, kind: str = "qemu") -> dict:
    branch = px.nodes(node).qemu if kind == "qemu" else px.nodes(node).lxc
    return branch(vmid).config.get()


def vm_update_config(px: ProxmoxAPI, node: str, vmid: int,
                     kind: str, params: dict) -> Any:
    """Apply live config changes. Returns UPID if restart required, else None."""
    branch = px.nodes(node).qemu if kind == "qemu" else px.nodes(node).lxc
    return branch(vmid).config.put(**params)


# ---------- Power actions ----------

def _branch(px: ProxmoxAPI, node: str, vmid: int, kind: str):
    return px.nodes(node).qemu(vmid) if kind == "qemu" else px.nodes(node).lxc(vmid)


def vm_start(px, node, vmid, kind="qemu"):    return _branch(px, node, vmid, kind).status.start.post()
def vm_stop(px, node, vmid, kind="qemu"):     return _branch(px, node, vmid, kind).status.stop.post()
def vm_shutdown(px, node, vmid, kind="qemu"): return _branch(px, node, vmid, kind).status.shutdown.post()
def vm_reboot(px, node, vmid, kind="qemu"):   return _branch(px, node, vmid, kind).status.reboot.post()


def vm_delete(px, node, vmid, kind="qemu", purge: bool = True):
    return _branch(px, node, vmid, kind).delete(purge=1 if purge else 0)


def vm_clone(px, node, vmid, newid: int, kind="qemu",
             target: Optional[str] = None, name: Optional[str] = None, full: bool = True):
    """
    Clone a VM/CT. For LXC, Proxmox doesn't support full clone of a *running*
    container without an existing snapshot — we degrade to a linked clone in
    that case (full=0) which the Proxmox API accepts.
    """
    params: dict[str, Any] = {"newid": newid}
    if target: params["target"] = target
    if name:
        # For LXC the keyword is `hostname`, for QEMU it's `name`
        if kind == "lxc":
            params["hostname"] = name
        else:
            params["name"] = name

    if kind == "qemu":
        params["full"] = 1 if full else 0
    else:
        # LXC: pick a sensible default depending on the source state.
        try:
            cur = _branch(px, node, vmid, "lxc").status.current.get()
            running = (cur or {}).get("status") == "running"
        except Exception:
            running = False
        # Full clones of a running LXC fail unless a frozen snapshot exists.
        # Linked clones (full=0) work in both stopped and running states.
        params["full"] = 0 if running else (1 if full else 0)

    return _branch(px, node, vmid, kind).clone.post(**params)


def vm_migrate(px, node, vmid, target_node: str, kind: str = "qemu",
               online: bool = True, with_local_disks: bool = True,
               target_storage: Optional[str] = None) -> str:
    """
    Returns the UPID of the migration task.

    For QEMU online migration with local disks, Proxmox requires an explicit
    `targetstorage` mapping when no shared storage is available. We default
    to `local-lvm` if the caller didn't pass one.
    """
    params: dict[str, Any] = {"target": target_node}
    if kind == "qemu":
        params["online"] = 1 if online else 0
        if with_local_disks:
            params["with-local-disks"] = 1
            # When migrating with local disks, give Proxmox a target storage hint.
            # Empty string means "use the same storage name on the destination".
            if target_storage is not None:
                params["targetstorage"] = target_storage
    else:  # lxc
        # LXC cannot live-migrate; restart it on the destination.
        params["restart"] = 1
        if online:
            params["restart"] = 1
    return _branch(px, node, vmid, kind).migrate.post(**params)


# ---------- Snapshots ----------

def snapshots_list(px, node, vmid, kind="qemu"):
    return _branch(px, node, vmid, kind).snapshot.get()


def snapshot_create(px, node, vmid, snapname: str, description: str = "",
                    vmstate: bool = False, kind: str = "qemu"):
    params = {"snapname": snapname, "description": description}
    if kind == "qemu":
        params["vmstate"] = 1 if vmstate else 0
    return _branch(px, node, vmid, kind).snapshot.post(**params)


def snapshot_delete(px, node, vmid, snapname: str, kind: str = "qemu"):
    return _branch(px, node, vmid, kind).snapshot(snapname).delete()


def snapshot_rollback(px, node, vmid, snapname: str, kind: str = "qemu"):
    return _branch(px, node, vmid, kind).snapshot(snapname).rollback.post()


# ---------- Backups ----------

def backup_create(px, node: str, vmid: int, storage: str, mode: str = "snapshot",
                  compress: str = "zstd", notes: Optional[str] = None) -> str:
    params: dict[str, Any] = {
        "vmid": vmid, "storage": storage, "mode": mode, "compress": compress,
    }
    if notes: params["notes-template"] = notes
    return px.nodes(node).vzdump.post(**params)


def backup_list(px, node: str, storage: str, vmid: Optional[int] = None) -> list[dict]:
    params = {"content": "backup"}
    if vmid: params["vmid"] = vmid
    return px.nodes(node).storage(storage).content.get(**params)


# ---------- Tasks ----------

def task_status(px, node: str, upid: str) -> dict:
    return px.nodes(node).tasks(upid).status.get()


def task_log(px, node: str, upid: str, start: int = 0, limit: int = 50) -> list[dict]:
    return px.nodes(node).tasks(upid).log.get(start=start, limit=limit)


# ---------- Resource discovery (for create forms) ----------

def next_vmid(px) -> int:
    """First free VMID across the whole cluster."""
    return int(px.cluster.nextid.get())


def node_storages(px, node: str, content: Optional[str] = None) -> list[dict]:
    """
    Storages enabled on a node. `content` filters by the kind of data the
    storage can hold: 'images' (VM disks), 'rootdir' (CT volumes),
    'iso', 'vztmpl', 'backup', 'snippets'.
    """
    params = {}
    if content:
        params["content"] = content
    return px.nodes(node).storage.get(**params)


def node_iso_list(px, node: str) -> list[dict]:
    """Every ISO image available on any storage of the node."""
    out: list[dict] = []
    for st in node_storages(px, node, content="iso"):
        name = st["storage"]
        try:
            items = px.nodes(node).storage(name).content.get(content="iso") or []
            for it in items:
                it["storage"] = name
                out.append(it)
        except Exception:
            continue
    return out


def node_ct_templates(px, node: str) -> list[dict]:
    """CT templates (vztmpl) across the node's storages."""
    out: list[dict] = []
    for st in node_storages(px, node, content="vztmpl"):
        name = st["storage"]
        try:
            items = px.nodes(node).storage(name).content.get(content="vztmpl") or []
            for it in items:
                it["storage"] = name
                out.append(it)
        except Exception:
            continue
    return out


def node_networks(px, node: str) -> list[dict]:
    """Return bridges (type=bridge) configured on the node."""
    nets = px.nodes(node).network.get() or []
    return [n for n in nets if n.get("type") == "bridge"]


# ---------- Create VM / CT ----------

def create_qemu(px, node: str, params: dict) -> str:
    """POST /nodes/{node}/qemu. Returns UPID of the task."""
    return px.nodes(node).qemu.post(**params)


def create_lxc(px, node: str, params: dict) -> str:
    """POST /nodes/{node}/lxc. Returns UPID of the task."""
    return px.nodes(node).lxc.post(**params)
