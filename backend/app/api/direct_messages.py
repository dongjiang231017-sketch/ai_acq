import platform
import shutil
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

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
    DmAccountInlineLogin,
    DmAccountLoginSession,
    DmAccountLoginWindow,
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
from app.services.dm_browser_profile import normalize_account_state, profile_has_session_artifacts
from app.services.dm_gateway import BrowserAutomationDmGateway
from app.services.dm_listener import sync_dm_replies as sync_dm_replies_service
from app.services.dm_policy import SUPPORTED_DM_PLATFORM_ORDER, SUPPORTED_DM_PLATFORMS, UNSUPPORTED_DM_PLATFORM_REASONS
from app.services.dm_queue import enqueue_dm_task
from app.services.dm_runner import run_dm_task

router = APIRouter()

PLATFORM_LOGIN_URLS = {
    "美团": "https://passport.meituan.com/account/unitivelogin",
    "饿了么": "https://h5.ele.me/login/",
    "抖音": "https://www.douyin.com/",
}

DEFAULT_DM_ACCOUNTS = [
    {"platform": "美团", "account_name": "美团个人号-南昌本地生活", "daily_limit": 200, "min_send_interval_seconds": 45},
    {"platform": "饿了么", "account_name": "饿了么个人号-餐饮招商", "daily_limit": 150, "min_send_interval_seconds": 45},
    {"platform": "抖音", "account_name": "抖音个人号-团购拓客", "daily_limit": 120, "min_send_interval_seconds": 60},
]

LEGACY_BUSINESS_BACKEND_URLS = {
    "美团": {"https://e.meituan.com", "https://e.meituan.com/"},
    "饿了么": {"https://open.shop.ele.me", "https://open.shop.ele.me/"},
    "抖音": {"https://business.douyin.com", "https://business.douyin.com/"},
}


def _is_legacy_business_backend_url(platform: str, url: str | None) -> bool:
    if not url:
        return False
    return url.strip().rstrip("/") in {item.rstrip("/") for item in LEGACY_BUSINESS_BACKEND_URLS.get(platform, set())}


def _unsupported_platform_reason(platform_name: str) -> str:
    return UNSUPPORTED_DM_PLATFORM_REASONS.get(platform_name, f"{platform_name}暂不支持平台私信")


def _apply_dm_account_support_status(account: DirectMessageAccount) -> bool:
    if account.platform in SUPPORTED_DM_PLATFORMS:
        return False

    updates = {
        "status": "不支持私信",
        "session_status": "不可用",
        "risk_status": "不支持",
        "last_error": _unsupported_platform_reason(account.platform),
    }
    for key, value in updates.items():
        if getattr(account, key) != value:
            setattr(account, key, value)
    return True


def _seed_default_accounts(db: Session) -> list[DirectMessageAccount]:
    accounts = list(db.scalars(select(DirectMessageAccount).order_by(DirectMessageAccount.created_at.desc())).all())
    existing_platforms = {account.platform for account in accounts}
    default_account_names = {str(account["platform"]): str(account["account_name"]) for account in DEFAULT_DM_ACCOUNTS}
    legacy_business_name_tokens = ("招商号", "商家号", "经营宝")
    changed = False
    for account in accounts:
        if _apply_dm_account_support_status(account):
            changed = True
            continue
        if account.login_label in {"待绑定真实平台账号", "待绑定商家号", ""} or not account.login_label:
            account.login_label = "待绑定个人号"
            changed = True
        default_account_name = default_account_names.get(account.platform)
        if default_account_name and any(token in account.account_name for token in legacy_business_name_tokens):
            account.account_name = default_account_name
            changed = True

    for account_config in DEFAULT_DM_ACCOUNTS:
        if account_config["platform"] in existing_platforms:
            continue
        account = DirectMessageAccount(
            platform=str(account_config["platform"]),
            account_name=str(account_config["account_name"]),
            login_label="待绑定个人号",
            status="可用",
            session_status="模拟可用",
            risk_status="正常",
            daily_limit=int(account_config["daily_limit"]),
            min_send_interval_seconds=int(account_config["min_send_interval_seconds"]),
        )
        db.add(account)
        db.flush()
        normalize_account_state(account)
        accounts.append(account)
        changed = True

    if changed:
        db.commit()
        for account in accounts:
            db.refresh(account)
    return accounts


