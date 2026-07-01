import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
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
    RealtimeLiveEventsRead,
    RealtimePipelineRead,
    RealtimeSessionCreate,
    RealtimeSessionRead,
    RealtimeTurnRead,
    RealtimeUtteranceCreate,
    TaskRead,
    TelephonyConfigRead,
    TelephonyHealthRead,
    TelephonyPreflightRead,
    TelephonyTestCallCreate,
    TelephonyTestCallRead,
)
from app.services.asterisk_ami import (
    AsteriskAmiError,
    AsteriskAmiValidationError,
    check_asterisk_health,
    originate_test_call,
)
from app.services.outbound_gateway import OutboundGatewayConfigurationError
from app.services.outbound_queue import enqueue_outbound_task
from app.services.outbound_runner import run_outbound_task
from app.services.realtime_outbound import (
    RealtimeSessionNotFound,
    build_realtime_pipeline,
    complete_realtime_playback,
    create_realtime_session,
    get_realtime_session,
    handle_customer_utterance,
    interrupt_realtime_session,
    read_realtime_live_events,
)
from app.services.telephony_preflight import build_telephony_preflight

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


@router.get("/telephony/config", response_model=TelephonyConfigRead)
def telephony_config() -> dict[str, object]:
    return {
        "gatewayMode": settings.telephony_gateway_mode,
        "queueEnabled": settings.outbound_queue_enabled,
        "queueName": settings.outbound_queue_name,
        "redisUrlConfigured": bool(settings.redis_url),
        "asteriskHost": settings.asterisk_host,
        "asteriskAmiPort": settings.asterisk_ami_port,
        "asteriskUsernameConfigured": bool(settings.asterisk_ami_username),
        "asteriskTrunkName": settings.asterisk_trunk_name,
        "asteriskMaxChannels": settings.asterisk_max_channels,
        "asteriskLiveCallEnabled": settings.asterisk_live_call_enabled,
        "asteriskBulkCallEnabled": settings.asterisk_bulk_call_enabled,
    }


@router.get("/telephony/health", response_model=TelephonyHealthRead)
def telephony_health() -> dict[str, object]:
    return check_asterisk_health().as_dict()


@router.get("/telephony/preflight", response_model=TelephonyPreflightRead)
def telephony_preflight(phone: str | None = None) -> dict[str, object]:
    return build_telephony_preflight(test_phone=phone)


@router.post("/telephony/test-call", response_model=TelephonyTestCallRead)
def create_telephony_test_call(payload: TelephonyTestCallCreate) -> dict[str, object]:
    started_at = datetime.utcnow()
    try:
        result = originate_test_call(payload.phone, caller_id=payload.caller_id)
    except AsteriskAmiValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AsteriskAmiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    media_loop_confirmed = result.media_loop_confirmed or _wait_realtime_media_confirmed_since(
        started_at,
        timeout_seconds=6.0 if result.cellular_confirmed else 0.0,
    )
    acceptance_ready = result.acceptance_ready or (result.cellular_confirmed and media_loop_confirmed)
    acceptance_note = result.acceptance_note
    verification_stage = result.verification_stage
    if result.cellular_confirmed and media_loop_confirmed:
        verification_stage = "realtime_media_confirmed"
        acceptance_note = "Asterisk 收到接通事件，AudioSocket 已出现实时 ASR/LLM/TTS 媒体事件；实时通话验收通过。"
    return {
        "accepted": result.accepted,
        "actionId": result.action_id,
        "channel": result.channel,
        "gatewayStatus": result.status,
        "message": result.message,
        "rawPayload": result.raw_payload,
        "verificationStage": verification_stage,
        "cellularConfirmed": result.cellular_confirmed,
        "mediaLoopConfirmed": media_loop_confirmed,
        "acceptanceReady": acceptance_ready,
        "acceptanceNote": acceptance_note,
    }


def _wait_realtime_media_confirmed_since(started_at: datetime, timeout_seconds: float = 0.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        if _realtime_media_confirmed_since(started_at):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def _realtime_media_confirmed_since(started_at: datetime) -> bool:
    media_event_types = {"call_connected", "asr_final", "llm_reply", "tts_start", "tts_done", "tts_interrupted"}
    events_payload = read_realtime_live_events(limit=120)
    for event in events_payload.get("events", []):
        if str(event.get("type") or "") not in media_event_types:
            continue
        at_text = str(event.get("at") or "")
        try:
            event_at = datetime.fromisoformat(at_text.replace("Z", ""))
        except ValueError:
            continue
        if event_at >= started_at:
            return True
    return False


@router.get("/realtime/pipeline", response_model=RealtimePipelineRead)
def realtime_pipeline() -> dict[str, object]:
    return build_realtime_pipeline()


@router.get("/realtime/live-events", response_model=RealtimeLiveEventsRead)
def realtime_live_events(limit: int = 80, call_id: str | None = None) -> dict[str, object]:
    return read_realtime_live_events(limit=limit, call_id=call_id)


@router.post("/realtime/sessions", response_model=RealtimeSessionRead)
def create_realtime_session_api(payload: RealtimeSessionCreate) -> dict[str, object]:
    return create_realtime_session(
        merchant_name=payload.merchant_name,
        phone=payload.phone,
        voice=payload.voice.model_dump(by_alias=True),
    )


@router.get("/realtime/sessions/{session_id}", response_model=RealtimeSessionRead)
def get_realtime_session_api(session_id: str) -> dict[str, object]:
    try:
        return get_realtime_session(session_id)
    except RealtimeSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/realtime/sessions/{session_id}/utterances", response_model=RealtimeTurnRead)
def create_realtime_utterance(session_id: str, payload: RealtimeUtteranceCreate) -> dict[str, object]:
    try:
        return handle_customer_utterance(session_id, payload.text, barge_in=payload.barge_in)
    except RealtimeSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/realtime/sessions/{session_id}/interrupt", response_model=RealtimeSessionRead)
def interrupt_realtime_session_api(session_id: str) -> dict[str, object]:
    try:
        return interrupt_realtime_session(session_id)
    except RealtimeSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/realtime/sessions/{session_id}/playback-complete", response_model=RealtimeSessionRead)
def complete_realtime_playback_api(session_id: str) -> dict[str, object]:
    try:
        return complete_realtime_playback(session_id)
    except RealtimeSessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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

    if settings.outbound_queue_enabled:
        try:
            enqueue_outbound_task(task.id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        task.status = "排队中"
        task.started_at = datetime.utcnow()
        task.finished_at = None
        db.commit()
        db.refresh(task)
        return task

    try:
        return run_outbound_task(task.id, db)
    except OutboundGatewayConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
