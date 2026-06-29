from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lead import MerchantLead
from app.models.task import (
    DirectMessage,
    DirectMessageAccount,
    DirectMessageConversation,
    DirectMessagePlatformConfig,
    DirectMessageTemplate,
    OutreachTask,
)
from app.services.dm_gateway import DirectMessageGateway, DmAttempt, get_dm_gateway
from app.services.dm_policy import (
    find_existing_dm_conversation,
    mark_account_sent,
    pause_account_for_risk,
    pick_dm_account,
    SUPPORTED_DM_PLATFORMS,
    UNSUPPORTED_DM_PLATFORM_REASONS,
)


def get_dm_task_leads(db: Session, task: OutreachTask) -> list[MerchantLead]:
    target_lead_ids = [lead_id for lead_id in task.target_lead_ids.split(",") if lead_id]
    if target_lead_ids:
        target_leads = list(db.scalars(select(MerchantLead).where(MerchantLead.id.in_(target_lead_ids))).all())
        leads_by_id = {lead.id: lead for lead in target_leads}
        return [leads_by_id[lead_id] for lead_id in target_lead_ids if lead_id in leads_by_id]

    leads = list(db.scalars(select(MerchantLead).order_by(MerchantLead.intent_score.desc())).all())
    return leads[: task.target_count or len(leads)]


def _get_dm_account(db: Session, task: OutreachTask) -> DirectMessageAccount | None:
    if task.dm_account_id:
        return db.get(DirectMessageAccount, task.dm_account_id)
    return db.scalar(select(DirectMessageAccount).where(DirectMessageAccount.status == "可用").order_by(DirectMessageAccount.created_at.desc()))


def _get_dm_template(db: Session, task: OutreachTask) -> DirectMessageTemplate | None:
    template_id = task.dm_template_id or task.script_id
    if template_id:
        return db.get(DirectMessageTemplate, template_id)
    return db.scalar(
        select(DirectMessageTemplate).where(DirectMessageTemplate.is_active.is_(True)).order_by(DirectMessageTemplate.created_at.desc())
    )


def _get_platform_config(db: Session, platform: str) -> DirectMessagePlatformConfig | None:
    return db.scalar(
        select(DirectMessagePlatformConfig)
        .where(DirectMessagePlatformConfig.platform == platform)
        .order_by(DirectMessagePlatformConfig.created_at.desc())
    )


def _clear_existing_conversations(db: Session, task_id: str) -> None:
    conversation_ids = list(
        db.scalars(select(DirectMessageConversation.id).where(DirectMessageConversation.task_id == task_id)).all()
    )
    if conversation_ids:
        db.query(DirectMessage).filter(DirectMessage.conversation_id.in_(conversation_ids)).delete(synchronize_session=False)
    db.query(DirectMessageConversation).filter(DirectMessageConversation.task_id == task_id).delete(synchronize_session=False)


def run_dm_task(task_id: str, db: Session, gateway: DirectMessageGateway | None = None) -> OutreachTask:
    task = db.get(OutreachTask, task_id)
    if not task or task.channel != "dm":
        raise HTTPException(status_code=404, detail="私信任务不存在")

    leads = get_dm_task_leads(db, task)
    if not leads:
        raise HTTPException(status_code=400, detail="暂无可私信线索")

    template = _get_dm_template(db, task)
    if not template:
        raise HTTPException(status_code=400, detail="暂无可用私信模板")

    active_gateway = gateway or get_dm_gateway()
    _clear_existing_conversations(db, task.id)
    task.status = "运行中"
    task.started_at = datetime.utcnow()
    task.finished_at = None
    task.completed_count = 0
    task.connected_count = 0
    task.intent_count = 0
    task.failed_count = 0

    for index, lead in enumerate(leads):
        now = datetime.utcnow()
        if lead.platform not in SUPPORTED_DM_PLATFORMS:
            db.add(
                DirectMessageConversation(
                    task_id=task.id,
                    lead_id=lead.id,
                    account_id=None,
                    platform=lead.platform,
                    merchant_name=lead.name,
                    status="平台不支持",
                    intent_level="跳过",
                    last_message=UNSUPPORTED_DM_PLATFORM_REASONS.get(lead.platform, f"{lead.platform}暂不支持平台私信"),
                    last_message_at=now,
                    need_handoff=False,
                )
            )
            task.failed_count += 1
            continue

        existing = find_existing_dm_conversation(db, lead)
        if existing:
            db.add(
                DirectMessageConversation(
                    task_id=task.id,
                    lead_id=lead.id,
                    account_id=existing.account_id,
                    platform=existing.platform,
                    merchant_name=lead.name,
                    status="已跳过",
                    intent_level="重复",
                    last_message="该商家已有私信触达记录，已跳过重复发送。",
                    last_message_at=now,
                    need_handoff=False,
                )
            )
            continue

        account, account_reason = pick_dm_account(db, task, lead, now)
        if not account:
            db.add(
                DirectMessageConversation(
                    task_id=task.id,
                    lead_id=lead.id,
                    account_id=None,
                    platform=lead.platform,
                    merchant_name=lead.name,
                    status="账号不可用",
                    intent_level="失败",
                    last_message=account_reason,
                    last_message_at=now,
                    need_handoff=False,
                )
            )
            task.failed_count += 1
            continue

        try:
            platform_config = _get_platform_config(db, account.platform)
            result = active_gateway.send_message(
                DmAttempt(
                    task=task,
                    lead=lead,
                    account=account,
                    template=template,
                    sequence=index,
                    platform_config=platform_config,
                )
            )
        except RuntimeError as exc:
            error_message = str(exc)
            if any(keyword in error_message for keyword in ["安全闸门", "缺少平台选择器", "选择器未启用", "缺少首页", "缺少商家页"]):
                account.last_error = error_message
            else:
                pause_account_for_risk(account, error_message, now)
            db.add(
                DirectMessageConversation(
                    task_id=task.id,
                    lead_id=lead.id,
                    account_id=account.id,
                    platform=account.platform,
                    merchant_name=lead.name,
                    status="发送失败",
                    intent_level="失败",
                    last_message=error_message,
                    last_message_at=now,
                    need_handoff=False,
                )
            )
            task.failed_count += 1
            continue

        conversation = DirectMessageConversation(
            task_id=task.id,
            lead_id=lead.id,
            account_id=account.id,
            platform=account.platform,
            merchant_name=lead.name,
            status=result.status,
            intent_level=result.intent_level,
            last_message=result.reply_content or result.outgoing_content,
            last_message_at=now,
            need_handoff=result.need_handoff,
        )
        db.add(conversation)
        db.flush()

        db.add(
            DirectMessage(
                conversation_id=conversation.id,
                direction="outbound",
                content=result.outgoing_content,
                status=result.status,
                external_message_id=result.external_message_id,
                raw_payload=result.raw_payload,
            )
        )
        mark_account_sent(account, now)

        if result.reply_content:
            db.add(
                DirectMessage(
                    conversation_id=conversation.id,
                    direction="inbound",
                    content=result.reply_content,
                    status="已接收",
                    external_message_id=f"{result.external_message_id}-reply" if result.external_message_id else None,
                    raw_payload='{"provider":"simulator","direction":"inbound"}',
                )
            )
            task.connected_count += 1

        if result.intent_level in {"A", "B"}:
            task.intent_count += 1
        if result.status == "失败":
            task.failed_count += 1

        lead.status = result.lead_status

    task.completed_count = len(leads)
    task.status = "已完成"
    task.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task
