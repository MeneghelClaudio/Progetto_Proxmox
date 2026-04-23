from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..auth import get_current_user
from ..models import User, ProxmoxCredential
from ..schemas import CredentialIn, CredentialOut
from ..crypto import encrypt_password


router = APIRouter(prefix="/api/credentials", tags=["credentials"])


@router.get("", response_model=List[CredentialOut])
def list_credentials(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(ProxmoxCredential).filter(ProxmoxCredential.user_id == user.id).all()


@router.post("", response_model=CredentialOut, status_code=201)
def create_credential(
    payload: CredentialIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Only admin and senior can add Proxmox servers
    if user.role not in ("admin", "senior"):
        raise HTTPException(403, "Admin or senior required to add servers")

    cred = ProxmoxCredential(
        user_id=user.id,
        name=payload.name,
        host=payload.host,
        port=payload.port,
        pve_username=payload.pve_username,
        pve_realm=payload.pve_realm,
        encrypted_password=encrypt_password(payload.password),
        verify_ssl=payload.verify_ssl,
    )
    db.add(cred)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(400, "A credential with that name already exists")
    db.refresh(cred)
    return cred


@router.delete("/{cred_id}", status_code=204)
def delete_credential(cred_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    cred = db.query(ProxmoxCredential).filter(
        ProxmoxCredential.id == cred_id,
        ProxmoxCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(404, "Not found")
    db.delete(cred)
    db.commit()
