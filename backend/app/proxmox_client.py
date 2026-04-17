"""
Proxmox API wrapper.

Builds a `proxmoxer.ProxmoxAPI` client from a stored credential, correctly
handling self-signed certificates. Exposes a thin collection of helpers used
by the routers (cluster resources, node stats, vm actions, migrations...).

Each call instantiates a fresh client; proxmoxer uses PVE ticket auth which
is cheap and keeps things stateless across workers. For heavier deployments
cache the client per (cred_id, worker) - left as an exercise.
"""

from __future__ import annotations

import urllib3
from typing import Any, Optional

from proxmoxer import ProxmoxAPI

from .crypto import decrypt_password
from .models import ProxmoxCredential


def build_client(cred: ProxmoxCredential) -> ProxmoxAPI:
    """Create a ProxmoxAPI client from a DB credential row."""
    if not cred.verify_ssl:
        # Silence self-signed warnings on homelab / lab setups
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    password = decrypt_password(cred.encrypted_password)
    user = f"{cred.pve_username}@{cred.pve_realm}"

    return ProxmoxAPI(
        host=f"{cred.host}:{cred.port}",
        user=user,
        password=password,
        verify_ssl=cred.verify_ssl,
        timeout=15,
    )


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
    params: dict[str, Any] = {"newid": newid, "full": 1 if full else 0}
    if target: params["target"] = target
    if name:   params["name"] = name
    return _branch(px, node, vmid, kind).clone.post(**params)


def vm_migrate(px, node, vmid, target_node: str, kind: str = "qemu",
               online: bool = True, with_local_disks: bool = True) -> str:
    """Returns the UPID of the migration task."""
    params: dict[str, Any] = {"target": target_node}
    if kind == "qemu":
        params["online"] = 1 if online else 0
        if with_local_disks:
            params["with-local-disks"] = 1
    else:  # lxc
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
