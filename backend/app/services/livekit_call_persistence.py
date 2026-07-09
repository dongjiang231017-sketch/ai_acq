"""LiveKit 通话结果落库（2026-07-09，需求 7.7.7/7.7.9/7.9/7.10）。

此前 LiveKit 通话结束只写本地 jsonl，通话记录/线索状态/意向客户池/工单全部断链。
本模块在 worker 挂断回调里同步写库：

1. CallRecord：每通电话完整落库（转写、时长、意向等级、结果）。
2. MerchantLead：电话状态回写（有意向/已拨打/拒绝勿扰），刷新最近触达时间。
3. A/B 类意向：upsert IntentCustomer + 记 IntentEvent（电话渠道）。
4. A 类：自动生成高优先级跟进工单（FollowUpWorkOrder，P0）。
5. D 类（明确拒绝）：线索标记勿扰，不再进入后续外呼名单。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.growth import FollowUpWorkOrder, IntentCustomer, IntentEvent
from app.models.lead import MerchantLead
from app.models.task import CallRecord, OutreachTask


def _normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return digits


def _find_lead(db, *, lead_id: str | None, phone: str) -> MerchantLead | None:
    if lead_id:
        lead = db.get(MerchantLead, lead_id)
        if lead is not None:
            return lead
    normalized = _normalize_phone(phone)
    if not normalized:
        return None
    for candidate in db.scalars(
        select(MerchantLead).where(MerchantLead.phone.is_not(None)).order_by(MerchantLead.created_at.desc()).limit(2000),
    ):
        if _normalize_phone(candidate.phone) == normalized:
            return candidate
    return None


def persist_livekit_call_result(
    *,
    action_id: str,
    phone: str,
    merchant_name: str,
    task_id: str | None,
    lead_id: str | None,
    duration_seconds: int,
    connected: bool,
    intent_level: str,
    outcome: str,
    transcript: str,
    intent_reason: str,
    refused: bool,
) -> str | None:
    """写库并返回 CallRecord id；任何异常向上抛，由调用方兜底记录事件。"""

    with SessionLocal() as db:
        lead = _find_lead(db, lead_id=lead_id, phone=phone)
        display_name = merchant_name or (lead.name if lead else "") or "未知商户"

        record = CallRecord(
            task_id=task_id or None,
            lead_id=lead.id if lead else None,
            merchant_name=display_name,
            phone=phone,
            ai_seat="AI-01",
            duration_seconds=max(int(duration_seconds), 0),
            intent_level=intent_level,
            current_node="通话结束",
            outcome=outcome,
            transcript=transcript[:8000],
            gateway_call_id=action_id,
            gateway_status="completed" if connected else "no_answer",
            need_handoff=intent_level == "A",
        )
        db.add(record)
        db.flush()

        now = datetime.utcnow()
        if lead is not None:
            lead.last_contact_at = now
            if refused and intent_level == "D":
                lead.status = "勿扰"
                lead.follow_up_status = "已拒绝"
            elif intent_level in {"A", "B"}:
                lead.status = "有意向"
                lead.follow_up_status = "待跟进"
            elif connected:
                lead.status = "已拨打"
            else:
                lead.status = "未接通"

        if intent_level in {"A", "B"}:
            customer = None
            if lead is not None:
                customer = db.scalar(select(IntentCustomer).where(IntentCustomer.lead_id == lead.id))
            if customer is None and phone:
                customer = db.scalar(select(IntentCustomer).where(IntentCustomer.phone == phone))
            if customer is None:
                customer = IntentCustomer(
                    lead_id=lead.id if lead else None,
                    merchant_name=display_name,
                    platform=(lead.platform if lead else "外呼"),
                    city=(lead.city if lead else "") or "",
                    category=(lead.category if lead else "") or "",
                    phone=phone,
                    source_channels="外呼",
                )
                db.add(customer)
                db.flush()
            customer.intent_level = intent_level
            customer.intent_score = 90 if intent_level == "A" else 75
            customer.latest_signal = intent_reason[:200]
            customer.evidence_summary = intent_reason[:200]
            customer.need_handoff = intent_level == "A"
            if "外呼" not in (customer.source_channels or ""):
                customer.source_channels = f"{customer.source_channels},外呼".strip(",")

            db.add(
                IntentEvent(
                    customer_id=customer.id,
                    lead_id=lead.id if lead else None,
                    source_type="call_record",
                    source_record_id=record.id,
                    channel="外呼",
                    intent_level=intent_level,
                    summary=intent_reason[:200],
                    evidence_text=transcript[-2000:],
                    need_handoff=intent_level == "A",
                ),
            )

            if intent_level == "A":
                existing_order = db.scalar(
                    select(FollowUpWorkOrder).where(
                        FollowUpWorkOrder.customer_id == customer.id,
                        FollowUpWorkOrder.status.in_(["待分配", "处理中"]),
                    ),
                )
                if existing_order is None:
                    db.add(
                        FollowUpWorkOrder(
                            customer_id=customer.id,
                            title=f"{display_name} 电话确认意向，尽快加微信跟进",
                            priority="P0",
                            status="待分配",
                            sla_due_at=now + timedelta(hours=4),
                            last_note=intent_reason[:200],
                        ),
                    )

        if task_id:
            task = db.get(OutreachTask, task_id)
            if task is not None:
                task.completed_count = (task.completed_count or 0) + 1
                if outcome in {"有意向", "已接通", "稍后联系"}:
                    task.connected_count = (task.connected_count or 0) + 1
                if intent_level in {"A", "B"}:
                    task.intent_count = (task.intent_count or 0) + 1

        db.commit()
        return record.id
