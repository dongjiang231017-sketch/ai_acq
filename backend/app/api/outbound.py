import logging
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
    CallScriptUpdate,
    OutboundOverview,
    OutboundTaskCreate,
    RecallRuleRead,
    RecallRuleUpdate,
    RealtimeLiveEventsRead,
    RealtimePipelineRead,
    RealtimeSessionCreate,
    RealtimeSessionRead,
    RealtimeTurnRead,
    RealtimeUtteranceCreate,
    TaskRead,
    TelephonyConfigRead,
    TelephonyHealthRead,
    TelephonyLineRecoveryRead,
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
from app.services.livekit_outbound import (
    LiveKitOutboundError,
    build_livekit_test_call_response,
    dispatch_livekit_outbound_call,
)
from app.services.realtime_intent_capture import register_realtime_test_call_context
from app.services.realtime_outbound import (
    RealtimeSessionNotFound,
    active_bridge_conversation_route,
    build_realtime_pipeline,
    complete_realtime_playback,
    create_realtime_session,
    get_realtime_session,
    handle_customer_utterance,
    interrupt_realtime_session,
    read_realtime_live_events,
)
from app.services.realtime_route_health import prepare_realtime_route_for_call
from app.services.telephony_cellular import build_cellular_diagnostic, recover_telephony_line
from app.services.telephony_preflight import build_telephony_preflight
from app.services.telephony_runtime_config import telephony_bool, telephony_int, telephony_str
from app.services.voice_gateway_profiles import current_voice_gateway_profile

router = APIRouter()
logger = logging.getLogger(__name__)


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


def _current_call_channel_limit() -> int:
    profile = current_voice_gateway_profile()
    return max(1, telephony_int("ASTERISK_MAX_CHANNELS", "VOICE_GATEWAY_MAX_CHANNELS", fallback=profile.max_channels))


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
    channel_limit = _current_call_channel_limit()
    active_calls = min(int(active_tasks) * channel_limit, channel_limit)
    return {
        "aiSeats": channel_limit,
        "activeCalls": active_calls,
        "needsHandoff": int(needs_handoff),
        "silentAlerts": 1 if active_calls > 0 else 0,
        "todayCalls": int(today_calls),
        "connectedRate": round((int(connected) / int(today_calls)) * 100) if today_calls else 0,
        "intentCount": int(intent_count),
    }


@router.get("/telephony/config", response_model=TelephonyConfigRead)
def telephony_config() -> dict[str, object]:
    profile = current_voice_gateway_profile()
    return {
        "gatewayMode": telephony_str("TELEPHONY_GATEWAY_MODE", fallback=settings.telephony_gateway_mode),
        "asteriskDeploymentMode": telephony_str("ASTERISK_DEPLOYMENT_MODE", "AI_ACQ_ASTERISK_DEPLOYMENT_MODE", fallback=settings.asterisk_deployment_mode),
        "voiceGatewayProfile": profile.as_dict(),
        "queueEnabled": settings.outbound_queue_enabled,
        "queueName": settings.outbound_queue_name,
        "redisUrlConfigured": bool(settings.redis_url),
        "asteriskHost": telephony_str("ASTERISK_HOST", "AI_ACQ_ASTERISK_HOST", fallback=settings.asterisk_host),
        "asteriskAmiPort": telephony_int("ASTERISK_AMI_PORT", "AI_ACQ_ASTERISK_AMI_PORT", fallback=settings.asterisk_ami_port),
        "asteriskUsernameConfigured": bool(telephony_str("ASTERISK_AMI_USERNAME", "AI_ACQ_ASTERISK_AMI_USERNAME", fallback=settings.asterisk_ami_username)),
        "asteriskTrunkName": profile.trunk_name,
        "asteriskMaxChannels": telephony_int("ASTERISK_MAX_CHANNELS", "VOICE_GATEWAY_MAX_CHANNELS", fallback=profile.max_channels),
        "asteriskLiveCallEnabled": telephony_bool("ASTERISK_LIVE_CALL_ENABLED", fallback=settings.asterisk_live_call_enabled),
        "asteriskBulkCallEnabled": telephony_bool("ASTERISK_BULK_CALL_ENABLED", fallback=settings.asterisk_bulk_call_enabled),
    }


@router.get("/telephony/health", response_model=TelephonyHealthRead)
def telephony_health() -> dict[str, object]:
    return check_asterisk_health().as_dict()


@router.get("/telephony/preflight", response_model=TelephonyPreflightRead)
def telephony_preflight(phone: str | None = None) -> dict[str, object]:
    return build_telephony_preflight(test_phone=phone)


@router.post("/telephony/recover-line", response_model=TelephonyLineRecoveryRead)
def recover_telephony_line_api() -> dict[str, object]:
    return recover_telephony_line()


