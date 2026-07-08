from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from dotenv import load_dotenv

from app.core.config import settings
from app.services.livekit_outbound import _emit_livekit_event, _looks_like_dashscope_realtime_url, _masked_phone
from app.services.runtime_ai_config import get_runtime_ai_config
from app.services.realtime_sales_playbook import build_video_group_buying_sales_instructions


load_dotenv()


async def entrypoint(ctx: Any) -> None:
    from livekit import api
    from livekit.agents import Agent, AgentSession, inference, room_io

    metadata = _parse_metadata(getattr(ctx.job, "metadata", "") or "{}")
    action_id = str(metadata.get("actionId") or getattr(ctx.job, "id", "") or "")
    room_name = str(metadata.get("roomName") or getattr(ctx.room, "name", "") or "")
    participant_identity = str(metadata.get("participantIdentity") or "").strip()
    dial_phone = str(metadata.get("dialPhone") or metadata.get("phone") or "")
    trunk_id = str(metadata.get("sipOutboundTrunkId") or settings.livekit_sip_outbound_trunk_id).strip()
    merchant_name = str(metadata.get("merchantName") or "您的门店")
    opening_text = str(metadata.get("openingText") or settings.realtime_call_opening_text)
    agent_mode = str(metadata.get("agentMode") or settings.livekit_agent_mode or "openai_realtime").strip().lower()
    call_direction = "outbound" if dial_phone else "inbound"

    _emit_livekit_event(
        "livekit_agent_job_start",
        callId=action_id,
        roomName=room_name,
        participantIdentity=participant_identity,
        dialPhone=_masked_phone(dial_phone),
        agentMode=agent_mode,
        direction=call_direction,
        detail="LiveKit Agent worker 已收到 dispatch，准备连接 room。",
    )
    await ctx.connect()

    instructions = _build_agent_instructions(merchant_name=merchant_name)
    session = _build_agent_session(inference=inference, agent_mode=agent_mode)
    agent = Agent(instructions=instructions)
    room_input_kwargs: dict[str, Any] = {
        "pre_connect_audio": True,
        "pre_connect_audio_timeout": 5.0,
        "close_on_disconnect": True,
    }
    if participant_identity:
        room_input_kwargs["participant_identity"] = participant_identity

    await session.start(
        agent=agent,
        room=ctx.room,
        room_input_options=room_io.RoomInputOptions(**room_input_kwargs),
        room_output_options=room_io.RoomOutputOptions(
            transcription_enabled=True,
            sync_transcription=True,
        ),
    )
    _emit_livekit_event(
        "livekit_agent_session_started",
        callId=action_id,
        roomName=room_name,
        participantIdentity=participant_identity,
        agentMode=agent_mode,
        direction=call_direction,
        detail=(
            "AgentSession 已启动，接下来通过 LiveKit SIP outbound trunk 建呼。"
            if call_direction == "outbound"
            else "AgentSession 已启动，等待 SIP 入呼 participant 进入 room。"
        ),
    )

    if call_direction == "outbound":
        if not trunk_id:
            _emit_livekit_event("livekit_sip_error", callId=action_id, roomName=room_name, error="缺少 SIP outbound trunk id")
            ctx.shutdown("missing_sip_trunk")
            return
        if not participant_identity:
            participant_identity = f"customer-{_masked_phone(dial_phone).replace('*', 'x') or 'phone'}"

        try:
            sip_info = await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    sip_trunk_id=trunk_id,
                    sip_call_to=dial_phone,
                    sip_number=str(metadata.get("sipFromNumber") or settings.livekit_sip_from_number).strip(),
                    room_name=room_name,
                    participant_identity=participant_identity,
                    participant_name="客户电话",
                    participant_metadata=json.dumps(
                        {
                            "actionId": action_id,
                            "phone": _masked_phone(str(metadata.get("phone") or "")),
                            "route": "livekit",
                        },
                        ensure_ascii=False,
                    ),
                    wait_until_answered=bool(settings.livekit_sip_wait_until_answered),
                    krisp_enabled=bool(settings.livekit_sip_krisp_enabled),
                )
            )
        except Exception as exc:  # noqa: BLE001
            _emit_livekit_event(
                "livekit_sip_error",
                callId=action_id,
                roomName=room_name,
                participantIdentity=participant_identity,
                error=str(exc),
                detail="LiveKit SIP outbound 建呼失败。",
            )
            ctx.shutdown("sip_create_failed")
            return

        _emit_livekit_event(
            "livekit_sip_participant_created",
            callId=action_id,
            roomName=room_name,
            participantIdentity=participant_identity,
            sipParticipant=str(sip_info),
            detail="LiveKit SIP outbound participant 已创建；如 wait_until_answered=true，此时通常已接通或进入可对话状态。",
        )
    try:
        participant = await ctx.wait_for_participant(identity=participant_identity or None)
        participant_identity = str(getattr(participant, "identity", participant_identity) or participant_identity)
        _emit_livekit_event(
            "livekit_customer_joined",
            callId=action_id,
            roomName=room_name,
            participantIdentity=participant_identity,
            direction=call_direction,
            detail="客户 SIP participant 已进入 LiveKit room。",
        )
    except Exception as exc:  # noqa: BLE001
        _emit_livekit_event(
            "livekit_customer_wait_error",
            callId=action_id,
            roomName=room_name,
            participantIdentity=participant_identity,
            error=str(exc),
        )

    speech = session.say(opening_text, allow_interruptions=True)
    _emit_livekit_event(
        "tts_start",
        callId=action_id,
        roomName=room_name,
        provider="livekit_agent",
        text=opening_text,
        raw={"speechId": getattr(speech, "id", "")},
        detail="LiveKit Agent 已向客户播放开场白，允许客户插话打断。",
    )

    done = asyncio.Event()

    async def _on_shutdown(reason: str = "") -> None:
        _emit_livekit_event(
            "livekit_agent_shutdown",
            callId=action_id,
            roomName=room_name,
            reason=reason,
        )
        done.set()

    ctx.add_shutdown_callback(_on_shutdown)
    await done.wait()


