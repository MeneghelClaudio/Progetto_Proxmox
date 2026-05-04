from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import urllib3

from proxmoxer import ProxmoxAPI

from ..database import get_db
from ..auth import get_current_user
from ..models import User, ProxmoxCredential
from ..schemas import CredentialIn, CredentialOut, CredentialUpdate
from ..crypto import encrypt_password


router = APIRouter(prefix="/api/credentials", tags=["credentials"])


def _test_proxmox_connection(payload: CredentialIn) -> None:
    """
    Tenta una connessione di prova al server Proxmox con le credenziali fornite.
    Lancia HTTPException se le credenziali sono errate o il server non è raggiungibile.
    """
    if not payload.verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        px = ProxmoxAPI(
            host=f"{payload.host}:{payload.port}",
            user=f"{payload.pve_username}@{payload.pve_realm}",
            password=payload.password,
            verify_ssl=payload.verify_ssl,
            timeout=8,
        )
        # Una semplice chiamata per forzare l'autenticazione
        px.version.get()
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("401", "unauthorized", "authentication", "permission")):
            raise HTTPException(401, "Credenziali non valide: utente o password errati")
        # Errori di rete / host non raggiungibile
        raise HTTPException(400, f"Impossibile raggiungere il server Proxmox: {exc}")


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

    # Verifica le credenziali prima di salvarle
    _test_proxmox_connection(payload)

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


@router.patch("/{cred_id}", response_model=CredentialOut)
def update_credential(
    cred_id: int,
    payload: CredentialUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("admin", "senior"):
        raise HTTPException(403, "Admin or senior required to edit servers")
    cred = db.query(ProxmoxCredential).filter(
        ProxmoxCredential.id == cred_id,
        ProxmoxCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(404, "Not found")

    if payload.name is not None:        cred.name = payload.name
    if payload.host is not None:        cred.host = payload.host
    if payload.port is not None:        cred.port = payload.port
    if payload.pve_username is not None:cred.pve_username = payload.pve_username
    if payload.pve_realm is not None:   cred.pve_realm = payload.pve_realm
    if payload.verify_ssl is not None:  cred.verify_ssl = payload.verify_ssl
    if payload.password:                cred.encrypted_password = encrypt_password(payload.password)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(400, "Update failed (duplicate name?)")
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
