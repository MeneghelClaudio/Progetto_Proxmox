from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, DateTime, Boolean,
    ForeignKey, LargeBinary, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    full_name = Column(String(128), default="", nullable=False)
    email = Column(String(128), default="", nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), default="junior", nullable=False)  # admin | senior | junior
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)

    credentials = relationship("ProxmoxCredential", back_populates="user",
                               cascade="all, delete-orphan")

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class ProxmoxCredential(Base):
    __tablename__ = "proxmox_credentials"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uniq_user_name"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=8006, nullable=False)
    pve_username = Column(String(128), nullable=False)
    pve_realm = Column(String(32), default="pam", nullable=False)
    encrypted_password = Column(LargeBinary, nullable=False)
    verify_ssl = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="credentials")


class MigrationTask(Base):
    __tablename__ = "migration_tasks"

    id = Column(String(64), primary_key=True)  # uuid
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cred_id = Column(Integer, ForeignKey("proxmox_credentials.id", ondelete="CASCADE"), nullable=False)
    vmid = Column(Integer, nullable=False)
    kind = Column(String(16), nullable=False)           # qemu | lxc
    source_node = Column(String(128), nullable=False)
    target_node = Column(String(128), nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    upid = Column(String(255), nullable=True)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
