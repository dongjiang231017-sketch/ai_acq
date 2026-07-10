from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.livekit_call_persistence import (
    create_pending_livekit_call_record,
    mark_livekit_call_dispatch_failed,
)
from app.services.realtime_sales_playbook import VIDEO_GROUP_BUYING_OPENING_A
from app.services.runtime_ai_config import get_runtime_ai_config


class LiveKitOutboundError(RuntimeError):
    pass


_PIPELINE_MODE = "pipeline_clone"
_QWEN_OMNI_MODE = "omni"


def _normalize_livekit_agent_mode(value: str) -> str:
    # 所有正式 LiveKit 外呼固定走 Qwen Omni，历史配置不得把新任务
    # 调度到 Pipeline，从而避免一通电话出现多种声音/模型路线。
    del value
    return _QWEN_OMNI_MODE


@dataclass(frozen=True)
class LiveKitOutboundResult:
    accepted: bool
    action_id: str
    room_name: str
    participant_identity: str
    dispatch_id: str
    status: str
    message: str
    raw_payload: str


def livekit_config_status() -> dict[str, object]:
    mode = _normalize_livekit_agent_mode(settings.livekit_agent_mode or _QWEN_OMNI_MODE)
    runtime_config = get_runtime_ai_config()
    realtime_base_url = runtime_config.dashscope_omni_realtime_url.strip()
    realtime_provider = "qwen_omni_realtime"
    realtime_key_configured = bool(
        settings.livekit_openai_realtime_api_key.strip()
        or runtime_config.dashscope_api_key.strip()
    )
    pipeline_ready = bool(
        runtime_config.dashscope_api_key.strip()
        and runtime_config.realtime_asr_model.strip()
        and runtime_config.realtime_tts_voice_id.strip()
    )
    configured = bool(
        settings.livekit_url.strip()
        and settings.livekit_api_key.strip()
        and settings.livekit_api_secret.strip()
        and settings.livekit_agent_name.strip()
        and settings.livekit_sip_outbound_trunk_id.strip()
    )
    inference_ready = bool(settings.livekit_agent_stt_model.strip() and settings.livekit_agent_llm_model.strip() and settings.livekit_agent_tts_model.strip())
    agent_ready = pipeline_ready if mode == _PIPELINE_MODE else realtime_key_configured
    return {
        "configured": configured,
        "agentReady": agent_ready,
        "mode": mode,
        "realtimeProvider": realtime_provider,
        "realtimeBaseUrlConfigured": bool(realtime_base_url),
        "realtimeKeyConfigured": realtime_key_configured,
        "pipelineCloneReady": pipeline_ready,
        "pipelineDashscopeKeyConfigured": bool(runtime_config.dashscope_api_key.strip()),
        "pipelineAsrModelConfigured": bool(runtime_config.realtime_asr_model.strip()),
        "pipelineCloneVoiceConfigured": bool(runtime_config.realtime_tts_voice_id.strip()),
        "urlConfigured": bool(settings.livekit_url.strip()),
        "apiKeyConfigured": bool(settings.livekit_api_key.strip()),
        "apiSecretConfigured": bool(settings.livekit_api_secret.strip()),
        "agentName": settings.livekit_agent_name.strip(),
        "sipOutboundTrunkConfigured": bool(settings.livekit_sip_outbound_trunk_id.strip()),
        "openaiKeyConfigured": realtime_key_configured,
        "inferenceModelsConfigured": inference_ready,
        "readyForCall": configured and agent_ready,
    }


def require_livekit_outbound_ready() -> None:
    status = livekit_config_status()
    missing: list[str] = []
    if not status["urlConfigured"]:
        missing.append("LIVEKIT_URL")
    if not status["apiKeyConfigured"]:
        missing.append("LIVEKIT_API_KEY")
    if not status["apiSecretConfigured"]:
        missing.append("LIVEKIT_API_SECRET")
    if not status["sipOutboundTrunkConfigured"]:
        missing.append("LIVEKIT_SIP_OUTBOUND_TRUNK_ID")
    if status["mode"] == "omni" and not status["realtimeKeyConfigured"]:
        missing.append("OPENAI_API_KEY / LIVEKIT_OPENAI_REALTIME_API_KEY / DASHSCOPE_API_KEY")
    if status["mode"] == _PIPELINE_MODE:
        if not status["pipelineDashscopeKeyConfigured"]:
            missing.append("DASHSCOPE_API_KEY")
        if not status["pipelineAsrModelConfigured"]:
            missing.append("REALTIME_ASR_MODEL")
        if not status["pipelineCloneVoiceConfigured"]:
            missing.append("REALTIME_TTS_VOICE_ID / 运行时克隆音色")
    if missing:
        raise LiveKitOutboundError("LiveKit 外呼未配置完整：" + "、".join(missing))


