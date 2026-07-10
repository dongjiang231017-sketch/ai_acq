from __future__ import annotations

import json
from hashlib import sha1
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.growth import FollowUpWorkOrder, IntentCustomer, IntentEvent
from app.models.lead import MerchantLead


STRONG_REALTIME_INTENTS = {"加微信/发资料"}
STRONG_INTENT_TEXT_MARKERS = ("加微信", "微信发", "发资料", "发案例", "资料发", "案例发", "发我", "给我发")
NEGATIVE_PUSH_MARKERS = ("不加微信", "不用加微信", "不要加微信", "不需要资料", "不用资料", "不要资料", "别发资料")


def realtime_call_context_path() -> Path:
    event_path = Path(settings.realtime_call_event_log_path).expanduser()
    return event_path.with_name("realtime_call_context.jsonl")


def register_realtime_test_call_context(
    *,
    phone: str,
    caller_id: str | None,
    requested_route: str,
    effective_route: str,
    merchant_name: str | None = None,
    source: str = "realtime_test_call",
    task_id: str | None = None,
    lead_id: str | None = None,
) -> None:
    _append_context_record(
        {
            "type": "submit",
            "createdAt": _now_iso(),
            "phone": phone.strip(),
            "merchantName": (merchant_name or caller_id or "单号真实试拨").strip() or "单号真实试拨",
            "callerId": (caller_id or "").strip(),
            "requestedRoute": requested_route,
            "effectiveRoute": effective_route,
            "source": source,
            "taskId": task_id or "",
            "leadId": lead_id or "",
        }
    )


def claim_realtime_call_context(call_id: str) -> dict[str, Any]:
    call_key = _call_key(call_id)
    if not call_key:
        return {}
    records = _read_context_records()
    for record in reversed(records):
        if record.get("type") == "claim" and _call_key(str(record.get("callId") or "")) == call_key:
            return _context_for_submit(records, str(record.get("submitId") or ""))
    claimed_submit_ids = {str(record.get("submitId") or "") for record in records if record.get("type") == "claim"}
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    for record in reversed(records):
        if record.get("type") != "submit":
            continue
        submit_id = str(record.get("submitId") or _submit_id(record))
        if submit_id in claimed_submit_ids:
            continue
        if _parse_iso(str(record.get("createdAt") or "")) < cutoff:
            continue
        _append_context_record({"type": "claim", "createdAt": _now_iso(), "callId": call_id, "submitId": submit_id})
        context = dict(record)
        context["submitId"] = submit_id
        return context
    return {}


def record_realtime_intent_signal(
    *,
    call_id: str,
    context: dict[str, Any] | None,
    text: str,
    intent: str,
    signal: str,
    source: str,
    force: bool = False,
    evidence: str | None = None,
    latest_signal: str | None = None,
    wechat_id: str | None = None,
    wechat_is_phone: bool = False,
    intent_level: str = "A",
    intent_score: int = 92,
    need_handoff: bool = True,
    follow_status: str = "待分配",
) -> dict[str, Any] | None:
    if not force and not _is_strong_realtime_intent(text, intent):
        return None
    source_record_id = _call_key(call_id)
    if not source_record_id:
        return None
    context = context or {}
    phone = str(context.get("phone") or "").strip() or None
    merchant_name = str(context.get("merchantName") or "").strip() or "单号真实试拨"
    evidence = evidence or "客户明确要求加微信/发资料"
    latest_signal = latest_signal or text
    level = intent_level if intent_level in {"A", "B", "C"} else "A"
    score = max(0, min(100, int(intent_score or 0)))
    clean_wechat_id = (wechat_id or "").strip()[:80] or None
    with SessionLocal() as db:
        try:
            lead = _find_lead(db, phone, lead_id=str(context.get("leadId") or "").strip() or None)
            if lead and clean_wechat_id:
                lead.wechat_id = clean_wechat_id
            customer = _find_customer(db, lead.id if lead else None, phone, merchant_name)
            if not customer:
                customer = IntentCustomer(
                    lead_id=lead.id if lead else None,
                    merchant_name=lead.name if lead else merchant_name,
                    platform=lead.platform if lead else "电话",
                    city=lead.city if lead else "",
                    category=lead.category if lead else "",
                    contact_name=lead.contact_name if lead else None,
                    phone=lead.phone if lead else phone,
                    intent_level=level,
                    intent_score=score,
                    source_channels="实时电话",
                    latest_signal=latest_signal,
                    evidence_summary=evidence,
                    follow_status=follow_status,
                    need_handoff=need_handoff,
                )
                db.add(customer)
                db.flush()
            else:
                current_score = int(customer.intent_score or 0)
                if score >= current_score:
                    customer.intent_level = level
                customer.intent_score = max(current_score, score)
                customer.source_channels = _merge_channels(customer.source_channels, "实时电话")
                customer.latest_signal = latest_signal
                customer.evidence_summary = evidence
                customer.need_handoff = customer.need_handoff or need_handoff
                customer.follow_status = follow_status
                if phone and not customer.phone:
                    customer.phone = phone

            event = db.scalar(
                select(IntentEvent).where(
                    IntentEvent.source_type == "realtime_call",
                    IntentEvent.source_record_id == source_record_id,
                )
            )
            if not event:
                db.add(
                    IntentEvent(
                        customer_id=customer.id,
                        lead_id=customer.lead_id,
                        source_type="realtime_call",
                        source_record_id=source_record_id,
                        channel="实时电话",
                        intent_level=level,
                        summary=_short(evidence, 240),
                        evidence_text=latest_signal,
                        need_handoff=need_handoff,
                    )
                )
            else:
                event.customer_id = customer.id
                event.lead_id = customer.lead_id
                event.intent_level = level
                event.summary = _short(evidence, 240)
                event.evidence_text = latest_signal
                event.need_handoff = event.need_handoff or need_handoff
            _ensure_work_order(db, customer)
            db.commit()
            return {
                "customerId": customer.id,
                "intentLevel": customer.intent_level,
                "sourceRecordId": source_record_id,
                "summary": evidence,
                "signal": signal,
                "source": source,
                "wechatId": clean_wechat_id or "",
                "wechatIsPhone": wechat_is_phone,
            }
        except SQLAlchemyError:
            db.rollback()
            raise