@router.post("/telephony/test-call", response_model=TelephonyTestCallRead)
def create_telephony_test_call(payload: TelephonyTestCallCreate) -> dict[str, object]:
    started_at = datetime.utcnow()
    pipeline = build_realtime_pipeline()
    actual_bridge_route = str(pipeline.get("actualBridgeRoute") or active_bridge_conversation_route() or "pipeline")
    requested_route = (payload.conversation_route or actual_bridge_route or "pipeline").strip().lower()
    if requested_route not in {"pipeline", "omni", "livekit"}:
        requested_route = "pipeline"
    if requested_route == "livekit":
        try:
            livekit_result = dispatch_livekit_outbound_call(
                payload.phone,
                caller_id=payload.caller_id,
                merchant_name=payload.merchant_name or "单号真实试拨",
            )
        except LiveKitOutboundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return build_livekit_test_call_response(livekit_result)
    route_probe = prepare_realtime_route_for_call(requested_route)
    effective_route = route_probe.effective_route
    route_fallback_reason = route_probe.route_fallback_reason
    route_matched = requested_route == actual_bridge_route or (actual_bridge_route == "omni" and effective_route == "pipeline")
    if not route_matched:
        raise HTTPException(
            status_code=409,
            detail=(
                f"本次选择的是 {requested_route} 路线，但当前真实 AudioSocket bridge 正在运行 {actual_bridge_route}。"
                "请先把 bridge 重启到可承接该路线的模式，否则这通电话不会走你选择的路线。"
            ),
        )
    register_realtime_test_call_context(
        phone=payload.phone,
        caller_id=payload.caller_id,
        merchant_name=payload.merchant_name,
        requested_route=requested_route,
        effective_route=effective_route,
    )
    try:
        result = originate_test_call(payload.phone, caller_id=payload.caller_id, conversation_route=effective_route)
    except AsteriskAmiValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AsteriskAmiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    conversation_status = _wait_realtime_conversation_status_since(
        started_at,
        timeout_seconds=6.0 if result.cellular_confirmed else 0.0,
    )
    media_loop_confirmed = result.media_loop_confirmed or bool(conversation_status["mediaLoopConfirmed"])
    human_speech_confirmed = bool(conversation_status["humanSpeechConfirmed"])
    ai_speech_confirmed = bool(conversation_status["aiSpeechConfirmed"])
    call_screening_detected = bool(conversation_status["callScreeningDetected"])
    bridge_error = str(conversation_status.get("bridgeError") or "")
    conversation_confirmed = result.cellular_confirmed and human_speech_confirmed and ai_speech_confirmed
    acceptance_ready = result.acceptance_ready or conversation_confirmed
    acceptance_note = result.acceptance_note
    verification_stage = result.verification_stage
    if route_fallback_reason:
        acceptance_note = route_fallback_reason
        verification_stage = "realtime_route_fallback"
    if conversation_confirmed:
        verification_stage = "realtime_conversation_confirmed"
        acceptance_note = "已确认真人客户语音，且 AI 首句已实际播入电话；实时对话验收通过。"
    elif result.cellular_confirmed and media_loop_confirmed:
        verification_stage = "realtime_media_confirmed"
        acceptance_note = "线路和实时媒体桥已接通，但还没同时确认真人语音和 AI 首句播出。"
    if bridge_error and not conversation_confirmed:
        verification_stage = "realtime_bridge_error"
        acceptance_note = "电话已接通，但实时语音桥报错；系统会自动降级或允许重新试拨。"
    if call_screening_detected and not human_speech_confirmed:
        acceptance_note = "检测到电话助理/秘书提示，已说明来电原因；还未确认真人客户接听。"
    cellular_diagnostic = build_cellular_diagnostic(
        result,
        media_loop_confirmed=media_loop_confirmed,
        human_speech_confirmed=human_speech_confirmed,
        ai_speech_confirmed=ai_speech_confirmed,
        call_screening_detected=call_screening_detected,
        bridge_error=bridge_error,
    )
    auto_recovery = None
    if (
        not result.cellular_confirmed
        and not media_loop_confirmed
        and cellular_diagnostic.get("canRetry")
        and cellular_diagnostic.get("status") == "fail"
    ):
        auto_recovery = recover_telephony_line()
    logger.warning(
        "telephony_test_call_result action_id=%s phone=%s accepted=%s status=%s channel=%s route=%s/%s "
        "cellular_confirmed=%s media_loop_confirmed=%s human_speech=%s ai_speech=%s verification_stage=%s "
        "diagnostic_status=%s diagnostic_stage=%s diagnostic_title=%s message=%s raw_payload=%s",
        result.action_id,
        payload.phone[-4:].rjust(len(payload.phone), "*"),
        result.accepted,
        result.status,
        result.channel,
        requested_route,
        actual_bridge_route,
        result.cellular_confirmed,
        media_loop_confirmed,
        human_speech_confirmed,
        ai_speech_confirmed,
        verification_stage,
        cellular_diagnostic.get("status"),
        cellular_diagnostic.get("stage"),
        cellular_diagnostic.get("title"),
        result.message,
        result.raw_payload[:2000],
    )
    return {
        "accepted": result.accepted,
        "actionId": result.action_id,
        "channel": result.channel,
        "requestedRoute": requested_route,
        "actualBridgeRoute": actual_bridge_route,
        "effectiveRoute": effective_route,
        "routeFallbackReason": route_fallback_reason,
        "routeMatched": route_matched,
        "gatewayStatus": result.status,
        "message": result.message,
        "rawPayload": result.raw_payload,
        "verificationStage": verification_stage,
        "cellularConfirmed": result.cellular_confirmed,
        "mediaLoopConfirmed": media_loop_confirmed,
        "humanSpeechConfirmed": human_speech_confirmed,
        "aiSpeechConfirmed": ai_speech_confirmed,
        "callScreeningDetected": call_screening_detected,
        "bridgeError": bridge_error,
        "conversationConfirmed": conversation_confirmed,
        "acceptanceReady": acceptance_ready,
        "acceptanceNote": acceptance_note,
        "cellularDiagnostic": cellular_diagnostic,
        "autoRecovery": auto_recovery,
    }