def normalize_livekit_phone(phone: str) -> str:
    value = str(phone or "").strip()
    if value.startswith("+"):
        digits = "+" + "".join(ch for ch in value[1:] if ch.isdigit())
        if len(digits) >= 5:
            return digits
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        raise LiveKitOutboundError("电话号码不能为空")
    if len(digits) == 11 and digits.startswith("1"):
        prefix = settings.livekit_default_country_code.strip() or "+86"
        if prefix.lower() in {"raw", "none", "local"}:
            return digits
        return prefix.rstrip() + digits
    if digits.startswith("00") and len(digits) > 4:
        return "+" + digits[2:]
    if len(digits) >= 8:
        prefix = settings.livekit_default_country_code.strip()
        return f"{prefix}{digits}" if prefix.startswith("+") else digits
    raise LiveKitOutboundError("电话号码格式不正确")


def dispatch_livekit_outbound_call(
    phone: str,
    *,
    caller_id: str | None = None,
    merchant_name: str = "单号真实试拨",
    task_id: str | None = None,
    lead_id: str | None = None,
) -> LiveKitOutboundResult:
    require_livekit_outbound_ready()
    dial_phone = normalize_livekit_phone(phone)
    action_id = f"lk-{uuid4().hex}"
    room_name = f"ai-acq-outbound-{action_id}"
    participant_identity = f"customer-{re.sub(r'\\D+', '', dial_phone)[-8:] or uuid4().hex[:8]}"
    metadata = {
        "actionId": action_id,
        "phone": str(phone),
        "dialPhone": dial_phone,
        "callerId": caller_id or "",
        "merchantName": merchant_name,
        "roomName": room_name,
        "participantIdentity": participant_identity,
        "agentMode": _normalize_livekit_agent_mode(settings.livekit_agent_mode or _QWEN_OMNI_MODE),
        "taskId": task_id or "",
        "leadId": lead_id or "",
        "sipOutboundTrunkId": settings.livekit_sip_outbound_trunk_id.strip(),
        "sipFromNumber": settings.livekit_sip_from_number.strip(),
        "openingText": VIDEO_GROUP_BUYING_OPENING_A,
    }
    create_pending_livekit_call_record(
        action_id=action_id,
        phone=str(phone),
        merchant_name=merchant_name,
        task_id=task_id,
        lead_id=lead_id,
    )
    _emit_livekit_event(
        "livekit_dispatch_start",
        callId=action_id,
        roomName=room_name,
        participantIdentity=participant_identity,
        phone=_masked_phone(phone),
        dialPhone=_masked_phone(dial_phone),
        agentName=settings.livekit_agent_name.strip(),
        agentMode=metadata["agentMode"],
    )
    try:
        result = asyncio.run(_create_livekit_dispatch(room_name=room_name, metadata=metadata))
    except Exception as exc:
        try:
            mark_livekit_call_dispatch_failed(action_id, str(exc))
        except Exception:  # noqa: BLE001 - preserve the original dispatch failure.
            pass
        raise
    dispatch_id = str(
        result.get("agent_dispatch_id")
        or result.get("dispatchId")
        or result.get("sid")
        or result.get("id")
        or ""
    )
    raw_payload = json.dumps({"room": result, "metadata": _safe_metadata(metadata)}, ensure_ascii=False, default=str)
    _emit_livekit_event(
        "livekit_dispatch_submitted",
        callId=action_id,
        roomName=room_name,
        participantIdentity=participant_identity,
        dispatchId=dispatch_id,
        agentName=settings.livekit_agent_name.strip(),
        detail="LiveKit room 已创建并绑定 agent，等待 worker 接管 room 并通过 SIP trunk 拨号。",
    )
    return LiveKitOutboundResult(
        accepted=True,
        action_id=action_id,
        room_name=room_name,
        participant_identity=participant_identity,
        dispatch_id=dispatch_id,
        status="livekit_room_agent_queued",
        message="LiveKit room + Agent dispatch 已提交；Agent worker 会创建 SIP outbound call。",
        raw_payload=raw_payload,
    )