def record_realtime_wechat_signal(
    *,
    call_id: str,
    context: dict[str, Any] | None,
    text: str,
    signal: str,
    source: str,
    wechat_id: str,
    wechat_is_phone: bool,
    summary: str = "",
) -> dict[str, Any] | None:
    clean_wechat_id = (wechat_id or "").strip()
    if not clean_wechat_id:
        return None
    evidence = summary or (
        f"客户同意加微信，确认当前手机号就是微信：{clean_wechat_id}"
        if wechat_is_phone
        else f"客户同意加微信，提供微信号：{clean_wechat_id}"
    )
    latest_signal = f"{evidence}；客户原话：{text}"
    return record_realtime_intent_signal(
        call_id=call_id,
        context=context,
        text=text,
        intent="加微信/发资料",
        signal=signal,
        source=source,
        force=True,
        evidence=evidence,
        latest_signal=latest_signal,
        wechat_id=clean_wechat_id,
        wechat_is_phone=wechat_is_phone,
    )


def _is_strong_realtime_intent(text: str, intent: str) -> bool:
    compact = "".join(text.split())
    if any(marker in compact for marker in NEGATIVE_PUSH_MARKERS):
        return False
    return intent in STRONG_REALTIME_INTENTS or any(marker in compact for marker in STRONG_INTENT_TEXT_MARKERS)


def _append_context_record(record: dict[str, Any]) -> None:
    path = realtime_call_context_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if record.get("type") == "submit":
        record = dict(record)
        record["submitId"] = _submit_id(record)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_context_records() -> list[dict[str, Any]]:
    path = realtime_call_context_path()
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-300:]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _context_for_submit(records: list[dict[str, Any]], submit_id: str) -> dict[str, Any]:
    for record in reversed(records):
        if record.get("type") == "submit" and str(record.get("submitId") or _submit_id(record)) == submit_id:
            context = dict(record)
            context["submitId"] = submit_id
            return context
    return {}


def _find_lead(db: Any, phone: str | None, *, lead_id: str | None = None) -> MerchantLead | None:
    if lead_id:
        lead = db.get(MerchantLead, lead_id)
        if lead is not None:
            return lead
    if not phone:
        return None
    return db.scalar(select(MerchantLead).where(MerchantLead.phone == phone).order_by(MerchantLead.updated_at.desc()))


def _find_customer(db: Any, lead_id: str | None, phone: str | None, merchant_name: str) -> IntentCustomer | None:
    if lead_id:
        customer = db.scalar(select(IntentCustomer).where(IntentCustomer.lead_id == lead_id))
        if customer:
            return customer
    if phone:
        customer = db.scalar(select(IntentCustomer).where(IntentCustomer.phone == phone).order_by(IntentCustomer.updated_at.desc()))
        if customer:
            return customer
    return db.scalar(select(IntentCustomer).where(IntentCustomer.merchant_name == merchant_name).order_by(IntentCustomer.updated_at.desc()))


def _ensure_work_order(db: Any, customer: IntentCustomer) -> None:
    priority = "P0" if customer.intent_level == "A" else "P1"
    due_hours = 4 if customer.intent_level == "A" else 24
    exists = db.scalar(
        select(FollowUpWorkOrder).where(
            FollowUpWorkOrder.customer_id == customer.id,
            FollowUpWorkOrder.status.in_(["待分配", "跟进中", "待确认"]),
        )
    )
    if exists:
        exists.priority = priority
        exists.last_note = customer.latest_signal
        return
    db.add(
        FollowUpWorkOrder(
            customer_id=customer.id,
            title=f"{customer.merchant_name} {customer.intent_level}级意向跟进",
            owner_name=customer.owner_name,
            status="待分配",
            priority=priority,
            sla_due_at=datetime.utcnow() + timedelta(hours=due_hours),
            last_note=customer.latest_signal,
        )
    )


def _merge_channels(existing: str, channel: str) -> str:
    channels = [item for item in existing.split(",") if item]
    if channel not in channels:
        channels.append(channel)
    return ",".join(channels)


def _short(text: str, limit: int) -> str:
    value = str(text or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _call_key(call_id: str) -> str:
    return "".join(char for char in call_id if char.isalnum()).lower()[:32]


def _submit_id(record: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(record.get("createdAt") or ""),
            str(record.get("phone") or ""),
            str(record.get("requestedRoute") or ""),
            str(record.get("effectiveRoute") or ""),
        ]
    )
    return sha1(raw.encode("utf-8")).hexdigest()[:24]


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _parse_iso(value: str) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except ValueError:
        return datetime.min