def _wait_realtime_conversation_status_since(started_at: datetime, timeout_seconds: float = 0.0) -> dict[str, object]:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        status = _realtime_conversation_status_since(started_at)
        if status["conversationConfirmed"] or time.monotonic() >= deadline:
            return status
        if status["callScreeningDetected"] and time.monotonic() >= deadline - 1.0:
            return status
        time.sleep(0.25)


def _realtime_conversation_status_since(started_at: datetime) -> dict[str, object]:
    media_event_types = {
        "call_connected",
        "audio_capture_started",
        "remote_speech_started",
        "asr_final",
        "tts_start",
        "tts_done",
        "tts_interrupted",
        "call_screening_detected",
        "human_speech_confirmed",
    }
    status = {
        "mediaLoopConfirmed": False,
        "humanSpeechConfirmed": False,
        "aiSpeechConfirmed": False,
        "callScreeningDetected": False,
        "bridgeError": "",
        "conversationConfirmed": False,
    }
    events_payload = read_realtime_live_events(limit=160)
    for event in events_payload.get("events", []):
        event_type = str(event.get("type") or "")
        if event_type not in media_event_types and event_type not in {"call_error", "omni_start_failed_fallback", "omni_unavailable"}:
            continue
        at_text = str(event.get("at") or "")
        try:
            event_at = datetime.fromisoformat(at_text.replace("Z", ""))
        except ValueError:
            continue
        if event_at < started_at:
            continue
        if event_type in {"call_error", "omni_unavailable"}:
            status["bridgeError"] = str(event.get("error") or event.get("detail") or event.get("message") or event_type)
            continue
        if event_type == "omni_start_failed_fallback":
            status["bridgeError"] = ""
            status["mediaLoopConfirmed"] = True
            continue
        status["mediaLoopConfirmed"] = True
        if event_type == "human_speech_confirmed":
            status["humanSpeechConfirmed"] = True
        if event_type in {"tts_start", "tts_done"}:
            raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
            sent_bytes = int(raw.get("sentBytes") or raw.get("bytes") or 0)
            status["aiSpeechConfirmed"] = status["aiSpeechConfirmed"] or sent_bytes > 0
        if event_type == "call_screening_detected":
            status["callScreeningDetected"] = True
    status["conversationConfirmed"] = status["humanSpeechConfirmed"] and status["aiSpeechConfirmed"]
    return status

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
        conversation_route=payload.conversation_route,
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
    channel_limit = _current_call_channel_limit()
    if payload.concurrency > channel_limit:
        raise HTTPException(status_code=400, detail=f"当前语音网关最多支持 {channel_limit} 路并发，请把并发数量调到 {channel_limit} 或以下。")
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
    if payload.is_active:
        for active_script in db.scalars(select(CallScript).where(CallScript.is_active.is_(True))).all():
            active_script.is_active = False
    script = CallScript(**payload.model_dump(by_alias=False))
    db.add(script)
    db.commit()
    db.refresh(script)
    return script


@router.patch("/scripts/{script_id}", response_model=CallScriptRead)
def update_call_script(script_id: str, payload: CallScriptUpdate, db: Session = Depends(get_db)) -> CallScript:
    script = db.get(CallScript, script_id)
    if script is None:
        raise HTTPException(status_code=404, detail="话术不存在")
    if payload.is_active:
        for active_script in db.scalars(
            select(CallScript).where(CallScript.is_active.is_(True), CallScript.id != script_id)
        ).all():
            active_script.is_active = False
    for field, value in payload.model_dump(by_alias=False).items():
        setattr(script, field, value)
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


@router.patch("/recall-rules/{rule_id}", response_model=RecallRuleRead)
def update_recall_rule(rule_id: str, payload: RecallRuleUpdate, db: Session = Depends(get_db)) -> RecallRule:
    rule = db.get(RecallRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="重拨规则不存在")
    for field, value in payload.model_dump(by_alias=False).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule
