"""
Background migration runner.

A migration in Proxmox is an asynchronous PVE task identified by a UPID.
We kick it off, then poll its status/log endpoints from a FastAPI BackgroundTask
to update progress in the DB, which the UI fetches via /api/tasks.
"""

from __future__ import annotations

import re
import time
import uuid
import logging
from typing import Optional

from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import ProxmoxCredential, MigrationTask
from .proxmox_client import (
    build_client, vm_migrate, task_status, task_log,
    node_storages, vm_config as _vm_config,
    vm_update_config as _vm_update_config,
    ha_resource_get, ha_resource_set_state,
)


log = logging.getLogger(__name__)
PROGRESS_RE     = re.compile(r"(\d{1,3})\s*%")
_DISK_KEY_RE    = re.compile(r"^(scsi|virtio|ide|sata|efidisk)\d+$")
_LXC_DISK_RE    = re.compile(r"^(rootfs|mp\d+)$")
# Matches the rsync progress line that Proxmox emits for LXC offline migration:
#   "2026-04-29 14:13:17 6286540800 bytes (6.3 GB, 5.9 GiB) copied, 90 s, 69.9 MB/s"
# The line starts with a timestamp, so we use search() not match() and anchor
# on the "bytes … copied" pattern rather than line start.
_BYTES_COPIED_RE = re.compile(r"(\d{6,})\s+bytes\b.*?\bcopied\b")
# Matches size=50G / size=8192M / size=1.5T inside disk config strings
_SIZE_RE        = re.compile(r"size=(\d+(?:\.\d+)?)([TGKM]?)", re.IGNORECASE)

# Log keywords that indicate the actual failure reason in a Proxmox task log.
_ERROR_KEYWORDS = ("error:", "task error", "can't", "cannot", "failed", "abort", "refused")


def _extract_error_from_log(lines: list[dict]) -> str | None:
    """
    Return the most meaningful error context from a Proxmox task log.

    Strategy:
      1. Collect all lines matching error keywords.
      2. Remove the generic last-line summary ("TASK ERROR: migration aborted",
         "TASK ERROR: job errors") — it is always present and not informative.
      3. Return the remaining lines joined with newlines (most specific first).
      4. If nothing remains, fall back to the last error line (generic summary).
    """
    # Patterns that are the generic summary line — not useful on their own
    _GENERIC = ("task error: migration aborted", "task error: job errors",
                "task error: command", "task ok")

    all_error: list[str] = []
    for entry in lines:
        text = (entry.get("t") or entry.get("text") or "").strip()
        if not text:
            continue
        tl = text.lower()
        if any(kw in tl for kw in _ERROR_KEYWORDS):
            all_error.append(text)

    if not all_error:
        return None

    # Filter out generic summary lines
    specific = [t for t in all_error if not any(g in t.lower() for g in _GENERIC)]
    chosen   = specific if specific else all_error

    # Return the last few most relevant lines (avoid huge messages)
    return "\n".join(chosen[-5:]) if chosen else None


def _cdrom_iso_entries(config: dict) -> dict[str, str]:
    """
    Return {drive_key: original_value} for every CD-ROM drive that has an ISO
    image actually mounted (i.e. not just an empty tray).

    Proxmox CD-ROM config lines look like:
      ide2: local:iso/virtio-win-0.1.285.iso,media=cdrom
      ide2: none,media=cdrom          ← empty tray — excluded

    These entries cause migration to fail when the ISO storage type ('iso') is
    not available on the target node's storage (e.g. local-lvm only has 'images').
    We eject them before the migration and restore afterwards.
    """
    result: dict[str, str] = {}
    for key, val in config.items():
        if not _DISK_KEY_RE.match(key):
            continue
        if not isinstance(val, str):
            continue
        if "media=cdrom" not in val:
            continue
        # First comma-separated segment is the storage:path or "none"
        first_part = val.split(",")[0].strip()
        if first_part == "none" or ":" not in first_part:
            continue   # empty tray — nothing to eject
        result[key] = val
    return result


