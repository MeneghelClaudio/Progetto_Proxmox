from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ---------- Auth ----------

class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: bool


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6)
    is_admin: bool = False


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool
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
