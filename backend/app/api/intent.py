from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.growth import FollowUpWorkOrder, IntentCustomer, IntentEvent
from app.models.lead import MerchantLead
from app.models.task import CallRecord, DirectMessageConversation
from app.schemas.intent import (
    FollowUpWorkOrderRead,
    IntentCustomerRead,
    IntentCustomerUpdate,
    IntentEventCreate,
    IntentEventRead,
    IntentOverview,
)

router = APIRouter()


def _level_from_score(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def _score_from_level(level: str) -> int:
    return {"A": 92, "B": 78, "C": 58, "D": 35}.get(level, 58)


def _merge_channels(existing: str, channel: str) -> str:
    channels = [item for item in existing.split(",") if item]
    if channel not in channels:
        channels.append(channel)
    return ",".join(channels)


def _find_customer(db: Session, lead_id: str | None, merchant_name: str) -> IntentCustomer | None:
    if lead_id:
        customer = db.scalar(select(IntentCustomer).where(IntentCustomer.lead_id == lead_id))
        if customer:
            return customer
    return db.scalar(select(IntentCustomer).where(IntentCustomer.merchant_name == merchant_name).order_by(IntentCustomer.created_at.desc()))


def _upsert_customer_from_lead(db: Session, lead: MerchantLead) -> IntentCustomer:
    customer = _find_customer(db, lead.id, lead.name)
    if not customer:
        customer = IntentCustomer(
            lead_id=lead.id,
            merchant_name=lead.name,
            platform=lead.platform,
            city=lead.city,
            category=lead.category,
            contact_name=lead.contact_name,
            phone=lead.phone,
            intent_level=_level_from_score(lead.intent_score),
            intent_score=lead.intent_score,
            source_channels="线索",
            latest_signal=f"{lead.source}录入，当前线索状态：{lead.status}",
            evidence_summary=f"线索意向分 {lead.intent_score}",
            follow_status="待分配" if lead.intent_score >= 70 else "观察中",
        )
        db.add(customer)
        db.flush()
    else:
        customer.platform = lead.platform
        customer.city = lead.city
        customer.category = lead.category
        customer.contact_name = lead.contact_name
        customer.phone = lead.phone
        customer.intent_score = max(customer.intent_score, lead.intent_score)
        customer.intent_level = min(customer.intent_level, _level_from_score(customer.intent_score))
        customer.source_channels = _merge_channels(customer.source_channels, "线索")
    return customer


def _add_event_once(
    db: Session,
    customer: IntentCustomer,
    source_type: str,
    source_record_id: str,
    channel: str,
    intent_level: str,
    summary: str,
    evidence_text: str,
    need_handoff: bool,
) -> None:
    event = db.scalar(
        select(IntentEvent).where(IntentEvent.source_type == source_type, IntentEvent.source_record_id == source_record_id)
    )
    if event:
        return
    db.add(
        IntentEvent(
            customer_id=customer.id,
            lead_id=customer.lead_id,
            source_type=source_type,
            source_record_id=source_record_id,
            channel=channel,
            intent_level=intent_level,
            summary=summary,
            evidence_text=evidence_text,
            need_handoff=need_handoff,
        )
    )


def _ensure_work_order(db: Session, customer: IntentCustomer) -> None:
    if customer.intent_level not in {"A", "B"} and not customer.need_handoff:
        return
    exists = db.scalar(
        select(FollowUpWorkOrder).where(
            FollowUpWorkOrder.customer_id == customer.id,
            FollowUpWorkOrder.status.in_(["待分配", "跟进中", "待确认"]),
        )
    )
    if exists:
        return
    due_hours = 4 if customer.intent_level == "A" else 24
    db.add(
        FollowUpWorkOrder(
            customer_id=customer.id,
            title=f"{customer.merchant_name} {customer.intent_level}级意向跟进",
            owner_name=customer.owner_name,
            status="待分配",
            priority="P0" if customer.intent_level == "A" else "P1",
            sla_due_at=datetime.utcnow() + timedelta(hours=due_hours),
            last_note=customer.latest_signal,
        )
    )


def _sync_intent_customers(db: Session) -> None:
    leads = list(db.scalars(select(MerchantLead).order_by(MerchantLead.created_at.desc())).all())
    for lead in leads:
        if lead.intent_score < 50:
            continue
        customer = _upsert_customer_from_lead(db, lead)
        if lead.intent_score >= 70:
            _ensure_work_order(db, customer)

    calls = list(db.scalars(select(CallRecord).order_by(CallRecord.created_at.desc()).limit(80)).all())
    for record in calls:
        if record.intent_level not in {"A", "B"} and not record.need_handoff:
            continue
        lead = db.get(MerchantLead, record.lead_id)
        customer = _upsert_customer_from_lead(db, lead) if lead else _find_customer(db, None, record.merchant_name)
        if not customer:
            customer = IntentCustomer(
                merchant_name=record.merchant_name,
                phone=record.phone,
                intent_level=record.intent_level,
                intent_score=_score_from_level(record.intent_level),
                source_channels="外呼",
                latest_signal=record.transcript,
                evidence_summary=record.outcome,
                need_handoff=record.need_handoff,
            )
            db.add(customer)
            db.flush()
        customer.intent_level = record.intent_level if record.intent_level in {"A", "B"} else customer.intent_level
        customer.intent_score = max(customer.intent_score, _score_from_level(record.intent_level))
        customer.source_channels = _merge_channels(customer.source_channels, "外呼")
        customer.latest_signal = record.transcript or record.outcome
        customer.evidence_summary = record.outcome
        customer.need_handoff = customer.need_handoff or record.need_handoff
        _add_event_once(
            db,
            customer,
            "call_record",
            record.id,
            "外呼",
            record.intent_level,
            record.outcome,
            record.transcript,
            record.need_handoff,
        )
        _ensure_work_order(db, customer)

    conversations = list(db.scalars(select(DirectMessageConversation).order_by(DirectMessageConversation.created_at.desc()).limit(80)).all())
    for conversation in conversations:
        if conversation.intent_level not in {"A", "B"} and not conversation.need_handoff:
            continue
        lead = db.get(MerchantLead, conversation.lead_id)
        customer = _upsert_customer_from_lead(db, lead) if lead else _find_customer(db, None, conversation.merchant_name)
        if not customer:
            customer = IntentCustomer(
                merchant_name=conversation.merchant_name,
                platform=conversation.platform,
                intent_level=conversation.intent_level,
                intent_score=_score_from_level(conversation.intent_level),
                source_channels="私信",
                latest_signal=conversation.last_message,
                evidence_summary=conversation.status,
                need_handoff=conversation.need_handoff,
            )
            db.add(customer)
            db.flush()
        customer.intent_level = conversation.intent_level if conversation.intent_level in {"A", "B"} else customer.intent_level
        customer.intent_score = max(customer.intent_score, _score_from_level(conversation.intent_level))
        customer.source_channels = _merge_channels(customer.source_channels, "私信")
        customer.latest_signal = conversation.last_message
        customer.evidence_summary = conversation.status
        customer.need_handoff = customer.need_handoff or conversation.need_handoff
        _add_event_once(
            db,
            customer,
            "dm_conversation",
            conversation.id,
            "私信",
            conversation.intent_level,
            conversation.status,
            conversation.last_message,
            conversation.need_handoff,
        )
        _ensure_work_order(db, customer)

    db.commit()


@router.get("/overview", response_model=IntentOverview)
def intent_overview(db: Session = Depends(get_db)) -> dict[str, int]:
    _sync_intent_customers(db)
    total = db.scalar(select(func.count()).select_from(IntentCustomer)) or 0
    high = db.scalar(select(func.count()).select_from(IntentCustomer).where(IntentCustomer.intent_level.in_(["A", "B"]))) or 0
    handoff = db.scalar(select(func.count()).select_from(IntentCustomer).where(IntentCustomer.need_handoff.is_(True))) or 0
    pending = (
        db.scalar(select(func.count()).select_from(FollowUpWorkOrder).where(FollowUpWorkOrder.status.in_(["待分配", "跟进中", "待确认"])))
        or 0
    )
    dnc = db.scalar(select(func.count()).select_from(IntentCustomer).where(IntentCustomer.dnc_status.is_(True))) or 0
    return {
        "totalCustomers": int(total),
        "highIntent": int(high),
        "needsHandoff": int(handoff),
        "pendingWorkOrders": int(pending),
        "dncBlocked": int(dnc),
    }


@router.get("/customers", response_model=list[IntentCustomerRead])
def list_intent_customers(db: Session = Depends(get_db)) -> list[IntentCustomer]:
    _sync_intent_customers(db)
    return list(
        db.scalars(
            select(IntentCustomer).order_by(IntentCustomer.need_handoff.desc(), IntentCustomer.intent_score.desc(), IntentCustomer.updated_at.desc())
        ).all()
    )


@router.get("/events", response_model=list[IntentEventRead])
def list_recent_intent_events(db: Session = Depends(get_db)) -> list[IntentEvent]:
    _sync_intent_customers(db)
    return list(db.scalars(select(IntentEvent).order_by(IntentEvent.created_at.desc()).limit(80)).all())


@router.patch("/customers/{customer_id}", response_model=IntentCustomerRead)
def update_intent_customer(
    customer_id: str, payload: IntentCustomerUpdate, db: Session = Depends(get_db)
) -> IntentCustomer:
    customer = db.get(IntentCustomer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="意向客户不存在")

    for field, value in payload.model_dump(exclude_unset=True, by_alias=False).items():
        setattr(customer, field, value)
    customer.updated_at = datetime.utcnow()
    _ensure_work_order(db, customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/customers/{customer_id}/events", response_model=list[IntentEventRead])
def list_intent_events(customer_id: str, db: Session = Depends(get_db)) -> list[IntentEvent]:
    customer = db.get(IntentCustomer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="意向客户不存在")
    return list(db.scalars(select(IntentEvent).where(IntentEvent.customer_id == customer_id).order_by(IntentEvent.created_at.desc())).all())


@router.post("/customers/{customer_id}/events", response_model=IntentEventRead)
def create_intent_event(customer_id: str, payload: IntentEventCreate, db: Session = Depends(get_db)) -> IntentEvent:
    customer = db.get(IntentCustomer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="意向客户不存在")
    event = IntentEvent(customer_id=customer.id, lead_id=customer.lead_id, **payload.model_dump(by_alias=False))
    customer.intent_level = payload.intent_level
    customer.intent_score = max(customer.intent_score, _score_from_level(payload.intent_level))
    customer.latest_signal = payload.evidence_text or payload.summary
    customer.need_handoff = customer.need_handoff or payload.need_handoff
    customer.updated_at = datetime.utcnow()
    db.add(event)
    _ensure_work_order(db, customer)
    db.commit()
    db.refresh(event)
    return event


@router.get("/work-orders", response_model=list[FollowUpWorkOrderRead])
def list_work_orders(db: Session = Depends(get_db)) -> list[FollowUpWorkOrder]:
    _sync_intent_customers(db)
    return list(db.scalars(select(FollowUpWorkOrder).order_by(FollowUpWorkOrder.created_at.desc())).all())
