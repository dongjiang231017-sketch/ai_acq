from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.lead import MerchantLead
from app.models.task import DirectMessage, DirectMessageAccount, DirectMessageConversation, DirectMessagePlatformConfig
from app.services.dm_gateway import BrowserAutomationDmGateway


@dataclass(frozen=True)
class DmReplySyncResult:
    checked: int
    new_replies: int
    needs_handoff: int


def sync_simulated_dm_replies(db: Session, limit: int = 50) -> DmReplySyncResult:
    conversations = list(
        db.scalars(
            select(DirectMessageConversation)
            .where(DirectMessageConversation.status == "已发送")
            .order_by(DirectMessageConversation.created_at.desc())
            .limit(limit)
        ).all()
    )

    new_replies = 0
    needs_handoff = 0
    for conversation in conversations:
        lead = db.get(MerchantLead, conversation.lead_id)
        if not lead or lead.intent_score < 65:
            continue

        reply = "可以，发我看看。" if lead.intent_score >= 80 else "怎么收费？需要准备什么资料？"
        intent_level = "A" if lead.intent_score >= 80 else "B"
        conversation.status = "已回复"
        conversation.intent_level = intent_level
        conversation.last_message = reply
        conversation.last_message_at = datetime.utcnow()
        conversation.need_handoff = True
        db.add(
            DirectMessage(
                conversation_id=conversation.id,
                direction="inbound",
                content=reply,
                status="已接收",
                external_message_id=f"sim-reply-{conversation.id}",
                raw_payload='{"provider":"simulator","source":"reply-sync"}',
            )
        )
        lead.status = "高意向" if intent_level == "A" else "需跟进"
        new_replies += 1
        needs_handoff += 1

    db.commit()
    return DmReplySyncResult(checked=len(conversations), new_replies=new_replies, needs_handoff=needs_handoff)


def _platform_config_for_account(db: Session, account: DirectMessageAccount) -> DirectMessagePlatformConfig | None:
    return db.scalar(
        select(DirectMessagePlatformConfig)
        .where(DirectMessagePlatformConfig.platform == account.platform)
        .order_by(DirectMessagePlatformConfig.created_at.desc())
    )


def sync_browser_dm_replies(db: Session, limit: int = 50) -> DmReplySyncResult:
    accounts = list(
        db.scalars(
            select(DirectMessageAccount)
            .where(
                DirectMessageAccount.status == "可用",
                DirectMessageAccount.session_status == "已登录",
            )
            .order_by(DirectMessageAccount.last_sync_at.asc().nullsfirst(), DirectMessageAccount.created_at.asc())
        ).all()
    )
    gateway = BrowserAutomationDmGateway()
    checked = 0
    new_replies = 0
    needs_handoff = 0

    for account in accounts:
        config = _platform_config_for_account(db, account)
        try:
            replies = gateway.collect_replies(account, config, limit=limit)
        except RuntimeError as exc:
            account.last_error = str(exc)
            account.last_sync_at = datetime.utcnow()
            continue

        account.last_error = None
        account.last_sync_at = datetime.utcnow()
        checked += len(replies)
        for reply in replies:
            if reply.external_message_id:
                exists = db.scalar(
                    select(DirectMessage).where(DirectMessage.external_message_id == reply.external_message_id)
                )
                if exists:
                    continue

            conversation = db.scalar(
                select(DirectMessageConversation)
                .where(
                    DirectMessageConversation.account_id == account.id,
                    DirectMessageConversation.merchant_name == reply.merchant_name,
                )
                .order_by(DirectMessageConversation.created_at.desc())
            )
            if not conversation:
                continue

            conversation.status = "已回复"
            conversation.intent_level = conversation.intent_level if conversation.intent_level in {"A", "B"} else "B"
            conversation.last_message = reply.content
            conversation.last_message_at = datetime.utcnow()
            conversation.need_handoff = True
            db.add(
                DirectMessage(
                    conversation_id=conversation.id,
                    direction="inbound",
                    content=reply.content,
                    status="已接收",
                    external_message_id=reply.external_message_id,
                    raw_payload=reply.raw_payload,
                )
            )
            lead = db.get(MerchantLead, conversation.lead_id)
            if lead:
                lead.status = "需跟进"
            new_replies += 1
            needs_handoff += 1

    db.commit()
    return DmReplySyncResult(checked=checked, new_replies=new_replies, needs_handoff=needs_handoff)


def sync_dm_replies(db: Session, limit: int = 50) -> DmReplySyncResult:
    if settings.dm_gateway_mode == "browser":
        return sync_browser_dm_replies(db, limit=limit)
    return sync_simulated_dm_replies(db, limit=limit)