async def _create_livekit_dispatch(*, room_name: str, metadata: dict[str, object]) -> dict[str, object]:
    from google.protobuf.json_format import MessageToDict
    from livekit import api

    lkapi = api.LiveKitAPI(
        url=settings.livekit_url.strip(),
        api_key=settings.livekit_api_key.strip(),
        api_secret=settings.livekit_api_secret.strip(),
    )
    try:
        room = await lkapi.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                empty_timeout=120,
                max_participants=4,
                metadata=json.dumps({"route": "livekit", "actionId": metadata.get("actionId", "")}, ensure_ascii=False),
                agents=[
                    api.RoomAgentDispatch(
                        agent_name=settings.livekit_agent_name.strip(),
                        metadata=json.dumps(metadata, ensure_ascii=False),
                    )
                ],
            )
        )
        return MessageToDict(room, preserving_proto_field_name=True)
    finally:
        await lkapi.aclose()


def build_livekit_test_call_response(result: LiveKitOutboundResult) -> dict[str, object]:
    return {
        "accepted": result.accepted,
        "actionId": result.action_id,
        "channel": f"LiveKit/{result.room_name}/{result.participant_identity}",
        "requestedRoute": "livekit",
        "actualBridgeRoute": "livekit",
        "effectiveRoute": "livekit",
        "routeFallbackReason": "",
        "routeMatched": True,
        "gatewayStatus": result.status,
        "message": result.message,
        "rawPayload": result.raw_payload,
        "verificationStage": "livekit_room_agent_submitted",
        "cellularConfirmed": False,
        "mediaLoopConfirmed": False,
        "humanSpeechConfirmed": False,
        "aiSpeechConfirmed": False,
        "callScreeningDetected": False,
        "bridgeError": "",
        "conversationConfirmed": False,
        "acceptanceReady": False,
        "acceptanceNote": "LiveKit room + Agent dispatch 已提交。真实接通、真人语音和 AI 首句会由 LiveKit Agent worker 写入实时事件日志。",
        "cellularDiagnostic": {
            "status": "warn",
            "stage": "livekit_room_agent_submitted",
            "title": "LiveKit Agent 已接管外呼请求",
            "summary": "后端已经把外呼交给 LiveKit Agent；等待 SIP trunk 建呼和 Agent 实时对话事件。",
            "detail": "请确认 livekit outbound worker 正在运行，并在 LiveKit 控制台确认 SIP outbound trunk 可用。",
            "actionItems": [
                "启动：python -m app.tools.livekit_outbound_agent dev",
                "确认 LIVEKIT_URL/API_KEY/API_SECRET 和 LIVEKIT_SIP_OUTBOUND_TRUNK_ID 已配置。",
                "确认 Pipeline 的 DASHSCOPE_API_KEY、Paraformer ASR 模型和 CosyVoice 克隆音色已配置。",
            ],
            "technicalDetail": result.raw_payload[:1000],
            "canRetry": True,
            "customerActionRequired": False,
        },
        "autoRecovery": None,
    }


def _emit_livekit_event(event_type: str, **fields: object) -> None:
    payload = {
        "at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "type": event_type,
        **fields,
    }
    path = Path(settings.realtime_call_event_log_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _masked_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def _looks_like_dashscope_realtime_url(base_url: str) -> bool:
    normalized = base_url.strip().lower()
    return "dashscope.aliyuncs.com" in normalized or "maas.aliyuncs.com" in normalized


def _safe_metadata(metadata: dict[str, object]) -> dict[str, object]:
    safe = dict(metadata)
    for key in ("phone", "dialPhone"):
        if key in safe:
            safe[key] = _masked_phone(str(safe[key]))
    return safe