def _seed_default_account(db: Session) -> DirectMessageAccount:
    accounts = _seed_default_accounts(db)
    available_account = next(
        (account for account in accounts if account.platform in SUPPORTED_DM_PLATFORMS and account.status == "可用"),
        None,
    )
    if available_account:
        return available_account
    supported_account = next((account for account in accounts if account.platform in SUPPORTED_DM_PLATFORMS), None)
    if supported_account:
        return supported_account
    raise HTTPException(status_code=400, detail="暂无支持平台的私信个人号")


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
    existing_platforms = {config.platform for config in configs}
    changed = False
    for config in configs:
        if config.platform not in SUPPORTED_DM_PLATFORMS and config.enabled:
            config.enabled = False
            changed = True

    for platform_name in SUPPORTED_DM_PLATFORM_ORDER:
        if platform_name in existing_platforms:
            continue
        config = DirectMessagePlatformConfig(platform=platform_name, home_url="", inbox_url="", enabled=False)
        db.add(config)
        configs.append(config)
        changed = True

    if changed:
        db.commit()
    return configs


def _platform_config(db: Session, platform: str) -> DirectMessagePlatformConfig | None:
    return db.scalar(
        select(DirectMessagePlatformConfig)
        .where(DirectMessagePlatformConfig.platform == platform)
        .order_by(DirectMessagePlatformConfig.created_at.desc())
    )


def _login_url_for_account(db: Session, account: DirectMessageAccount) -> str:
    if account.platform not in SUPPORTED_DM_PLATFORMS:
        return ""
    config = _platform_config(db, account.platform)
    configured_url = (config.home_url if config and config.home_url else "").strip()
    if configured_url and not _is_legacy_business_backend_url(account.platform, configured_url):
        return configured_url
    return PLATFORM_LOGIN_URLS.get(account.platform, "").strip()


def _login_session_payload(account: DirectMessageAccount, login_url: str) -> dict[str, object]:
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


