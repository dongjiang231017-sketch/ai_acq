from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.lead import MerchantLead
from app.models.task import CallRecord, CallScript, OutreachTask, RecallRule
from app.schemas.task import (
    CallRecordRead,
    CallScriptCreate,
    CallScriptRead,
    OutboundOverview,
    OutboundTaskCreate,
    RecallRuleRead,
    TaskRead,
)

router = APIRouter()


def _seed_default_script(db: Session) -> CallScript:
    script = db.scalar(select(CallScript).where(CallScript.is_active.is_(True)).order_by(CallScript.created_at.desc()))
    if script:
        return script

    script = CallScript(
        name="视频号团购商家邀约话术",
        opening="您好，我是视频号本地生活服务顾问，看到您店铺适合做团购曝光，想跟您确认下是否方便了解。",
        qualification="目前店里是否有团购、直播或短视频获客需求？每月希望新增多少到店客户？",
        objection="如果您担心费用，我们可以先按基础入驻和活动试跑讲，不需要马上决定。",
        closing="我先把入驻资料和适合您品类的案例发您，稍后安排同事跟进可以吗？",
        is_active=True,
    )
    db.add(script)
    db.commit()
    db.refresh(script)
    return script


def _mock_call_result(lead: MerchantLead, index: int) -> dict[str, object]:
    score = lead.intent_score
    if not lead.phone:
        return {
            "duration_seconds": 0,
            "intent_level": "无效",
            "current_node": "号码缺失",
            "outcome": "失败",
            "transcript": "系统：该商家没有电话，跳过外呼。",
            "need_handoff": False,
            "recall_at": None,
            "lead_status": "号码缺失",
        }
    if score >= 80:
        return {
            "duration_seconds": 138 + index * 8,
            "intent_level": "A",
            "current_node": "加微信",
            "outcome": "有意向",
            "transcript": "商家：可以，先发资料看看。AI：我安排顾问给您发入驻资料。",
            "need_handoff": True,
            "recall_at": None,
            "lead_status": "高意向",
        }
    if score >= 65:
        return {
            "duration_seconds": 72 + index * 6,
            "intent_level": "B",
            "current_node": "价格异议",
            "outcome": "已接通",
            "transcript": "商家：费用怎么收？AI：可以先给您发基础方案。",
            "need_handoff": False,
            "recall_at": datetime.utcnow() + timedelta(hours=4),
            "lead_status": "需复拨",
        }
    if score >= 50:
        return {
            "duration_seconds": 35 + index * 4,
            "intent_level": "C",
            "current_node": "老板忙",
            "outcome": "稍后联系",
            "transcript": "商家：现在忙，下午再打。AI：好的，我稍后再联系您。",
            "need_handoff": False,
            "recall_at": datetime.utcnow() + timedelta(hours=2),
            "lead_status": "需复拨",
        }
    return {
        "duration_seconds": 0,
        "intent_level": "D",
        "current_node": "未接通",
        "outcome": "未接通",
        "transcript": "系统：无人接听，进入重拨队列。",
        "need_handoff": False,
        "recall_at": datetime.utcnow() + timedelta(hours=6),
        "lead_status": "未接通",
    }


@router.get("/overview", response_model=OutboundOverview)
def outbound_overview(db: Session = Depends(get_db)) -> dict[str, int]:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_calls = db.scalar(select(func.count()).select_from(CallRecord).where(CallRecord.created_at >= today_start)) or 0
    connected = (
        db.scalar(
            select(func.count())
            .select_from(CallRecord)
            .where(CallRecord.created_at >= today_start, CallRecord.outcome.in_(["有意向", "已接通", "稍后联系"]))
        )
        or 0
    )
    intent_count = db.scalar(select(func.count()).select_from(CallRecord).where(CallRecord.intent_level.in_(["A", "B"]))) or 0
    needs_handoff = db.scalar(select(func.count()).select_from(CallRecord).where(CallRecord.need_handoff.is_(True))) or 0
    active_tasks = db.scalar(select(func.count()).select_from(OutreachTask).where(OutreachTask.status == "运行中")) or 0
    active_calls = min(int(active_tasks) * 5, 12)
    return {
        "aiSeats": 10,
        "activeCalls": active_calls,
        "needsHandoff": int(needs_handoff),
        "silentAlerts": 1 if active_calls > 0 else 0,
        "todayCalls": int(today_calls),
        "connectedRate": round((int(connected) / int(today_calls)) * 100) if today_calls else 0,
        "intentCount": int(intent_count),
    }


@router.get("/tasks", response_model=list[TaskRead])
def list_outbound_tasks(db: Session = Depends(get_db)) -> list[OutreachTask]:
    return list(
        db.scalars(
            select(OutreachTask).where(OutreachTask.channel == "call").order_by(OutreachTask.created_at.desc())
        ).all()
    )


