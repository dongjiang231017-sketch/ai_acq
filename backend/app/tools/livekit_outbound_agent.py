from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

from app.core.config import settings
from app.services.livekit_outbound import _emit_livekit_event, _looks_like_dashscope_realtime_url, _masked_phone
from app.services.runtime_ai_config import get_runtime_ai_config
from app.services.realtime_sales_playbook import build_video_group_buying_sales_instructions


load_dotenv()

# 单通电话硬上限秒数：防止对语音信箱/静默线路无限烧钱（对齐 livekit-poc/agent/main.py）。
_MAX_CALL_SECONDS = int(os.getenv("LIVEKIT_MAX_CALL_SECONDS", "300"))

# 固定开场白录音：接通即播、一字不差、可被客户说话打断。
# 为什么不用模型说开场白：DashScope 对空上下文的 response.create 静默忽略
# （2026-07-09 真机复现：generate_reply 后 7.5s 无响应，直到客户先开口"喂"），
# Workbuddy 台子同日已验证固定录音方案。默认路径 backend/assets/opening.wav。
_OPENING_WAV_PATH = os.getenv(
    "OPENING_WAV_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "opening.wav"),
)


class _OpeningPlayer:
    """移植自 Workbuddy livekit-local/agent.py（2026-07-09 真机验证版）。"""

    def __init__(self, room: Any, path: str) -> None:
        self._room = room
        self._stop = False
        self._data = self._load(path)

    @staticmethod
    def _load(path: str) -> bytes:
        import struct
        import wave as _wave

        with _wave.open(path, "rb") as w:
            assert w.getframerate() == 24000 and w.getnchannels() == 1
            data = w.readframes(w.getnframes())

        def rms(seg: bytes) -> float:
            n = len(seg) // 2
            if not n:
                return 0.0
            ss = struct.unpack(f"<{n}h", seg[: n * 2])
            return (sum(x * x for x in ss) / n) ** 0.5

        win = 4800  # 100ms @24k
        start, end = 0, len(data)
        while start + win < end and rms(data[start:start + win]) < 200:
            start += win
        while end - win > start and rms(data[end - win:end]) < 200:
            end -= win
        return data[start:end]

    def stop(self) -> None:
        self._stop = True

    async def play(self, delay: float = 0.3) -> None:
        from livekit import rtc

        await asyncio.sleep(delay)
        src = rtc.AudioSource(24000, 1)
        track = rtc.LocalAudioTrack.create_audio_track("opening", src)
        await self._room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_UNKNOWN)
        )
        total = len(self._data) // 480  # 每帧 10ms @24k 16bit mono
        # 墙钟驱动：保证 play() 跑满真实时长才返回，避免音频一次性灌进缓冲、
        # 输入闸过早打开、模型抢答客户"喂"（Workbuddy 真机复现过的 bug）。
        start = time.monotonic()
        next_frame = 0
        while not self._stop:
            due = int((time.monotonic() - start) / 0.01)
            while next_frame <= due and next_frame < total:
                chunk = self._data[next_frame * 480:(next_frame + 1) * 480]
                if len(chunk) < 480:
                    chunk += b"\x00" * (480 - len(chunk))
                await src.capture_frame(
                    rtc.AudioFrame(data=chunk, sample_rate=24000, num_channels=1, samples_per_channel=240)
                )
                next_frame += 1
            if next_frame >= total:
                break
            await asyncio.sleep(0.01)


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
    session = _build_agent_session(inference=inference, agent_mode=agent_mode, instructions=instructions)
    agent = Agent(instructions=instructions)

    # 转向延迟打点（对齐 livekit-poc/agent/main.py）：客户停→AI出声的真实延迟，
    # 待办6 两线路 A/B 对比就看这个事件的 P50/P95，没有它对比无数据可用。
    last_user_stop = {"t": 0.0}

    # ---- 三层挂断基础设施（对齐 bench_agent_reference.py：道别/静默/硬上限）----
    hangup_flag = {"v": False}
    last_activity = {"t": time.monotonic()}
    call_started = {"t": 0.0}

    async def _hangup(reason: str, delay: float = 0.0) -> None:
        if hangup_flag["v"]:
            return
        hangup_flag["v"] = True
        if delay:
            await asyncio.sleep(delay)
        _emit_livekit_event("livekit_auto_hangup", callId=action_id, roomName=room_name, reason=reason)
        try:
            # 不能用 ctx.api：session 事件回调里 create_task 出来的协程没有 job 的
            # http 上下文，ctx.api 懒建 aiohttp session 会抛 "outside of a job context"，
            # 房间删不掉（07-09 真机复现：AI 道完别电话不挂）。自建 LiveKitAPI。
            lkapi = api.LiveKitAPI(
                url=settings.livekit_url.strip().replace("ws://", "http://").replace("wss://", "https://"),
                api_key=settings.livekit_api_key.strip(),
                api_secret=settings.livekit_api_secret.strip(),
            )
            try:
                await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))
            finally:
                await lkapi.aclose()
        except Exception as exc:  # noqa: BLE001
            _emit_livekit_event("livekit_auto_hangup_error", callId=action_id, roomName=room_name, error=str(exc))

    @session.on("user_state_changed")
    def _on_user_state(ev: Any) -> None:
        last_activity["t"] = time.monotonic()
        if str(getattr(ev, "new_state", "")) == "listening":
            last_user_stop["t"] = time.perf_counter()

    @session.on("agent_state_changed")
    def _on_agent_state(ev: Any) -> None:
        last_activity["t"] = time.monotonic()
        if str(getattr(ev, "new_state", "")) == "speaking" and last_user_stop["t"]:
            _emit_livekit_event(
                "turn_latency",
                callId=action_id,
                roomName=room_name,
                latencyMs=int((time.perf_counter() - last_user_stop["t"]) * 1000),
            )
            last_user_stop["t"] = 0.0
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
                    # 外呼必须等接通再返回：若为 false，开场白会在接通前播进空房间，
                    # 客户接起只听到半截或沉默（livekit-poc main.py 同样写死 True）。
                    wait_until_answered=True,
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

    # 开场白：优先固定录音（接通即播、消除 2026-07-09 真机复现的 7.5s 空窗），
    # 无录音才退回 generate_reply 兜底（DashScope 对空上下文 response.create 静默
    # 忽略，兜底模式下 AI 可能等客户先开口才响应）。
    call_started["t"] = time.monotonic()
    opening_player: _OpeningPlayer | None = None
    if os.path.exists(_OPENING_WAV_PATH):
        try:
            opening_player = _OpeningPlayer(ctx.room, _OPENING_WAV_PATH)
        except Exception as exc:  # noqa: BLE001
            _emit_livekit_event("opening_wav_load_error", callId=action_id, roomName=room_name, error=str(exc))
    if opening_player is not None:
        _llm_for_opening = getattr(session, "llm", None) or getattr(session, "_llm", None)
        _rt_for_opening = getattr(_llm_for_opening, "last_session", None)
        if _rt_for_opening is not None:
            try:
                # 客户开口（服务端 VAD speech_started）立即停掉开场白录音
                _rt_for_opening.on("input_speech_started", lambda *_: opening_player.stop())
            except Exception:  # noqa: BLE001
                pass
        asyncio.create_task(opening_player.play())
        _emit_livekit_event(
            "tts_start",
            callId=action_id,
            roomName=room_name,
            provider="livekit_agent",
            text=opening_text,
            detail="播放固定开场白录音（接通即播，可被客户说话打断）。",
        )
    else:
        session.generate_reply(instructions=f"用一句话自然开场，不要多说：{opening_text}")
        _emit_livekit_event(
            "tts_start",
            callId=action_id,
            roomName=room_name,
            provider="livekit_agent",
            text=opening_text,
            detail="未找到开场白录音，退回 generate_reply（可能等客户先开口才响应）。",
        )

    # ---- 意向标记（对齐 bench：AI 问过微信 + 客户同意 => 落库）----
    wechat_ask = {"pending": 0, "ai_text": ""}
    lead_marked = {"v": False}
    _WECHAT_HINTS = ("微信", "加您", "加个微信", "加一下")
    # 判定顺序先拒绝后同意："不对/不是"先被拒绝分支拦住，"对/是的"才能安全进同意词表
    _AGREE_WORDS = ("可以", "行", "好的", "好啊", "嗯", "加吧", "发吧", "就是微信", "是微信",
                    "同意", "没问题", "对", "是的", "对的", "嗯嗯", "方便")
    _REFUSE_WORDS = ("不用", "不加", "别加", "不需要", "不方便", "不行", "不对", "不是")
    # 2026-07-09 真机踩坑：AI 实际道别语是"先不多打扰/拜拜/您先忙"，
    # 只留"不打扰"匹配不上（"不多打扰"不含子串"不打扰"），挂断永不触发
    _FAREWELLS = ("再见", "拜拜", "不打扰", "不多打扰", "您先忙", "生意兴隆")
    lead_path = os.getenv("INTENT_LEADS_PATH", "intent_leads.jsonl")

    def _mark_lead(customer_text: str) -> None:
        if lead_marked["v"]:
            return
        lead_marked["v"] = True
        record = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "phone": dial_phone,
            "room": room_name,
            "level": "A",
            "reason": "客户同意加微信",
            "ai_ask": wechat_ask["ai_text"][:120],
            "customer_reply": customer_text[:120],
        }
        try:
            with open(lead_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            _emit_livekit_event("intent_lead_write_error", callId=action_id, roomName=room_name, error=str(exc))
        _emit_livekit_event(
            "intent_lead_marked",
            callId=action_id,
            roomName=room_name,
            phone=_masked_phone(dial_phone),
            customerReply=customer_text[:80],
            detail="客户同意加微信，已写入意向池。",
        )

    def _on_user_transcript(text: str) -> None:
        # 挂适配器 on_user_transcript（DashScope 转写完成事件，带 transcript）。
        # 不用 conversation_item_added——user 事件在转写完成前发出，常拿到空文本。
        text = (text or "").strip()
        if not text:
            return
        last_activity["t"] = time.monotonic()
        # 实时字幕流：客户侧转写推给前端实时监听页
        _emit_livekit_event(
            "user_transcript",
            callId=action_id,
            roomName=room_name,
            text=text[:200],
            detail="客户说话（实时转写）",
        )
        if wechat_ask["pending"] > 0:
            if any(w in text for w in _REFUSE_WORDS):
                wechat_ask["pending"] = 0
            elif any(w in text for w in _AGREE_WORDS):
                _mark_lead(text)
                wechat_ask["pending"] = 0
            else:
                wechat_ask["pending"] -= 1

    _llm_obj = getattr(session, "llm", None) or getattr(session, "_llm", None)
    _rt = getattr(_llm_obj, "last_session", None)
    if _rt is not None:
        _rt.on_user_transcript = _on_user_transcript

    @session.on("conversation_item_added")
    def _on_item(ev: Any) -> None:
        item = getattr(ev, "item", None)
        role = str(getattr(item, "role", ""))
        text = str(getattr(item, "text_content", "") or "")
        if role != "assistant" or not text:
            return
        # 实时字幕流：AI 侧回复推给前端实时监听页
        _emit_livekit_event(
            "ai_transcript",
            callId=action_id,
            roomName=room_name,
            text=text[:200],
            detail="AI 回复（实时转写）",
        )
        if any(w in text for w in _WECHAT_HINTS):
            wechat_ask["pending"] = 2  # 给客户 2 轮回应窗口
            wechat_ask["ai_text"] = text
        if any(w in text for w in _FAREWELLS):
            # 保护：接通 20 秒内不因道别语挂断（防模型口滑/话术污染误触发）
            if call_started["t"] and time.monotonic() - call_started["t"] < 20.0:
                return
            asyncio.create_task(_hangup("AI 道别", delay=4.0))

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

    # 看门狗：2s 一查，静默超时 + 硬上限（道别挂断由 _on_item 异步触发）
    idle_hangup_seconds = float(os.getenv("LIVEKIT_IDLE_HANGUP_SECONDS", "25"))
    start_t = time.monotonic()
    while not done.is_set():
        try:
            await asyncio.wait_for(done.wait(), timeout=2.0)
            break
        except asyncio.TimeoutError:
            pass
        if time.monotonic() - start_t > _MAX_CALL_SECONDS:
            _emit_livekit_event(
                "livekit_call_timeout",
                callId=action_id,
                roomName=room_name,
                limitSeconds=_MAX_CALL_SECONDS,
                detail="到达单通电话硬上限，主动收尾（防语音信箱/静默线路空耗计费）。",
            )
            await _hangup(f"硬上限 {_MAX_CALL_SECONDS}s")
            ctx.shutdown("max_call_seconds_reached")
            break
        if time.monotonic() - last_activity["t"] > idle_hangup_seconds:
            await _hangup(f"双方静默超 {idle_hangup_seconds:.0f}s")
            ctx.shutdown("idle_timeout")
            break
    await done.wait()


def _build_agent_session(*, inference: Any, agent_mode: str, instructions: str = "") -> Any:
    from livekit.agents import APIConnectOptions

    if agent_mode == "inference":
        return _build_inference_agent_session(inference)
    return _build_openai_realtime_agent_session(
        connect_options=APIConnectOptions(max_retry=2, retry_interval=0.8, timeout=8.0),
        instructions=instructions,
    )


def _build_openai_realtime_agent_session(*, connect_options: Any, instructions: str = "") -> Any:
    from livekit.agents import AgentSession

    runtime_config = get_runtime_ai_config()
    base_url = (
        settings.livekit_openai_realtime_base_url.strip()
        or os.getenv("LIVEKIT_OPENAI_REALTIME_BASE_URL", "").strip()
        or runtime_config.dashscope_omni_realtime_url.strip()
    )
    if _looks_like_dashscope_realtime_url(base_url):
        # 【WORKER_MIGRATION 必改2】DashScope 分支不走 openai 插件——协议有三个暗坑
        # 插件不处理（空上下文 response.create 被静默忽略、大音频帧被丢、modalities
        # 声明时序），2026-07-08 真机验证版适配器 app/tools/qwen_omni_realtime.py
        # 已内置全部修复。AgentSession 保持裸构造，与验证形态（livekit-poc/agent/
        # main.py）完全一致，不叠加未经真机测试的 pipeline 参数组合。
        # 判停毫秒用环境变量 VAD_SILENCE_MS 调（适配器内部读取，默认 400）。
        from app.tools.qwen_omni_realtime import QwenOmniRealtimeModel

        api_key = (
            settings.livekit_openai_realtime_api_key.strip()
            or os.getenv("LIVEKIT_OPENAI_REALTIME_API_KEY", "").strip()
            or runtime_config.dashscope_api_key.strip()
            or os.getenv("DASHSCOPE_API_KEY", "").strip()
            or settings.dashscope_api_key.strip()
        )
        # 默认值必须是真机验证过的组合 qwen3-omni-flash-realtime + Cherry，
        # 不要换成未验证的模型串/音色（原 qwen3.5-omni-plus-realtime/Serena 未经真机验证）。
        model = runtime_config.dashscope_omni_realtime_model.strip() or settings.livekit_openai_realtime_model.strip() or "qwen3-omni-flash-realtime"
        voice = runtime_config.dashscope_omni_realtime_voice.strip() or settings.livekit_openai_realtime_voice.strip() or "Cherry"
        return AgentSession(
            llm=QwenOmniRealtimeModel(
                model=model,
                api_key=api_key,
                voice=voice,
                base_url=base_url or "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
                instructions=instructions,
            )
        )

    # OpenAI 官方端点：插件对自家协议没问题，保留原实现。
    from livekit.plugins import openai

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
        "商家名称整通电话最多说一次（开场提一下即可），之后一律用「您」称呼对方，禁止每句话重复商家名。"
        "同一个问题整通电话最多问一次（比如「想看案例还是看费用」），客户没有正面回答就换个角度说，或直接推进到加微信，禁止原样复读。"
        "客户报出或更正微信号/手机号后，必须复述最新号码请客户确认；客户再次补充或更正时，以最新说法为准重新复述确认，号码未经客户确认不得道别。"
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
