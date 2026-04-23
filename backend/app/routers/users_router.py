"""
User management (admin-only).

Admins can list, create, update (role, password, email, active/disabled) and
delete users. Non-admins get 403.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import UserCreate, UserUpdate, UserOut
from ..crypto import hash_password
from ..auth import require_admin, get_current_user


router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db),
               _admin: User = Depends(require_admin)):
    return db.query(User).order_by(User.id.asc()).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate,
                db: Session = Depends(get_db),
                _admin: User = Depends(require_admin)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(400, "Username already exists")

    user = User(
        username=payload.username,
        full_name=payload.full_name or payload.username,
        email=payload.email or "",
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate,
                db: Session = Depends(get_db),
                _admin: User = Depends(require_admin)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.email is not None:
        user.email = payload.email
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if payload.role is not None:
        # Prevent demoting the last admin
        if user.role == "admin" and payload.role != "admin":
            remaining_admins = db.query(User).filter(
                User.role == "admin", User.id != user.id
            ).count()
            if remaining_admins == 0:
                raise HTTPException(400, "Cannot demote the last admin")
        user.role = payload.role
    if payload.is_active is not None:
        if user.role == "admin" and not payload.is_active:
            remaining_admins = db.query(User).filter(
                User.role == "admin", User.is_active == True, User.id != user.id
            ).count()
            if remaining_admins == 0:
                raise HTTPException(400, "Cannot disable the last active admin")
        user.is_active = payload.is_active

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int,
                db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(400, "You cannot delete your own account")
    if user.role == "admin":
        remaining_admins = db.query(User).filter(
            User.role == "admin", User.id != user.id
        ).count()
        if remaining_admins == 0:
            raise HTTPException(400, "Cannot delete the last admin")
    db.delete(user)
    db.commit()