def _total_disk_bytes(config: dict, kind: str) -> int:
    """
    Sum all disk sizes declared in a VM/CT config dict and return total bytes.

    QEMU: iterates scsi/virtio/ide/sata keys, skips CD-ROMs.
    LXC:  iterates rootfs + mpN mount-point keys.

    Config values contain a comma-separated options string; the disk size is
    carried as the ``size=XG`` option, e.g.:
      virtio0: local-lvm:vm-101-disk-0,size=50G
      rootfs:  local:subvol-102-disk-0,size=8G

    Returns 0 if no parseable disk is found (callers fall back gracefully).
    """
    _MULT = {"T": 1 << 40, "G": 1 << 30, "M": 1 << 20, "K": 1 << 10, "": 1}
    total = 0
    for key, val in config.items():
        if not isinstance(val, str):
            continue
        if kind == "qemu":
            if not _DISK_KEY_RE.match(key):
                continue
            if "media=cdrom" in val:
                continue
        elif kind == "lxc":
            if not _LXC_DISK_RE.match(key):
                continue
        else:
            continue
        m = _SIZE_RE.search(val)
        if m:
            num  = float(m.group(1))
            unit = (m.group(2) or "").upper()
            total += int(num * _MULT.get(unit, 1))
    return total


def _disk_storages(config: dict) -> set[str]:
    """
    Return the set of storage names used by VM disk devices in a PVE config dict.
    Skips CD-ROM/ISO entries (media=cdrom or .iso suffix).
    """
    result: set[str] = set()
    for key, val in config.items():
        if not _DISK_KEY_RE.match(key):
            continue
        if not isinstance(val, str) or ":" not in val:
            continue
        # skip cdrom / iso media
        if "media=cdrom" in val:
            continue
        storage_name = val.split(":")[0].strip()
        if storage_name:
            result.add(storage_name)
    return result


