"""
Tasks endpoints for the bottom task bar.

The UI polls /api/tasks?active=true every few seconds to render progress.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..auth import get_current_user
from ..models import User, MigrationTask
from ..schemas import MigrationTaskOut


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=List[MigrationTaskOut])
def list_tasks(active: bool = False, limit: int = 50,
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(MigrationTask).filter(MigrationTask.user_id == user.id)
    if active:
        q = q.filter(MigrationTask.status.in_(["pending", "running"]))
    return q.order_by(MigrationTask.created_at.desc()).limit(limit).all()


@router.delete("/{task_id}", status_code=204)
def dismiss_task(task_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    row = db.query(MigrationTask).filter(
        MigrationTask.id == task_id, MigrationTask.user_id == user.id,
    ).first()
    if row and row.status not in ("pending", "running"):
        db.delete(row)
        db.commit()
