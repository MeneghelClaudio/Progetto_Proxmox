from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, EmailStr


Role = Literal["admin", "senior", "junior"]


# ---------- Auth ----------

class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    full_name: str
    email: str
    role: Role
    is_admin: bool


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6)
    full_name: str = ""
    email: str = ""
    role: Role = "junior"


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=6)
    role: Optional[Role] = None
    is_active: Optional[bool] = None


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    email: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Proxmox credentials ----------

class CredentialIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host: str
    port: int = 8006
    pve_username: str
    pve_realm: str = "pam"
    password: str           # plaintext on the wire (HTTPS) - encrypted at rest
    verify_ssl: bool = False


class CredentialOut(BaseModel):
    id: int
    name: str
    host: str
    port: int
    pve_username: str
    pve_realm: str
    verify_ssl: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Actions ----------

class CloneIn(BaseModel):
    newid: int
    target_node: Optional[str] = None
    name: Optional[str] = None
    full: bool = True


class MigrateIn(BaseModel):
    target_node: str
    online: bool = True
    with_local_disks: bool = True


class DeleteConfirmIn(BaseModel):
    confirm_name: str       # must match current VM/CT name


class SnapshotCreateIn(BaseModel):
    snapname: str
    description: Optional[str] = ""
    vmstate: bool = False


class BackupIn(BaseModel):
    storage: str
    mode: str = "snapshot"  # snapshot | suspend | stop
    compress: str = "zstd"
    notes: Optional[str] = None


# ---------- Tasks ----------

class MigrationTaskOut(BaseModel):
    id: str
    vmid: int
    kind: str
    source_node: str
    target_node: str
    status: str
    progress: int
    message: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Creation forms ----------

class CreateVMIn(BaseModel):
    """Minimal but usable VM creation payload."""
    vmid: int = Field(ge=100, le=999999999)
    name: str = Field(min_length=1, max_length=64)
    cores: int = Field(1, ge=1, le=512)
    sockets: int = Field(1, ge=1, le=8)
    memory: int = Field(2048, ge=16)              # MiB
    ostype: str = "l26"                           # l26, win11, win10, other...
    # Disk
    disk_storage: str
    disk_size: int = Field(32, ge=1)              # GiB
    disk_format: str = "qcow2"                    # qcow2, raw, vmdk
    # Net
    net_bridge: str = "vmbr0"
    net_model: str = "virtio"
    net_vlan: Optional[int] = None
    # ISO (optional)
    iso_volid: Optional[str] = None               # e.g. "local:iso/debian.iso"
    # Options
    scsihw: str = "virtio-scsi-single"
    bios: str = "seabios"                         # seabios | ovmf
    machine: Optional[str] = None                 # "q35" or None
    start_after_create: bool = False
    agent: bool = True


class CreateCTIn(BaseModel):
    """Minimal LXC container creation payload."""
    vmid: int = Field(ge=100, le=999999999)
    hostname: str = Field(min_length=1, max_length=63)
    ostemplate: str                                # e.g. "local:vztmpl/ubuntu-24.04-...tar.zst"
    cores: int = Field(1, ge=1, le=512)
    memory: int = Field(512, ge=16)                # MiB
    swap: int = Field(512, ge=0)                   # MiB
    # rootfs
    storage: str                                    # where rootfs lives
    disk_size: int = Field(8, ge=1)                # GiB
    unprivileged: bool = True
    # Network
    net_name: str = "eth0"
    net_bridge: str = "vmbr0"
    net_ip: str = "dhcp"                           # 'dhcp' or CIDR like 10.0.0.5/24
    net_gw: Optional[str] = None
    # Auth
    password: Optional[str] = None                 # if None, must provide ssh_keys
    ssh_public_keys: Optional[str] = None
    # Options
    start_after_create: bool = False
    onboot: bool = False
    features: Optional[str] = None                 # e.g. "nesting=1"