def _build_agent_session(*, inference: Any, agent_mode: str) -> Any:
    from livekit.agents import APIConnectOptions

    if agent_mode == "inference":
        return _build_inference_agent_session(inference)
    return _build_openai_realtime_agent_session(connect_options=APIConnectOptions(max_retry=2, retry_interval=0.8, timeout=8.0))


def _build_openai_realtime_agent_session(*, connect_options: Any) -> Any:
    from livekit.agents import AgentSession
    from livekit.plugins import openai

    runtime_config = get_runtime_ai_config()
    base_url = (
        settings.livekit_openai_realtime_base_url.strip()
        or os.getenv("LIVEKIT_OPENAI_REALTIME_BASE_URL", "").strip()
        or runtime_config.dashscope_omni_realtime_url.strip()
    )
    if _looks_like_dashscope_realtime_url(base_url):
        api_key = (
            settings.livekit_openai_realtime_api_key.strip()
            or os.getenv("LIVEKIT_OPENAI_REALTIME_API_KEY", "").strip()
            or runtime_config.dashscope_api_key.strip()
            or os.getenv("DASHSCOPE_API_KEY", "").strip()
            or settings.dashscope_api_key.strip()
        )
        model = runtime_config.dashscope_omni_realtime_model.strip() or settings.livekit_openai_realtime_model.strip() or "qwen3.5-omni-plus-realtime"
        voice = runtime_config.dashscope_omni_realtime_voice.strip() or settings.livekit_openai_realtime_voice.strip() or "Serena"
    else:
        api_key = (
            settings.livekit_openai_realtime_api_key.strip()
            or os.getenv("LIVEKIT_OPENAI_REALTIME_API_KEY", "").strip()
            or settings.openai_api_key.strip()
            or os.getenv("OPENAI_API_KEY", "").strip()
        )
        model = settings.livekit_openai_realtime_model.strip() or "gpt-realtime"
        voice = settings.livekit_openai_realtime_voice.strip() or "marin"
    model_kwargs = {
        "model": model,
        "voice": voice,
        "api_key": api_key or None,
        "conn_options": connect_options,
    }
    if base_url:
        model_kwargs["base_url"] = base_url
    return AgentSession(
        llm=openai.realtime.RealtimeModel(**model_kwargs),
        allow_interruptions=True,
        min_interruption_duration=0.12,
        min_interruption_words=1,
        min_endpointing_delay=0.12,
        max_endpointing_delay=0.65,
        false_interruption_timeout=0.8,
        preemptive_generation=True,
        user_away_timeout=12.0,
    )


def _build_inference_agent_session(inference: Any) -> Any:
    from livekit.agents import AgentSession

    tts_voice = settings.livekit_agent_tts_voice.strip()
    return AgentSession(
        stt=inference.STT(
            model=settings.livekit_agent_stt_model.strip() or "deepgram/flux-general-multi",
            language=settings.livekit_agent_stt_language.strip() or "multi",
        ),
        llm=inference.LLM(model=settings.livekit_agent_llm_model.strip() or "openai/gpt-5-mini"),
        tts=(
            inference.TTS(model=settings.livekit_agent_tts_model.strip() or "elevenlabs/eleven_multilingual_v2", voice=tts_voice)
            if tts_voice
            else inference.TTS(model=settings.livekit_agent_tts_model.strip() or "elevenlabs/eleven_multilingual_v2")
        ),
        vad=inference.VAD(model="silero", min_speech_duration=0.05, min_silence_duration=0.2),
        allow_interruptions=True,
        min_interruption_duration=0.12,
        min_interruption_words=1,
        min_endpointing_delay=0.14,
        max_endpointing_delay=0.7,
        preemptive_generation=True,
        user_away_timeout=12.0,
    )


def _build_agent_instructions(*, merchant_name: str) -> str:
    base = build_video_group_buying_sales_instructions(merchant_name)
    return (
        f"{base}\n"
        "LiveKit 实时电话规则：客户说话或插话时立刻停下听；不要解释打断机制。"
        "回复要像日常外呼，短、快、自然；每次只解决一个问题。"
        "同一句话不要重复超过一遍；客户没听清时换一种更短的说法。"
        "这通电话的最终目标是确认客户是否有意向继续了解。"
        "确认有意向后，问客户方不方便加个微信，我们在微信上继续聊。"
        "客户同意加微信后必须确认当前手机号是不是微信；如果是，就明确记录为当前手机号可加微信；如果不是，就问微信号并复述确认。"
    )


def _parse_metadata(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    from livekit.agents import WorkerOptions, cli

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name=settings.livekit_agent_name.strip() or "ai-acq-outbound-agent",
            ws_url=settings.livekit_url.strip() or None,
            api_key=settings.livekit_api_key.strip() or None,
            api_secret=settings.livekit_api_secret.strip() or None,
        )
    )
