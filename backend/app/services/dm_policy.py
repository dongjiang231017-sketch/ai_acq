from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lead import MerchantLead
from app.models.task import DirectMessageAccount, DirectMessageConversation, OutreachTask


AVAILABLE_ACCOUNT_STATUS = {"可用"}
AVAILABLE_SESSION_STATUS = {"模拟可用", "已登录"}
BLOCKED_RISK_STATUS = {"需验证", "风控暂停", "封禁", "异常"}
SENT_CONVERSATION_STATUS = {"已发送", "已回复"}


@dataclass(frozen=True)
class AccountCheck:
    ok: bool
    reason: str


def account_send_check(account: DirectMessageAccount, at: datetime | None = None) -> AccountCheck:
    now = at or datetime.utcnow()
    if account.status not in AVAILABLE_ACCOUNT_STATUS:
        return AccountCheck(False, f"账号状态为{account.status or '未知'}")
    if (account.session_status or "未登录") not in AVAILABLE_SESSION_STATUS:
        return AccountCheck(False, f"登录态为{account.session_status or '未登录'}")
    if (account.risk_status or "正常") in BLOCKED_RISK_STATUS:
        return AccountCheck(False, f"账号风险状态为{account.risk_status}")
    if account.cooldown_until and account.cooldown_until > now:
        return AccountCheck(False, f"账号冷却至{account.cooldown_until.isoformat()}")
    if account.sent_today >= account.daily_limit:
        return AccountCheck(False, "今日发送量已达上限")

    min_interval = account.min_send_interval_seconds or 0
    if min_interval and account.last_sent_at and account.last_sent_at + timedelta(seconds=min_interval) > now:
        return AccountCheck(False, f"距离上次发送不足{min_interval}秒")

    return AccountCheck(True, "可发送")


def pick_dm_account(db: Session, task: OutreachTask, at: datetime | None = None) -> tuple[DirectMessageAccount | None, str]:
    now = at or datetime.utcnow()
    if task.dm_account_id:
        account = db.get(DirectMessageAccount, task.dm_account_id)
        if not account:
            return None, "任务指定账号不存在"
        check = account_send_check(account, now)
        return (account, check.reason) if check.ok else (None, check.reason)

    accounts = list(
        db.scalars(
            select(DirectMessageAccount)
            .where(DirectMessageAccount.status == "可用")
            .order_by(DirectMessageAccount.sent_today.asc(), DirectMessageAccount.created_at.asc())
        ).all()
    )
    blocked_reasons: list[str] = []
    for account in accounts:
        check = account_send_check(account, now)
        if check.ok:
            return account, check.reason
        blocked_reasons.append(f"{account.account_name}:{check.reason}")

    return None, "暂无可用账号" if not blocked_reasons else "；".join(blocked_reasons[:3])


def find_existing_dm_conversation(db: Session, lead: MerchantLead) -> DirectMessageConversation | None:
    return db.scalar(
        select(DirectMessageConversation)
        .where(
            DirectMessageConversation.lead_id == lead.id,
            DirectMessageConversation.status.in_(SENT_CONVERSATION_STATUS),
        )
        .order_by(DirectMessageConversation.created_at.desc())
    )


def mark_account_sent(account: DirectMessageAccount, at: datetime | None = None) -> None:
    now = at or datetime.utcnow()
    account.sent_today += 1
    account.last_sent_at = now
    account.last_sync_at = now
    account.last_error = None


def pause_account_for_risk(account: DirectMessageAccount, reason: str, at: datetime | None = None) -> None:
    now = at or datetime.utcnow()
    account.status = "暂停"
    account.risk_status = "异常"
    account.cooldown_until = now + timedelta(hours=2)
    account.last_error = reason