def start_migration(
    user_id: int,
    cred: ProxmoxCredential,
    node: str,
    vmid: int,
    kind: str,
    target_node: str,
    online: bool = True,
    with_local_disks: bool = True,
) -> tuple["MigrationTask", "dict | None", "dict[str, str]", int]:
    """
    Create DB row, launch PVE migration, return (task, ha_restore, cdrom_to_restore).

    Migration parameter strategy
    ─────────────────────────────
    Proxmox migration semantics differ depending on storage type:

    • Shared storage (Ceph RBD, NFS, iSCSI, …)
      Data is already accessible from every node — passing ``with-local-disks``
      or ``targetstorage`` is wrong and causes Proxmox to abort with
      "migration aborted". We must send a bare migrate request (target only).

    • Local storage (local-lvm, local, dir, …) + offline migration
      Proxmox needs ``with-local-disks: 1`` and an explicit ``targetstorage``
      on the destination; without it the task also aborts immediately.
      We auto-detect the first 'images'-compatible storage on the target node.

    • Local storage + online (live) migration
      Proxmox rejects live migration of local-disk VMs unless the cluster
      has a compatible migration network or the user forces it. We pass
      ``with-local-disks: 1`` and let Proxmox surface any remaining errors.

    CD-ROM ISO ejection
    ───────────────────
    Mounted ISO images (e.g. virtio-win drivers) are ejected before the migrate
    call and restored afterwards (on the target on success, on the source on
    failure). Without this, Proxmox aborts with "content type 'iso' is not
    available on storage 'local-lvm'" because the target storage only holds
    VM disk images, not ISO files.
    """
    px = build_client(cred)

    use_with_local_disks: bool           = False
    target_storage:       str | None     = None
    config:               dict           = {}
    cdrom_to_restore:     dict[str, str] = {}
    total_bytes:          int            = 0

    if kind == "qemu":
        # ── Disk storage detection (determines migration parameters) ──────────
        try:
            config        = _vm_config(px, node, vmid, kind)
            disk_st_names = _disk_storages(config)

            if disk_st_names:
                # Map storage name → storage info on the source node
                node_st_map = {
                    s["storage"]: s
                    for s in node_storages(px, node)
                }
                shared_flags = [
                    node_st_map.get(s, {}).get("shared", False)
                    for s in disk_st_names
                ]
                all_shared = all(shared_flags)
                any_shared = any(shared_flags)

                log.debug(
                    "vmid=%s disk storages=%s all_shared=%s any_shared=%s",
                    vmid, disk_st_names, all_shared, any_shared,
                )

                if all_shared:
                    # Ceph / NFS / iSCSI — bare migrate, no disk parameters
                    use_with_local_disks = False
                    target_storage       = None
                else:
                    # At least some local disks
                    use_with_local_disks = with_local_disks
                    if not online:
                        # Offline migration with local disks: auto-detect targetstorage
                        img_storages = node_storages(px, target_node, content="images")
                        local_st     = [s for s in img_storages if not s.get("shared")]
                        chosen       = local_st or img_storages
                        if chosen:
                            target_storage = chosen[0]["storage"]
                            log.debug(
                                "auto-selected target storage '%s' on '%s'",
                                target_storage, target_node,
                            )
            else:
                # No disks found in config (unlikely) — try bare migrate
                use_with_local_disks = False

        except Exception as exc:
            log.debug("disk storage detection failed for vmid=%s: %s", vmid, exc)
            # Fall back to the caller's preference
            use_with_local_disks = with_local_disks

        # ── CD-ROM ISO ejection ───────────────────────────────────────────────
        # Proxmox aborts migration when the target storage can't hold 'iso'
        # content (e.g. local-lvm only supports 'images').  We eject all
        # mounted ISOs now and restore them in poll_migration after the task
        # completes (on the target on success, on the source on failure).
        try:
            cdrom_entries = _cdrom_iso_entries(config)
            if cdrom_entries:
                eject_params = {k: "none,media=cdrom" for k in cdrom_entries}
                _vm_update_config(px, node, vmid, kind, eject_params)
                cdrom_to_restore = cdrom_entries
                log.debug(
                    "Ejected %d ISO(s) before migration vmid=%s: %s",
                    len(cdrom_entries), vmid, list(cdrom_entries),
                )
        except Exception as exc:
            log.debug("CD-ROM eject failed for vmid=%s: %s", vmid, exc)
            cdrom_to_restore = {}

    elif kind == "lxc":
        # LXC: rootfs is always 'local', but live migration is not supported.
        # pass with_local_disks as-is; LXC migrate ignores it anyway.
        use_with_local_disks = with_local_disks
        try:
            config = _vm_config(px, node, vmid, kind)
        except Exception:
            config = {}

    # ── Total disk size for progress tracking ────────────────────────────────
    # Parsed from config (size=XG fields). Used in poll_migration to turn the
    # "N bytes copied" lines in the Proxmox task log into a real percentage.
    try:
        total_bytes = _total_disk_bytes(config, kind)
        log.debug("vmid=%s total_disk_bytes=%d", vmid, total_bytes)
    except Exception:
        total_bytes = 0

    # ── HA management ─────────────────────────────────────────────────────────
    # If the VM is managed by Proxmox HA, the normal migrate API is silently
    # delegated to `ha-manager migrate`, which fails with exit 255 when the HA
    # services are degraded or the cluster lacks quorum.
    # Fix: temporarily set HA state to "ignored" so the HA manager leaves the
    # VM alone during migration, then restore the original state after.
    ha_restore: dict | None = None
    try:
        ha_cfg = ha_resource_get(px, kind, vmid)
        if ha_cfg:
            original_state = ha_cfg.get("state", "started")
            ha_restore = {
                "cred_id": cred.id,
                "kind":    kind,
                "vmid":    vmid,
                "state":   original_state,
            }
            # "ignored" = HA stops managing the resource but config is preserved
            ha_resource_set_state(px, kind, vmid, "ignored")
            import time as _t; _t.sleep(2)  # give HA crm time to release
            log.debug("HA temporarily set to 'ignored' for %s:%s (was: %s)",
                      kind, vmid, original_state)
    except Exception as exc:
        log.debug("HA detection/disable failed for vmid=%s: %s", vmid, exc)
        ha_restore = None  # proceed without HA management

    upid = vm_migrate(px, node, vmid, target_node, kind=kind,
                      online=online, with_local_disks=use_with_local_disks,
                      target_storage=target_storage)
    row = MigrationTask(
        id=uuid.uuid4().hex,
        user_id=user_id,
        cred_id=cred.id,
        vmid=vmid,
        kind=kind,
        source_node=node,
        target_node=target_node,
        status="running",
        progress=1,
        upid=upid,
        message="migration started",
    )
    db: Session = SessionLocal()
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row, ha_restore, cdrom_to_restore, total_bytes
    finally:
        db.close()


