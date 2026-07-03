from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.lead import MerchantLead
from app.models.task import CallRecord, OutreachTask
from app.services.outbound_gateway import (
    CallAttempt,
    OutboundGateway,
    OutboundGatewayConfigurationError,
    get_outbound_gateway,
)


def get_task_leads(db: Session, task: OutreachTask) -> list[MerchantLead]:
    target_lead_ids = [lead_id for lead_id in task.target_lead_ids.split(",") if lead_id]
    if target_lead_ids:
        target_leads = list(db.scalars(select(MerchantLead).where(MerchantLead.id.in_(target_lead_ids))).all())
        leads_by_id = {lead.id: lead for lead in target_leads}
        return [leads_by_id[lead_id] for lead_id in target_lead_ids if lead_id in leads_by_id and leads_by_id[lead_id].phone]

    leads = list(
        db.scalars(
            select(MerchantLead)
            .where(MerchantLead.phone.is_not(None))
            .order_by(MerchantLead.intent_score.desc())
        ).all()
    )
    return leads[: task.target_count or len(leads)]


def run_outbound_task(task_id: str, db: Session, gateway: OutboundGateway | None = None) -> OutreachTask:
    task = db.get(OutreachTask, task_id)
    if not task or task.channel != "call":
        raise HTTPException(status_code=404, detail="外呼任务不存在")

    leads = get_task_leads(db, task)
    if not leads:
        raise HTTPException(status_code=400, detail="暂无可外呼线索")

    active_gateway = gateway or get_outbound_gateway()
    db.query(CallRecord).filter(CallRecord.task_id == task.id).delete()
    task.status = "运行中"
    task.started_at = datetime.utcnow()
    task.finished_at = None
    task.completed_count = 0
    task.connected_count = 0
    task.intent_count = 0
    task.failed_count = 0

    try:
        for index, lead in enumerate(leads):
            ai_seat = f"AI-{index % max(task.concurrency, 1) + 1:02d}"
            result = active_gateway.place_call(CallAttempt(task=task, lead=lead, ai_seat=ai_seat, sequence=index))
            record = CallRecord(
                task_id=task.id,
                lead_id=lead.id,
                merchant_name=lead.name,
                phone=lead.phone,
                ai_seat=ai_seat,
                duration_seconds=result.duration_seconds,
                intent_level=result.intent_level,
                current_node=result.current_node,
                outcome=result.outcome,
                transcript=result.transcript,
                gateway_call_id=result.gateway_call_id,
                gateway_status=result.gateway_status,
                raw_payload=result.raw_payload,
                need_handoff=result.need_handoff,
                recall_at=result.recall_at,
            )
            db.add(record)
            lead.status = result.lead_status
            if record.outcome in {"有意向", "已接通", "稍后联系"}:
                task.connected_count += 1
            if record.intent_level in {"A", "B"}:
                task.intent_count += 1
            if record.outcome == "失败":
                task.failed_count += 1
    except OutboundGatewayConfigurationError:
        task.status = "启动失败"
        task.finished_at = datetime.utcnow()
        db.commit()
        raise

    task.completed_count = len(leads)
    task.status = "已完成"
    task.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task