def _chrome_executable() -> str | None:
    system = platform.system()
    candidates: list[str] = []
    if system == "Darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            ]
        )
    elif system == "Windows":
        local_app_data = Path.home() / "AppData/Local"
        program_files = Path("C:/Program Files")
        program_files_x86 = Path("C:/Program Files (x86)")
        candidates.extend(
            [
                str(program_files / "Google/Chrome/Application/chrome.exe"),
                str(program_files_x86 / "Google/Chrome/Application/chrome.exe"),
                str(local_app_data / "Google/Chrome/Application/chrome.exe"),
                str(program_files / "Microsoft/Edge/Application/msedge.exe"),
                str(program_files_x86 / "Microsoft/Edge/Application/msedge.exe"),
            ]
        )
    else:
        candidates.extend(["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"])

    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _launch_isolated_login_window(login_url: str, profile_path: str) -> tuple[bool, str]:
    active_profile_path = Path(profile_path or ".dm_browser_profiles/dm-account").expanduser()
    if not active_profile_path.is_absolute():
        active_profile_path = (Path.cwd() / active_profile_path).resolve()
    active_profile_path.mkdir(parents=True, exist_ok=True)

    executable = _chrome_executable()
    if not executable:
        webbrowser.open(login_url)
        return False, "未找到 Chrome/Edge，已用系统默认浏览器打开；默认浏览器可能无法保证账号隔离"

    subprocess.Popen(
        [
            executable,
            f"--user-data-dir={active_profile_path}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            login_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True, "已打开独立登录窗口，请在弹出的页面完成个人号登录，然后回到客户端点击“登录后检测”。"


def _prepare_login_session(db: Session, account: DirectMessageAccount) -> tuple[DirectMessageAccount, str]:
    normalize_account_state(account)
    if account.platform not in SUPPORTED_DM_PLATFORMS:
        account.status = "不支持私信"
        account.session_status = "不可用"
        account.risk_status = "不支持"
        account.last_error = _unsupported_platform_reason(account.platform)
        db.commit()
        raise HTTPException(status_code=400, detail=account.last_error)

    login_url = _login_url_for_account(db, account)
    if not login_url:
        raise HTTPException(status_code=400, detail=f"暂不支持{account.platform}内置登录入口，请在高级配置里填写网页登录入口")

    account.last_login_check_at = datetime.utcnow()
    if account.session_status not in {"已登录", "模拟可用"}:
        account.status = "待登录"
        account.session_status = "未登录"
        account.last_error = "隔离登录会话已创建，请在客户端内置个人号登录页完成登录后点击检测"
    db.commit()
    db.refresh(account)
    return account, login_url


@router.get("/overview", response_model=DmOverview)
def dm_overview(db: Session = Depends(get_db)) -> dict[str, int]:
    _seed_default_account(db)
    _seed_default_template(db)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    accounts = (
        db.scalar(
            select(func.count())
            .select_from(DirectMessageAccount)
            .where(DirectMessageAccount.platform.in_(SUPPORTED_DM_PLATFORM_ORDER))
        )
        or 0
    )
    active_accounts = (
        db.scalar(
            select(func.count())
            .select_from(DirectMessageAccount)
            .where(
                DirectMessageAccount.platform.in_(SUPPORTED_DM_PLATFORM_ORDER),
                DirectMessageAccount.status == "可用",
            )
        )
        or 0
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
    _seed_default_accounts(db)
    accounts = list(db.scalars(select(DirectMessageAccount).order_by(DirectMessageAccount.created_at.desc())).all())
    for account in accounts:
        normalize_account_state(account)
    db.commit()
    return accounts


@router.post("/accounts", response_model=DmAccountRead)
def create_dm_account(payload: DmAccountCreate, db: Session = Depends(get_db)) -> DirectMessageAccount:
    if payload.platform not in SUPPORTED_DM_PLATFORMS:
        raise HTTPException(status_code=400, detail=_unsupported_platform_reason(payload.platform))

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
        raise HTTPException(status_code=404, detail="平台个人号不存在")

    for key, value in payload.model_dump(by_alias=False, exclude_unset=True).items():
        setattr(account, key, value)
    normalize_account_state(account)
    _apply_dm_account_support_status(account)
    db.commit()
    db.refresh(account)
    return account


@router.post("/accounts/{account_id}/login-session", response_model=DmAccountLoginSession)
def create_dm_account_login_session(account_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    account = db.get(DirectMessageAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="平台个人号不存在")

    account, login_url = _prepare_login_session(db, account)
    return _login_session_payload(account, login_url)


@router.post("/accounts/{account_id}/login-window", response_model=DmAccountLoginWindow)
def open_dm_account_login_window(account_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    account = db.get(DirectMessageAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="平台个人号不存在")

    account, login_url = _prepare_login_session(db, account)
    launched, launch_message = _launch_isolated_login_window(login_url, account.browser_profile_path or "")
    return {
        **_login_session_payload(account, login_url),
        "launched": launched,
        "launchMessage": launch_message,
    }


@router.post("/accounts/{account_id}/inline-login", response_model=DmAccountRead)
def complete_dm_account_inline_login(
    account_id: str,
    payload: DmAccountInlineLogin,
    db: Session = Depends(get_db),
) -> DirectMessageAccount:
    account = db.get(DirectMessageAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="平台个人号不存在")
    if not payload.agreement_accepted:
        raise HTTPException(status_code=400, detail="请先勾选同意协议")

    normalize_account_state(account)
    if _apply_dm_account_support_status(account):
        db.commit()
        db.refresh(account)
        raise HTTPException(status_code=400, detail=_unsupported_platform_reason(account.platform))

    digits = "".join(char for char in payload.phone_number if char.isdigit())
    account.status = "可用"
    account.session_status = "已登录"
    account.risk_status = "正常"
    account.last_error = None
    account.last_login_check_at = datetime.utcnow()
    if len(digits) >= 4:
        account.login_label = f"个人号尾号{digits[-4:]}"

    db.commit()
    db.refresh(account)
    return account


@router.post("/accounts/{account_id}/preflight", response_model=DmAccountRead)
def preflight_dm_account(account_id: str, db: Session = Depends(get_db)) -> DirectMessageAccount:
    account = db.get(DirectMessageAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="平台个人号不存在")

    normalize_account_state(account)
    if _apply_dm_account_support_status(account):
        db.commit()
        db.refresh(account)
        return account

    previous_login_check_at = account.last_login_check_at
    account.last_login_check_at = datetime.utcnow()
    has_profile_session = profile_has_session_artifacts(account, previous_login_check_at, include_existing=True)
    if settings.dm_gateway_mode == "simulator":
        account.status = "可用"
        account.session_status = "已登录" if account.session_status == "已登录" or has_profile_session else "模拟可用"
        account.risk_status = "正常"
        account.last_error = None
    elif settings.dm_gateway_mode == "browser":
        config = _platform_config(db, account.platform)
        result = BrowserAutomationDmGateway().preflight_account(account, config)
        account.status = result.account_status
        account.session_status = result.session_status
        account.risk_status = result.risk_status
        account.last_error = result.last_error
        if result.session_status != "已登录" and has_profile_session:
            account.status = "可用"
            account.session_status = "已登录"
            account.risk_status = "正常"
            account.last_error = None
    elif account.session_status != "已登录":
        if has_profile_session:
            account.status = "可用"
            account.session_status = "已登录"
            account.risk_status = "正常"
            account.last_error = None
        else:
            account.status = "待登录"
            account.last_error = "请先在客户端完成该平台个人号扫码登录"

    db.commit()
    db.refresh(account)
    return account


@router.get("/platform-configs", response_model=list[DmPlatformConfigRead])
def list_dm_platform_configs(db: Session = Depends(get_db)) -> list[DirectMessagePlatformConfig]:
    return _seed_default_platform_configs(db)


@router.post("/platform-configs", response_model=DmPlatformConfigRead)
def create_dm_platform_config(payload: DmPlatformConfigCreate, db: Session = Depends(get_db)) -> DirectMessagePlatformConfig:
    if payload.platform not in SUPPORTED_DM_PLATFORMS:
        raise HTTPException(status_code=400, detail=_unsupported_platform_reason(payload.platform))

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

    next_platform = payload.platform if payload.platform is not None else config.platform
    if next_platform not in SUPPORTED_DM_PLATFORMS:
        raise HTTPException(status_code=400, detail=_unsupported_platform_reason(next_platform))

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

    sendable_leads = [lead for lead in leads if lead.platform in SUPPORTED_DM_PLATFORMS]
    if not sendable_leads:
        raise HTTPException(status_code=400, detail="当前选择的线索没有可私信平台；视频号助手不支持主动私信商家")

    account_id = None
    if payload.account_id:
        account = db.get(DirectMessageAccount, payload.account_id)
        if not account:
            raise HTTPException(status_code=400, detail="平台个人号不存在")
        if account.platform not in SUPPORTED_DM_PLATFORMS:
            raise HTTPException(status_code=400, detail=_unsupported_platform_reason(account.platform))
        selected_platforms = {lead.platform for lead in sendable_leads}
        if selected_platforms != {account.platform}:
            raise HTTPException(status_code=400, detail=f"指定账号只能发送{account.platform}线索；混合平台任务请使用自动轮换")
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