def poll_migration(task_id: str, cred_id: int, max_seconds: int = 60 * 60,
                   ha_restore: "dict | None" = None,
                   cdrom_to_restore: "dict[str, str] | None" = None,
                   total_bytes: int = 0) -> None:
    """Run in a BackgroundTask thread: poll PVE until the task finishes."""
    db: Session = SessionLocal()
    try:
        task = db.query(MigrationTask).get(task_id)
        cred = db.query(ProxmoxCredential).get(cred_id)
        if not task or not cred:
            return
        px = build_client(cred)
        started = time.time()

        while time.time() - started < max_seconds:
            try:
                st = task_status(px, task.source_node, task.upid)
            except Exception as e:
                log.warning("task_status failed: %s", e)
                time.sleep(2)
                continue

            status = st.get("status", "running")
            exitstatus = st.get("exitstatus")

            # Parse progress from the log.
            # Two strategies are used in parallel:
            #   1. Percentage patterns ("XX %") — common in QEMU migration logs
            #   2. Byte-count lines ("N bytes … copied") — emitted by rsync
            #      during LXC offline migration.  We convert to % using the
            #      total_bytes pre-computed before migration started.
            try:
                lines = task_log(px, task.source_node, task.upid, start=0, limit=500)
                highest = task.progress
                for entry in lines:
                    text = entry.get("t") or entry.get("text") or ""
                    # Strategy 1: explicit percentage in log line
                    m_pct = PROGRESS_RE.search(text)
                    if m_pct:
                        highest = max(highest, int(m_pct.group(1)))
                    # Strategy 2: "N bytes (…) copied" (rsync / LXC)
                    if total_bytes > 0:
                        m_bytes = _BYTES_COPIED_RE.search(text)
                        if m_bytes:
                            pct = min(99, int(int(m_bytes.group(1)) * 100 / total_bytes))
                            highest = max(highest, pct)
                task.progress = min(highest, 99 if status == "running" else 100)
                if lines:
                    tail = lines[-1]
                    task.message = tail.get("t") or tail.get("text") or task.message
            except Exception as e:
                log.debug("task_log failed: %s", e)

            if status == "stopped":
                if exitstatus == "OK":
                    task.status = "success"
                    task.progress = 100
                    task.message = "migration completed"
                    # Restore HA state on the destination node after a
                    # successful migration (we disabled it before migrating).
                    if ha_restore:
                        try:
                            _px_ha = build_client(
                                db.query(ProxmoxCredential).get(ha_restore["cred_id"])
                            )
                            ha_resource_set_state(
                                _px_ha,
                                ha_restore["kind"],
                                ha_restore["vmid"],
                                ha_restore["state"],
                            )
                            log.debug("HA state restored to '%s' for %s:%s",
                                      ha_restore["state"], ha_restore["kind"],
                                      ha_restore["vmid"])
                        except Exception as exc:
                            log.warning("Failed to restore HA state: %s", exc)
                    # Restore any ejected CD-ROM ISOs on the TARGET node.
                    # The VM moved there, so that's where the config must change.
                    # If the ISO file doesn't exist on the target storage, the
                    # PUT will fail — we catch it and leave the drive ejected
                    # (the user can remount the ISO from the Proxmox UI).
                    if cdrom_to_restore:
                        try:
                            _vm_update_config(
                                px, task.target_node, task.vmid,
                                task.kind, cdrom_to_restore,
                            )
                            log.debug(
                                "Restored %d ISO(s) on target node '%s' after migration vmid=%s",
                                len(cdrom_to_restore), task.target_node, task.vmid,
                            )
                        except Exception as exc:
                            log.warning(
                                "Could not restore CD-ROM ISOs on target '%s' (ISO may not "
                                "exist there) — drive left ejected: %s",
                                task.target_node, exc,
                            )
                else:
                    # Try to surface the real reason from the task log instead
                    # of the generic "migration aborted" exit code.
                    real_error: str | None = None
                    try:
                        all_lines = task_log(px, task.source_node, task.upid,
                                             start=0, limit=500)
                        real_error = _extract_error_from_log(all_lines)
                    except Exception:
                        pass
                    task.status  = "failed"
                    task.message = real_error or f"exit: {exitstatus}"
                    # Restore HA even on failure so the VM is managed again
                    if ha_restore:
                        try:
                            _px_ha = build_client(
                                db.query(ProxmoxCredential).get(ha_restore["cred_id"])
                            )
                            ha_resource_set_state(
                                _px_ha,
                                ha_restore["kind"],
                                ha_restore["vmid"],
                                ha_restore["state"],
                            )
                        except Exception as exc:
                            log.warning("Failed to restore HA state after failure: %s", exc)
                    # Restore ejected CD-ROM ISOs on the SOURCE node.
                    # Migration failed so the VM is still where it started.
                    if cdrom_to_restore:
                        try:
                            _vm_update_config(
                                px, task.source_node, task.vmid,
                                task.kind, cdrom_to_restore,
                            )
                            log.debug(
                                "Restored %d ISO(s) on source node '%s' after failed migration vmid=%s",
                                len(cdrom_to_restore), task.source_node, task.vmid,
                            )
                        except Exception as exc:
                            log.warning(
                                "Could not restore CD-ROM ISOs on source '%s' after failure: %s",
                                task.source_node, exc,
                            )
                db.commit()
                return

            db.commit()
            time.sleep(2)

        task.status = "timeout"
        task.message = "polling timed out"
        db.commit()
    finally:
        db.close()