@router.post("/tasks", response_model=TaskRead)
def create_outbound_task(payload: OutboundTaskCreate, db: Session = Depends(get_db)) -> OutreachTask:
    unique_lead_ids = list(dict.fromkeys(payload.lead_ids))
    leads = list(db.scalars(select(MerchantLead).where(MerchantLead.id.in_(unique_lead_ids))).all())
    if len(leads) != len(unique_lead_ids):
        raise HTTPException(status_code=400, detail="包含不存在的线索")

    script_id = payload.script_id or _seed_default_script(db).id
    task = OutreachTask(
        name=payload.name,
        channel="call",
        status="待启动",
        target_count=len(leads),
        concurrency=payload.concurrency,
        script_id=script_id,
        target_lead_ids=",".join(unique_lead_ids),
        scheduled_at=payload.scheduled_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.post("/tasks/{task_id}/start", response_model=TaskRead)
def start_outbound_task(task_id: str, db: Session = Depends(get_db)) -> OutreachTask:
    task = db.get(OutreachTask, task_id)
    if not task or task.channel != "call":
        raise HTTPException(status_code=404, detail="外呼任务不存在")

    target_lead_ids = [lead_id for lead_id in task.target_lead_ids.split(",") if lead_id]
    if target_lead_ids:
        target_leads = list(db.scalars(select(MerchantLead).where(MerchantLead.id.in_(target_lead_ids))).all())
        leads_by_id = {lead.id: lead for lead in target_leads}
        leads = [leads_by_id[lead_id] for lead_id in target_lead_ids if lead_id in leads_by_id and leads_by_id[lead_id].phone]
    else:
        leads = list(
            db.scalars(
                select(MerchantLead)
                .where(MerchantLead.phone.is_not(None))
                .order_by(MerchantLead.intent_score.desc())
            ).all()
        )
        leads = leads[: task.target_count or len(leads)]
    if not leads:
        raise HTTPException(status_code=400, detail="暂无可外呼线索")

    db.query(CallRecord).filter(CallRecord.task_id == task.id).delete()
    task.status = "运行中"
    task.started_at = datetime.utcnow()
    task.completed_count = 0
    task.connected_count = 0
    task.intent_count = 0
    task.failed_count = 0

    for index, lead in enumerate(leads):
        result = _mock_call_result(lead, index)
        record = CallRecord(
            task_id=task.id,
            lead_id=lead.id,
            merchant_name=lead.name,
            phone=lead.phone,
            ai_seat=f"AI-{index % max(task.concurrency, 1) + 1:02d}",
            duration_seconds=int(result["duration_seconds"]),
            intent_level=str(result["intent_level"]),
            current_node=str(result["current_node"]),
            outcome=str(result["outcome"]),
            transcript=str(result["transcript"]),
            need_handoff=bool(result["need_handoff"]),
            recall_at=result["recall_at"],
        )
        db.add(record)
        lead.status = str(result["lead_status"])
        if record.outcome in {"有意向", "已接通", "稍后联系"}:
            task.connected_count += 1
        if record.intent_level in {"A", "B"}:
            task.intent_count += 1
        if record.outcome == "失败":
            task.failed_count += 1

    task.completed_count = len(leads)
    task.status = "已完成"
    task.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


@router.get("/records", response_model=list[CallRecordRead])
def list_call_records(db: Session = Depends(get_db)) -> list[CallRecord]:
    return list(db.scalars(select(CallRecord).order_by(CallRecord.created_at.desc())).all())


@router.get("/live", response_model=list[CallRecordRead])
def live_calls(db: Session = Depends(get_db)) -> list[CallRecord]:
    return list(db.scalars(select(CallRecord).order_by(CallRecord.created_at.desc()).limit(8)).all())


@router.get("/scripts", response_model=list[CallScriptRead])
def list_call_scripts(db: Session = Depends(get_db)) -> list[CallScript]:
    _seed_default_script(db)
    return list(db.scalars(select(CallScript).order_by(CallScript.created_at.desc())).all())


@router.post("/scripts", response_model=CallScriptRead)
def create_call_script(payload: CallScriptCreate, db: Session = Depends(get_db)) -> CallScript:
    script = CallScript(**payload.model_dump(by_alias=False))
    db.add(script)
    db.commit()
    db.refresh(script)
    return script


@router.get("/recall-rules", response_model=list[RecallRuleRead])
def list_recall_rules(db: Session = Depends(get_db)) -> list[RecallRule]:
    rules = list(db.scalars(select(RecallRule).order_by(RecallRule.created_at.desc())).all())
    if rules:
        return rules
    rule = RecallRule(name="默认重拨规则")
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return [rule]
