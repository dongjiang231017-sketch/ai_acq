from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.task import OutreachTask
from app.schemas.task import TaskCreate, TaskRead

router = APIRouter()


@router.get("", response_model=list[TaskRead])
def list_tasks(db: Session = Depends(get_db)) -> list[OutreachTask]:
    return list(db.scalars(select(OutreachTask).order_by(OutreachTask.created_at.desc())).all())


@router.post("", response_model=TaskRead)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> OutreachTask:
    task = OutreachTask(
        name=payload.name,
        channel=payload.channel,
        target_count=payload.target_count,
        scheduled_at=payload.scheduled_at,
        status="待启动",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task
