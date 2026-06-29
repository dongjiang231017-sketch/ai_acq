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
    DirectMessagePlatformConfig,
    DirectMessageTemplate,
    OutreachTask,
)
from app.schemas.dm import (
    DmAccountCreate,
    DmAccountLoginSession,
    DmAccountRead,
    DmAccountUpdate,
    DmConfigRead,
    DmConversationRead,
    DmMessageRead,
    DmOverview,
    DmPlatformConfigCreate,
    DmPlatformConfigRead,
    DmPlatformConfigUpdate,
    DmSyncResult,
    DmTaskCreate,
    DmTemplateCreate,
    DmTemplateRead,
)
from app.schemas.task import TaskRead
from app.services.dm_browser_profile import normalize_account_state
from app.services.dm_gateway import BrowserAutomationDmGateway
from app.services.dm_listener import sync_dm_replies as sync_dm_replies_service
from app.services.dm_queue import enqueue_dm_task
from app.services.dm_runner import run_dm_task

router = APIRouter()

PLATFORM_LOGIN_URLS = {
    "美团": "https://e.meituan.com/",
    "饿了么": "https://open.shop.ele.me/",
    "抖音": "https://business.douyin.com/",
    "视频号": "https://channels.weixin.qq.com/",
}


def _seed_default_account(db: Session) -> DirectMessageAccount:
    account = db.scalar(select(DirectMessageAccount).where(DirectMessageAccount.status == "可用").order_by(DirectMessageAccount.created_at.desc()))
    if account:
        return account

    account = DirectMessageAccount(
        platform="美团",
        account_name="南昌本地生活招商号",
        login_label="待绑定真实平台账号",
        status="可用",
        session_status="模拟可用",
        risk_status="正常",
        daily_limit=200,
        min_send_interval_seconds=0,
    )
    db.add(account)
    db.flush()
    normalize_account_state(account)
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


def _seed_default_platform_configs(db: Session) -> list[DirectMessagePlatformConfig]:
    configs = list(db.scalars(select(DirectMessagePlatformConfig).order_by(DirectMessagePlatformConfig.created_at.desc())).all())
    if configs:
        return configs

    defaults = [
        DirectMessagePlatformConfig(platform="美团", home_url="https://e.meituan.com/", inbox_url="", enabled=False),
        DirectMessagePlatformConfig(platform="饿了么", home_url="https://open.shop.ele.me/", inbox_url="", enabled=False),
        DirectMessagePlatformConfig(platform="抖音", home_url="https://business.douyin.com/", inbox_url="", enabled=False),
    ]
    db.add_all(defaults)
    db.commit()
    return defaults


def _platform_config(db: Session, platform: str) -> DirectMessagePlatformConfig | None:
    return db.scalar(
        select(DirectMessagePlatformConfig)
        .where(DirectMessagePlatformConfig.platform == platform)
        .order_by(DirectMessagePlatformConfig.created_at.desc())
    )


def _login_url_for_account(db: Session, account: DirectMessageAccount) -> str:
    config = _platform_config(db, account.platform)
    return (config.home_url if config and config.home_url else PLATFORM_LOGIN_URLS.get(account.platform, "")).strip()


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
        "browserProfileRoot": settings.dm_browser_profile_root,
        "browserHeadless": settings.dm_browser_headless,
        "browserChannel": settings.dm_browser_channel,
        "browserLiveSendEnabled": settings.dm_browser_live_send_enabled,
    }


@router.get("/accounts", response_model=list[DmAccountRead])
def list_dm_accounts(db: Session = Depends(get_db)) -> list[DirectMessageAccount]:
    _seed_default_account(db)
    accounts = list(db.scalars(select(DirectMessageAccount).order_by(DirectMessageAccount.created_at.desc())).all())
    for account in accounts:
        normalize_account_state(account)
    db.commit()
    return accounts


@router.post("/accounts", response_model=DmAccountRead)
def create_dm_account(payload: DmAccountCreate, db: Session = Depends(get_db)) -> DirectMessageAccount:
    account = DirectMessageAccount(**payload.model_dump(by_alias=False))
    db.add(account)
    db.flush()
    normalize_account_state(account)
    db.commit()
    db.refresh(account)
    return account


