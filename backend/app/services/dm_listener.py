from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lead import MerchantLead
from app.models.task import DirectMessage, DirectMessageConversation


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
