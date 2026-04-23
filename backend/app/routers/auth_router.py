from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import TokenOut, UserOut
from ..crypto import verify_password
from ..auth import create_access_token, get_current_user


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token(
        sub=user.username,
        extra={"role": user.role, "admin": user.role == "admin"},
    )
    return TokenOut(
        access_token=token,
        username=user.username,
        full_name=user.full_name or user.username,
        email=user.email or "",
        role=user.role,
        is_admin=(user.role == "admin"),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
