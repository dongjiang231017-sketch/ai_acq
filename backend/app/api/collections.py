from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.collection import LeadCollectionRun, LeadCollectionTask, RawLeadRecord
from app.models.user import User
from app.schemas.collection import (
    LeadCollectionRunRead,
    LeadCollectionTaskCreate,
    LeadCollectionTaskRead,
    RawLeadRecordRead,
)
from app.schemas.common import Page, paginate
from app.services.collection import CollectionError, enqueue_collection_task, normalize_collection_mode

router = APIRouter()


@router.get("/tasks", response_model=list[LeadCollectionTaskRead])
def list_collection_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[LeadCollectionTask]:
    return list(
        db.scalars(
            select(LeadCollectionTask)
            .where(LeadCollectionTask.owner_user_id == current_user.id)
            .order_by(LeadCollectionTask.created_at.desc()),
        ).all(),
    )


@router.post("/tasks", response_model=LeadCollectionTaskRead, status_code=status.HTTP_201_CREATED)
def create_collection_task(
    payload: LeadCollectionTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadCollectionTask:
    task = LeadCollectionTask(
        name=payload.name,
        provider=payload.provider,
        collection_mode=normalize_collection_mode(payload.provider, payload.collection_mode),
        cities=payload.cities,
        categories=payload.categories,
        keywords=payload.keywords,
        target_per_keyword=payload.target_per_keyword,
        remark=payload.remark,
        owner_user_id=current_user.id,
        created_by_user_id=current_user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.post("/tasks/{task_id}/run", response_model=LeadCollectionRunRead, status_code=status.HTTP_202_ACCEPTED)
def run_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadCollectionRun:
    task = db.scalar(
        select(LeadCollectionTask).where(
            LeadCollectionTask.id == task_id,
            LeadCollectionTask.owner_user_id == current_user.id,
        ),
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="采集任务不存在")
    try:
        return enqueue_collection_task(db, task)
    except CollectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/runs", response_model=Page[LeadCollectionRunRead])
def list_collection_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=1000, ge=1, le=1000, alias="pageSize"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[LeadCollectionRunRead]:
    statement = (
        select(LeadCollectionRun)
        .join(LeadCollectionTask)
        .where(LeadCollectionTask.owner_user_id == current_user.id)
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    offset, page = paginate(total, page, page_size)
    items = db.scalars(statement.order_by(LeadCollectionRun.started_at.desc()).offset(offset).limit(page_size)).all()
    return Page(
        items=[LeadCollectionRunRead.model_validate(i, from_attributes=True) for i in items],
        total=total,
        page=page,
        pageSize=page_size,
    )


@router.get("/raw-records", response_model=Page[RawLeadRecordRead])
def list_raw_records(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=1000, ge=1, le=1000, alias="pageSize"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[RawLeadRecordRead]:
    statement = select(RawLeadRecord).where(RawLeadRecord.owner_user_id == current_user.id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    offset, page = paginate(total, page, page_size)
    items = db.scalars(statement.order_by(RawLeadRecord.created_at.desc()).offset(offset).limit(page_size)).all()
    return Page(
        items=[RawLeadRecordRead.model_validate(i, from_attributes=True) for i in items],
        total=total,
        page=page,
        pageSize=page_size,
    )
