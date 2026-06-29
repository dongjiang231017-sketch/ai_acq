from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.lead import MerchantLead
from app.models.task import (
    DirectMessage,
    DirectMessageAccount,
    DirectMessageConversation,
    DirectMessageTemplate,
    OutreachTask,
)
from app.schemas.dm import (
    DmAccountCreate,
    DmAccountRead,
    DmConfigRead,
    DmConversationRead,
    DmMessageRead,
    DmOverview,
    DmTaskCreate,
    DmTemplateCreate,
    DmTemplateRead,
)
from app.schemas.task import TaskRead
from app.services.dm_queue import enqueue_dm_task
from app.services.dm_runner import run_dm_task

router = APIRouter()


def _seed_default_account(db: Session) -> DirectMessageAccount:
    account = db.scalar(select(DirectMessageAccount).where(DirectMessageAccount.status == "可用").order_by(DirectMessageAccount.created_at.desc()))
    if account:
        return account

    account = DirectMessageAccount(
        platform="美团",
        account_name="南昌本地生活招商号",
        login_label="待绑定真实平台账号",
        status="可用",
        daily_limit=200,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _seed_default_template(db: Session) -> DirectMessageTemplate:
    template = db.scalar(
        select(DirectMessageTemplate).where(DirectMessageTemplate.is_active.is_(True)).order_by(DirectMessageTemplate.created_at.desc())
    )
    if template:
        return template

    template = DirectMessageTemplate(
        name="视频号团购邀约私信",
        platform="通用",
        content="您好，看到{商家名称}适合做视频号本地生活团购曝光，想了解下您是否考虑新增线上获客渠道？",
        is_active=True,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.get("/overview", response_model=DmOverview)
def dm_overview(db: Session = Depends(get_db)) -> dict[str, int]:
    _seed_default_account(db)
    _seed_default_template(db)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    accounts = db.scalar(select(func.count()).select_from(DirectMessageAccount)) or 0
    active_accounts = (
        db.scalar(select(func.count()).select_from(DirectMessageAccount).where(DirectMessageAccount.status == "可用")) or 0
    )
    today_sent = (
        db.scalar(
            select(func.count())
            .select_from(DirectMessage)
            .where(DirectMessage.direction == "outbound", DirectMessage.created_at >= today_start)
        )
        or 0
    )
    replies = (
        db.scalar(
            select(func.count())
            .select_from(DirectMessage)
            .where(DirectMessage.direction == "inbound", DirectMessage.created_at >= today_start)
        )
        or 0
    )
    needs_handoff = (
        db.scalar(select(func.count()).select_from(DirectMessageConversation).where(DirectMessageConversation.need_handoff.is_(True)))
        or 0
    )
    intent_count = (
        db.scalar(select(func.count()).select_from(DirectMessageConversation).where(DirectMessageConversation.intent_level.in_(["A", "B"])))
        or 0
    )
    return {
        "accounts": int(accounts),
        "activeAccounts": int(active_accounts),
        "todaySent": int(today_sent),
        "replies": int(replies),
        "needsHandoff": int(needs_handoff),
        "intentCount": int(intent_count),
    }


@router.get("/config", response_model=DmConfigRead)
def dm_config() -> dict[str, object]:
    return {
        "gatewayMode": settings.dm_gateway_mode,
        "queueEnabled": settings.dm_queue_enabled,
        "queueName": settings.dm_queue_name,
        "redisUrlConfigured": bool(settings.redis_url),
    }


@router.get("/accounts", response_model=list[DmAccountRead])
def list_dm_accounts(db: Session = Depends(get_db)) -> list[DirectMessageAccount]:
    _seed_default_account(db)
    return list(db.scalars(select(DirectMessageAccount).order_by(DirectMessageAccount.created_at.desc())).all())


@router.post("/accounts", response_model=DmAccountRead)
def create_dm_account(payload: DmAccountCreate, db: Session = Depends(get_db)) -> DirectMessageAccount:
    account = DirectMessageAccount(**payload.model_dump(by_alias=False))
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/templates", response_model=list[DmTemplateRead])
def list_dm_templates(db: Session = Depends(get_db)) -> list[DirectMessageTemplate]:
    _seed_default_template(db)
    return list(db.scalars(select(DirectMessageTemplate).order_by(DirectMessageTemplate.created_at.desc())).all())


@router.post("/templates", response_model=DmTemplateRead)
def create_dm_template(payload: DmTemplateCreate, db: Session = Depends(get_db)) -> DirectMessageTemplate:
    template = DirectMessageTemplate(**payload.model_dump(by_alias=False))
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.get("/tasks", response_model=list[TaskRead])
def list_dm_tasks(db: Session = Depends(get_db)) -> list[OutreachTask]:
    return list(db.scalars(select(OutreachTask).where(OutreachTask.channel == "dm").order_by(OutreachTask.created_at.desc())).all())


@router.post("/tasks", response_model=TaskRead)
def create_dm_task(payload: DmTaskCreate, db: Session = Depends(get_db)) -> OutreachTask:
    unique_lead_ids = list(dict.fromkeys(payload.lead_ids))
    leads = list(db.scalars(select(MerchantLead).where(MerchantLead.id.in_(unique_lead_ids))).all())
    if len(leads) != len(unique_lead_ids):
        raise HTTPException(status_code=400, detail="包含不存在的线索")

    account = db.get(DirectMessageAccount, payload.account_id) if payload.account_id else _seed_default_account(db)
    if not account:
        raise HTTPException(status_code=400, detail="平台账号不存在")

    template = db.get(DirectMessageTemplate, payload.template_id) if payload.template_id else _seed_default_template(db)
    if not template:
        raise HTTPException(status_code=400, detail="私信模板不存在")

    task = OutreachTask(
        name=payload.name,
        channel="dm",
        status="待启动",
        target_count=len(leads),
        concurrency=1,
        script_id=template.id,
        dm_account_id=account.id,
        dm_template_id=template.id,
        target_lead_ids=",".join(unique_lead_ids),
        scheduled_at=payload.scheduled_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.post("/tasks/{task_id}/start", response_model=TaskRead)
def start_dm_task(task_id: str, db: Session = Depends(get_db)) -> OutreachTask:
    task = db.get(OutreachTask, task_id)
    if not task or task.channel != "dm":
        raise HTTPException(status_code=404, detail="私信任务不存在")

    if settings.dm_queue_enabled:
        try:
            enqueue_dm_task(task.id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        task.status = "排队中"
        task.started_at = datetime.utcnow()
        task.finished_at = None
        db.commit()
        db.refresh(task)
        return task

    try:
        return run_dm_task(task.id, db)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/conversations", response_model=list[DmConversationRead])
def list_dm_conversations(db: Session = Depends(get_db)) -> list[DirectMessageConversation]:
    return list(db.scalars(select(DirectMessageConversation).order_by(DirectMessageConversation.created_at.desc())).all())


@router.get("/messages", response_model=list[DmMessageRead])
def list_dm_messages(
    conversation_id: str | None = Query(default=None, alias="conversationId"),
    db: Session = Depends(get_db),
) -> list[DirectMessage]:
    stmt = select(DirectMessage).order_by(DirectMessage.created_at.desc())
    if conversation_id:
        stmt = stmt.where(DirectMessage.conversation_id == conversation_id)
    return list(db.scalars(stmt).all())
