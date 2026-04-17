"""
Symmetric encryption for Proxmox credentials + bcrypt for login passwords.

Proxmox passwords are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using
a key held only on the backend container volume. User login passwords are
bcrypt-hashed and never stored in clear or reversibly.
"""

from cryptography.fernet import Fernet

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
# NOTE: we use the `bcrypt` library directly instead of passlib because
# passlib 1.7.x is incompatible with bcrypt >= 4.1 (AttributeError on
# `bcrypt.__about__`). This keeps the dependency surface small and robust.

import bcrypt as _bcrypt


def hash_password(password: str) -> str:
    # bcrypt has a 72-byte input limit; truncate defensively.
    raw = password.encode("utf-8")[:72]
    return _bcrypt.hashpw(raw, _bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False