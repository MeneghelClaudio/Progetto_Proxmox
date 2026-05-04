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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_method(cred: ProxmoxCredential) -> str:
    has_token = bool(cred.token_name and cred.encrypted_token_value)
    has_pass  = bool(cred.encrypted_password)
    if has_token and has_pass:
        return "both"
    if has_token:
        return "token"
    return "password"


def _cred_to_out(cred: ProxmoxCredential) -> CredentialOut:
    """Serializza ProxmoxCredential → CredentialOut (mai espone segreti)."""
    return CredentialOut(
        id           = cred.id,
        name         = cred.name,
        host         = cred.host,
        port         = cred.port,
        pve_username = cred.pve_username,
        pve_realm    = cred.pve_realm,
        verify_ssl   = cred.verify_ssl,
        created_at   = cred.created_at,
        auth_method  = _auth_method(cred),
        token_name   = cred.token_name,
        has_password = bool(cred.encrypted_password),
    )


def _test_proxmox_connection(
    host: str, port: int, pve_username: str, pve_realm: str,
    verify_ssl: bool,
    password: str | None = None,
    token_name: str | None = None,
    token_value: str | None = None,
) -> None:
    """
    Prova la connessione a Proxmox con le credenziali fornite.
    Usa token se disponibile, altrimenti password.
    """
    if not verify_ssl:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    user = f"{pve_username}@{pve_realm}"
    h    = f"{host}:{port}"

    try:
        if token_name and token_value:
            px = ProxmoxAPI(
                host=h, user=user,
                token_name=token_name, token_value=token_value,
                verify_ssl=verify_ssl, timeout=8,
            )
        elif password:
            px = ProxmoxAPI(
                host=h, user=user,
                password=password,
                verify_ssl=verify_ssl, timeout=8,
            )
        else:
            raise HTTPException(400, "Fornire almeno un metodo di autenticazione.")
        px.version.get()
    except HTTPException:
        raise
    except Exception as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("401", "unauthorized", "authentication", "permission", "forbidden")):
            raise HTTPException(401, "Credenziali non valide: utente, password o token errati.")
        raise HTTPException(400, f"Impossibile raggiungere il server Proxmox: {exc}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[CredentialOut])
def list_credentials(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    creds = db.query(ProxmoxCredential).filter(ProxmoxCredential.user_id == user.id).all()
    return [_cred_to_out(c) for c in creds]


@router.post("", response_model=CredentialOut, status_code=201)
def create_credential(
    payload: CredentialIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("admin", "senior"):
        raise HTTPException(403, "Admin o senior richiesto per aggiungere server.")

    has_token = bool(payload.token_name and payload.token_value)
    has_pass  = bool(payload.password)
    if not has_token and not has_pass:
        raise HTTPException(
            400,
            "Fornire almeno un metodo di autenticazione: "
            "password oppure token_name + token_value."
        )

    # Verifica connessione prima di salvare (usa token se disponibile)
    _test_proxmox_connection(
        host=payload.host, port=payload.port,
        pve_username=payload.pve_username, pve_realm=payload.pve_realm,
        verify_ssl=payload.verify_ssl,
        password=payload.password,
        token_name=payload.token_name,
        token_value=payload.token_value,
    )

    cred = ProxmoxCredential(
        user_id               = user.id,
        name                  = payload.name,
        host                  = payload.host,
        port                  = payload.port,
        pve_username          = payload.pve_username,
        pve_realm             = payload.pve_realm,
        encrypted_password    = encrypt_password(payload.password) if payload.password else None,
        token_name            = payload.token_name or None,
        encrypted_token_value = encrypt_password(payload.token_value) if payload.token_value else None,
        verify_ssl            = payload.verify_ssl,
    )
    db.add(cred)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(400, "Una credenziale con questo nome esiste già.")
    db.refresh(cred)
    return _cred_to_out(cred)


@router.patch("/{cred_id}", response_model=CredentialOut)
def update_credential(
    cred_id: int,
    payload: CredentialUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("admin", "senior"):
        raise HTTPException(403, "Admin o senior richiesto per modificare server.")
    cred = db.query(ProxmoxCredential).filter(
        ProxmoxCredential.id == cred_id,
        ProxmoxCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(404, "Not found")

    if payload.name         is not None: cred.name         = payload.name
    if payload.host         is not None: cred.host         = payload.host
    if payload.port         is not None: cred.port         = payload.port
    if payload.pve_username is not None: cred.pve_username = payload.pve_username
    if payload.pve_realm    is not None: cred.pve_realm    = payload.pve_realm
    if payload.verify_ssl   is not None: cred.verify_ssl   = payload.verify_ssl
    if payload.password:
        cred.encrypted_password = encrypt_password(payload.password)
    if payload.token_name is not None:
        cred.token_name = payload.token_name or None
    if payload.token_value:
        cred.encrypted_token_value = encrypt_password(payload.token_value)

    # Garanzia: almeno un metodo di auth rimane valido dopo la modifica
    has_token = bool(cred.token_name and cred.encrypted_token_value)
    has_pass  = bool(cred.encrypted_password)
    if not has_token and not has_pass:
        raise HTTPException(400, "Almeno un metodo di autenticazione deve rimanere configurato.")

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(400, "Aggiornamento fallito (nome duplicato?).")
    db.refresh(cred)
    return _cred_to_out(cred)


@router.delete("/{cred_id}", status_code=204)
def delete_credential(
    cred_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(403, "Solo admin può rimuovere server.")
    cred = db.query(ProxmoxCredential).filter(
        ProxmoxCredential.id == cred_id,
        ProxmoxCredential.user_id == user.id,
    ).first()
    if not cred:
        raise HTTPException(404, "Not found")
    db.delete(cred)
    db.commit()
