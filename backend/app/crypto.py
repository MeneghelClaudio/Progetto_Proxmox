"""
Symmetric encryption for Proxmox credentials + bcrypt for login passwords.

Proxmox passwords are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using
a key held only on the backend container volume. User login passwords are
bcrypt-hashed and never stored in clear or reversibly.
"""

from cryptography.fernet import Fernet
from passlib.context import CryptContext

from .config import ensure_fernet_key


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(ensure_fernet_key())
    return _fernet


def encrypt_password(plain: str) -> bytes:
    return _get_fernet().encrypt(plain.encode("utf-8"))


def decrypt_password(token: bytes) -> str:
    return _get_fernet().decrypt(token).decode("utf-8")


# ---------- bcrypt for user login ----------

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_ctx.verify(password, hashed)
    except Exception:
        return False