@router.patch("/accounts/{account_id}", response_model=DmAccountRead)
def update_dm_account(account_id: str, payload: DmAccountUpdate, db: Session = Depends(get_db)) -> DirectMessageAccount:
    account = db.get(DirectMessageAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="平台账号不存在")

    for key, value in payload.model_dump(by_alias=False, exclude_unset=True).items():
        setattr(account, key, value)
    normalize_account_state(account)
    db.commit()
    db.refresh(account)
    return account


@router.post("/accounts/{account_id}/login-session", response_model=DmAccountLoginSession)
def create_dm_account_login_session(account_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    account = db.get(DirectMessageAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="平台账号不存在")

    normalize_account_state(account)
    login_url = _login_url_for_account(db, account)
    if not login_url:
        raise HTTPException(status_code=400, detail="请先配置该平台的登录首页")

    account.last_login_check_at = datetime.utcnow()
    if account.session_status not in {"已登录", "模拟可用"}:
        account.status = "待登录"
        account.session_status = "未登录"
        account.last_error = "隔离登录会话已创建，请在客户端内置登录页完成登录后点击检测"
    db.commit()
    db.refresh(account)
    return {
        "accountId": account.id,
        "platform": account.platform,
        "accountName": account.account_name,
        "loginUrl": login_url,
        "profileKey": account.browser_profile_key or "",
        "profilePath": account.browser_profile_path or "",
        "sessionStatus": account.session_status,
        "riskStatus": account.risk_status,
        "embeddedMode": "desktop-isolated-webview",
        "isolated": True,
    }


@router.post("/accounts/{account_id}/preflight", response_model=DmAccountRead)
def preflight_dm_account(account_id: str, db: Session = Depends(get_db)) -> DirectMessageAccount:
    account = db.get(DirectMessageAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="平台账号不存在")

    normalize_account_state(account)
    account.last_login_check_at = datetime.utcnow()
    if settings.dm_gateway_mode == "simulator":
        account.status = "可用"
        account.session_status = "模拟可用"
        account.risk_status = "正常"
        account.last_error = None
    elif settings.dm_gateway_mode == "browser":
        config = _platform_config(db, account.platform)
        result = BrowserAutomationDmGateway().preflight_account(account, config)
        account.status = result.account_status
        account.session_status = result.session_status
        account.risk_status = result.risk_status
        account.last_error = result.last_error
    elif account.session_status != "已登录":
        account.status = "待登录"
        account.last_error = "请先在客户端完成该平台账号扫码登录"

    db.commit()
    db.refresh(account)
    return account


@router.get("/platform-configs", response_model=list[DmPlatformConfigRead])
def list_dm_platform_configs(db: Session = Depends(get_db)) -> list[DirectMessagePlatformConfig]:
    return _seed_default_platform_configs(db)


@router.post("/platform-configs", response_model=DmPlatformConfigRead)
def create_dm_platform_config(payload: DmPlatformConfigCreate, db: Session = Depends(get_db)) -> DirectMessagePlatformConfig:
    config = DirectMessagePlatformConfig(**payload.model_dump(by_alias=False))
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.patch("/platform-configs/{config_id}", response_model=DmPlatformConfigRead)
def update_dm_platform_config(
    config_id: str,
    payload: DmPlatformConfigUpdate,
    db: Session = Depends(get_db),
) -> DirectMessagePlatformConfig:
    config = db.get(DirectMessagePlatformConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="平台选择器配置不存在")

    for key, value in payload.model_dump(by_alias=False, exclude_unset=True).items():
        setattr(config, key, value)
    db.commit()
    db.refresh(config)
    return config


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

    account_id = None
    if payload.account_id:
        account = db.get(DirectMessageAccount, payload.account_id)
        if not account:
            raise HTTPException(status_code=400, detail="平台账号不存在")
        account_id = account.id
    else:
        _seed_default_account(db)

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
        dm_account_id=account_id,
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


@router.post("/sync-replies", response_model=DmSyncResult)
def sync_dm_replies(db: Session = Depends(get_db)) -> dict[str, int]:
    try:
        result = sync_dm_replies_service(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"checked": result.checked, "newReplies": result.new_replies, "needsHandoff": result.needs_handoff}


@router.get("/messages", response_model=list[DmMessageRead])
def list_dm_messages(
    conversation_id: str | None = Query(default=None, alias="conversationId"),
    db: Session = Depends(get_db),
) -> list[DirectMessage]:
    stmt = select(DirectMessage).order_by(DirectMessage.created_at.desc())
    if conversation_id:
        stmt = stmt.where(DirectMessage.conversation_id == conversation_id)
    return list(db.scalars(stmt).all())
