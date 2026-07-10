from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

from app.core.config import settings
from app.services.livekit_outbound import _emit_livekit_event, _masked_phone
from app.services.realtime_intent_capture import record_realtime_wechat_signal
from app.services.realtime_outbound import _classify_intent
from app.services.runtime_ai_config import get_runtime_ai_config
from app.services.realtime_sales_playbook import (
    VIDEO_GROUP_BUYING_OPENING_A,
    build_video_group_buying_sales_instructions,
    classify_realtime_call_input,
)
from app.services.realtime_sales_state import SalesStateMachine


load_dotenv()

# 单通电话硬上限秒数：防止对语音信箱/静默线路无限烧钱（对齐 livekit-poc/agent/main.py）。
_MAX_CALL_SECONDS = int(os.getenv("LIVEKIT_MAX_CALL_SECONDS", "300"))

# AI 结束语匹配：说完这些话且客户没有再开口，就主动挂断（解决"AI 说完再见不挂机"）。
_FAREWELL_PATTERN = re.compile(
    r"再见|拜拜|微信见|回头见|下次再聊|有空再聊|"
    r"不多打扰|不打扰(?:了|您)?|感谢接听|您先忙|生意兴隆"
)
# 结束语播完后留给客户反悔的窗口秒数，窗口内客户开口则取消挂机继续对话。
_HANGUP_GRACE_SECONDS = float(os.getenv("LIVEKIT_HANGUP_GRACE_SECONDS", "1.5"))

_QWEN_OMNI_MODE = "omni"
_ACTIVE_AGENT_STATES = {"speaking", "thinking"}
_SILENCE_PROBE_WAIT_SECONDS = float(os.getenv("LIVEKIT_SILENCE_PROBE_WAIT_SECONDS", "8"))
_SILENCE_PROBE_INSTRUCTIONS = (
    (
        "关心、轻柔",
        "用关心、轻柔的口气，语速稍慢，每个字都说清楚。"
        "只说这一句，不要添加其他内容：老板，您还在吗？",
    ),
    (
        "稍提高音量、仍然礼貌",
        "用稍微提高音量、仍然礼貌的口气，停顿自然，咬字清楚。"
        "只说这一句，不要添加其他内容：喂，老板，您能听到我说话吗？",
    ),
    (
        "耐心、郑重地最后确认",
        "用耐心、郑重地最后确认的口气，放慢语速，不吞字。"
        "只说这一句，不要添加其他内容：老板，我最后确认一下，您还在听吗？",
    ),
)


def _conversation_turn_in_progress(agent_state: str, user_state: str) -> bool:
    return agent_state in _ACTIVE_AGENT_STATES or user_state == "speaking"


def _assistant_turn_expects_reply(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean or _FAREWELL_PATTERN.search(clean):
        return False
    return bool(
        re.search(r"[？?](?:[\s”’'\"]*)$", clean)
        or re.search(r"(?:吗|呢|行不行|可不可以)(?:[。！？!?\s”’'\"]*)$", clean)
    )


def _normalize_agent_mode(value: str) -> str:
    # 生产外呼统一使用 Qwen Omni。即使历史 dispatch metadata 仍携带
    # pipeline_clone，worker 也不得在通话中切换到 ASR -> LLM -> TTS 路线。
    del value
    return _QWEN_OMNI_MODE


class _RtpSilenceKeepalive:
    """Publish silence continuously so the SIP mixer never runs out of RTP."""

    def __init__(self, room: Any) -> None:
        self._room = room
        self._source: Any = None
        self._publication: Any = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.frames_sent = 0

    async def start(self) -> None:
        from livekit import rtc

        self._source = rtc.AudioSource(24000, 1)
        track = rtc.LocalAudioTrack.create_audio_track("rtp_keepalive", self._source)
        self._publication = await self._room.local_participant.publish_track(
            track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_UNKNOWN),
        )
        self._task = asyncio.create_task(self._run(), name="livekit_rtp_silence_keepalive")

    async def _run(self) -> None:
        from livekit import rtc

        frame = rtc.AudioFrame(
            data=b"\x00" * 960,
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=480,
        )
        loop = asyncio.get_running_loop()
        next_frame_at = loop.time()
        while not self._stop.is_set():
            await self._source.capture_frame(frame)
            self.frames_sent += 1
            next_frame_at += 0.02
            now = loop.time()
            if next_frame_at < now - 0.1:
                next_frame_at = now
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0.001, next_frame_at - now))
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:  # noqa: BLE001
                pass
            self._task = None
        if self._publication is not None:
            try:
                await asyncio.wait_for(
                    self._room.local_participant.unpublish_track(self._publication.sid),
                    timeout=2.0,
                )
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass
            self._publication = None
        if self._source is not None:
            try:
                await asyncio.wait_for(self._source.aclose(), timeout=2.0)
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass
            self._source = None


async def entrypoint(ctx: Any) -> None:
    from livekit import api
    from livekit.agents import Agent, AgentSession, inference, room_io

    metadata = _parse_metadata(getattr(ctx.job, "metadata", "") or "{}")
    action_id = str(metadata.get("actionId") or getattr(ctx.job, "id", "") or "")
    room_name = str(metadata.get("roomName") or getattr(ctx.room, "name", "") or "")
    participant_identity = str(metadata.get("participantIdentity") or "").strip()
    dial_phone = str(metadata.get("dialPhone") or metadata.get("phone") or "")
    batch_task_id = str(metadata.get("taskId") or "").strip() or None
    batch_lead_id = str(metadata.get("leadId") or "").strip() or None
    trunk_id = str(metadata.get("sipOutboundTrunkId") or settings.livekit_sip_outbound_trunk_id).strip()
    merchant_name = str(metadata.get("merchantName") or "您的门店")
    opening_text = str(metadata.get("openingText") or VIDEO_GROUP_BUYING_OPENING_A)
    requested_agent_mode = str(metadata.get("agentMode") or settings.livekit_agent_mode or _QWEN_OMNI_MODE)
    agent_mode = _normalize_agent_mode(requested_agent_mode)
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

    rtp_keepalive = _RtpSilenceKeepalive(ctx.room)
    try:
        await rtp_keepalive.start()
    except Exception as exc:  # noqa: BLE001
        _emit_livekit_event(
            "rtp_keepalive_error",
            callId=action_id,
            roomName=room_name,
            error=str(exc),
            detail="RTP 静音保活轨发布失败，为避免 media-timeout，本通不继续建呼。",
        )
        ctx.shutdown("rtp_keepalive_start_failed")
        return

    async def _stop_rtp_keepalive(reason: str = "") -> None:
        await rtp_keepalive.stop()
        _emit_livekit_event(
            "rtp_keepalive_stopped",
            callId=action_id,
            roomName=room_name,
            reason=reason,
            frames=rtp_keepalive.frames_sent,
        )

    ctx.add_shutdown_callback(_stop_rtp_keepalive)
    _emit_livekit_event(
        "rtp_keepalive_started",
        callId=action_id,
        roomName=room_name,
        sampleRate=24000,
        frameMs=20,
        detail="已发布全程静音保活轨，持续保持 SIP RTP 媒体流。",
    )

    instructions = _build_agent_instructions(merchant_name=merchant_name)
    session = _build_agent_session(inference=inference, agent_mode=agent_mode, instructions=instructions)
    agent = Agent(instructions=instructions)

    for component_name, component in (("stt", session.stt), ("llm", session.llm), ("tts", session.tts)):
        if component is None:
            continue

        def _on_metrics(metrics: Any, *, name: str = component_name, target_component: Any = component) -> None:
            payload: dict[str, Any] = {
                "callId": action_id,
                "roomName": room_name,
                "component": name,
                "provider": str(getattr(target_component, "provider", "")),
                "model": str(getattr(target_component, "model", "")),
            }
            for source, target in (
                ("ttfb", "ttfbMs"),
                ("duration", "durationMs"),
                ("audio_duration", "audioDurationMs"),
            ):
                value = getattr(metrics, source, None)
                if isinstance(value, (int, float)) and value >= 0:
                    payload[target] = int(value * 1000)
            _emit_livekit_event("pipeline_component_metrics", **payload)

        try:
            component.on("metrics_collected", _on_metrics)
        except Exception:  # noqa: BLE001
            pass

    # 转向延迟打点（对齐 livekit-poc/agent/main.py）：客户停→AI出声的真实延迟，
    # 待办6 两线路 A/B 对比就看这个事件的 P50/P95，没有它对比无数据可用。
    last_user_stop = {"t": 0.0}

    # ---- 三层挂断基础设施（对齐 bench_agent_reference.py：道别/静默/硬上限）----
    hangup_flag = {"v": False}
    hangup_state: dict[str, Any] = {"pending": False, "task": None}
    last_agent_state = {"v": ""}
    last_user_state = {"v": ""}
    silence_probe_state: dict[str, Any] = {
        "attempts": 0,
        "eligible": False,
        "waiting_since": 0.0,
        "prompt_in_flight": False,
    }
    call_started = {"t": 0.0}
    done = asyncio.Event()

    def _reset_silence_probe() -> None:
        silence_probe_state.update(
            attempts=0,
            eligible=False,
            waiting_since=0.0,
            prompt_in_flight=False,
        )

    def _arm_silence_probe_wait() -> None:
        if not silence_probe_state["eligible"] or hangup_state["pending"]:
            return
        if _conversation_turn_in_progress(last_agent_state["v"], last_user_state["v"]):
            return
        silence_probe_state["waiting_since"] = time.monotonic()

    def _request_next_silence_probe() -> None:
        attempt = int(silence_probe_state["attempts"]) + 1
        tone, probe_instruction = _SILENCE_PROBE_INSTRUCTIONS[attempt - 1]
        silence_probe_state.update(
            attempts=attempt,
            eligible=True,
            waiting_since=time.monotonic(),
            prompt_in_flight=True,
        )
        try:
            session.generate_reply(instructions=probe_instruction)
            _emit_livekit_event(
                "livekit_silence_probe",
                callId=action_id,
                roomName=room_name,
                attempt=attempt,
                tone=tone,
                waitSeconds=_SILENCE_PROBE_WAIT_SECONDS,
                detail=f"客户未回应，Qwen Omni 正在进行第 {attempt} 次在线确认。",
            )
        except Exception as exc:  # noqa: BLE001
            silence_probe_state["prompt_in_flight"] = False
            _emit_livekit_event(
                "livekit_silence_probe_error",
                callId=action_id,
                roomName=room_name,
                attempt=attempt,
                error=str(exc),
            )

    async def _hangup(
        reason: str,
        delay: float = 0.0,
        *,
        event_name: str = "livekit_auto_hangup",
        error_event_name: str = "livekit_auto_hangup_error",
        detail: str = "",
        shutdown_reason: str = "",
        remove_participant_first: bool = False,
    ) -> bool:
        if hangup_flag["v"]:
            return False
        hangup_flag["v"] = True
        if delay:
            await asyncio.sleep(delay)
        event_payload: dict[str, Any] = {
            "callId": action_id,
            "roomName": room_name,
            "participantIdentity": participant_identity,
            "reason": reason,
        }
        if detail:
            event_payload["detail"] = detail
        _emit_livekit_event(event_name, **event_payload)
        success = True
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
                if remove_participant_first and participant_identity:
                    try:
                        await lkapi.room.remove_participant(
                            api.RoomParticipantIdentity(room=room_name, identity=participant_identity)
                        )
                    except Exception:  # noqa: BLE001
                        await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))
                else:
                    await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))
            finally:
                await lkapi.aclose()
        except Exception as exc:  # noqa: BLE001
            success = False
            _emit_livekit_event(
                error_event_name,
                callId=action_id,
                roomName=room_name,
                participantIdentity=participant_identity,
                error=str(exc),
                detail="主动挂断失败，等待客户侧挂机或通话上限收尾。",
            )
        if shutdown_reason and success:
            done.set()
            ctx.shutdown(shutdown_reason)
        return success

    def _cancel_farewell_hangup() -> None:
        hangup_state["pending"] = False
        task = hangup_state["task"]
        if task is not None:
            task.cancel()
        hangup_state["task"] = None

    async def _hangup_after_grace() -> None:
        try:
            await asyncio.sleep(_HANGUP_GRACE_SECONDS)
            if not hangup_state["pending"]:
                return
            await _hangup(
                "AI 道别",
                event_name="livekit_agent_hangup",
                error_event_name="livekit_agent_hangup_error",
                detail="AI 结束语播放完毕且客户未再说话，主动挂断电话。",
                shutdown_reason="agent_hangup_after_farewell",
                remove_participant_first=True,
            )
        except asyncio.CancelledError:
            return
        finally:
            hangup_state["pending"] = False
            hangup_state["task"] = None

    def _arm_farewell_hangup(text: str) -> None:
        if not _FAREWELL_PATTERN.search(text):
            return
        # 保护：接通 20 秒内不因道别语挂断（防模型口滑/话术污染误触发）
        if call_started["t"] and time.monotonic() - call_started["t"] < 20.0:
            return
        hangup_state["pending"] = True
        if last_agent_state["v"] in {"listening", "idle"} and hangup_state["task"] is None:
            hangup_state["task"] = asyncio.create_task(_hangup_after_grace())

    @session.on("user_state_changed")
    def _on_user_state(ev: Any) -> None:
        new_state = str(getattr(ev, "new_state", ""))
        last_user_state["v"] = new_state
        if new_state == "speaking":
            _cancel_farewell_hangup()
            _reset_silence_probe()
        if new_state == "listening":
            last_user_stop["t"] = time.perf_counter()

    @session.on("agent_state_changed")
    def _on_agent_state(ev: Any) -> None:
        new_state = str(getattr(ev, "new_state", ""))
        last_agent_state["v"] = new_state
        if new_state == "speaking" and last_user_stop["t"]:
            _emit_livekit_event(
                "turn_latency",
                callId=action_id,
                roomName=room_name,
                latencyMs=int((time.perf_counter() - last_user_stop["t"]) * 1000),
            )
            last_user_stop["t"] = 0.0
        if new_state in {"listening", "idle"} and hangup_state["pending"] and hangup_state["task"] is None:
            hangup_state["task"] = asyncio.create_task(_hangup_after_grace())
        if new_state in {"listening", "idle"}:
            _arm_silence_probe_wait()

    @session.on("close")
    def _on_session_close(ev: Any) -> None:
        reason = str(getattr(ev, "reason", "") or "agent_session_closed")
        _emit_livekit_event(
            "livekit_agent_session_closed",
            callId=action_id,
            roomName=room_name,
            reason=reason,
        )
        if not done.is_set():
            done.set()
            ctx.shutdown(reason)

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

    # 通话落库状态：必须在 customer_joined 回调（下方写 joined_at）之前定义，
    # 否则 Python 视 call_state 为整函数局部变量、读取时 UnboundLocalError。
    conversation_log: list[str] = []
    call_state: dict[str, Any] = {
        "joined_at": 0.0,
        "refused": False,
        "persisted": False,
        "intent_level": "",
        "intent_reason": "",
        "wechat_id": "",
        "wechat_is_phone": False,
    }
    sales_fsm = SalesStateMachine()
    transcript_dedupe = {"text": "", "at": 0.0}
    persistence_tasks: set[asyncio.Task[Any]] = set()
    context_phone = str(metadata.get("phone") or dial_phone).strip()
    realtime_context = {
        "phone": context_phone,
        "merchantName": merchant_name,
        "taskId": batch_task_id or "",
        "leadId": batch_lead_id or "",
    }
    interest_intents = {"价格异议", "效果询问", "合作咨询", "加微信/发资料"}
    interest_markers = (
        "想了解",
        "有兴趣",
        "可以做",
        "想做",
        "怎么合作",
        "怎么开通",
        "发我",
        "发过来",
        "加我微信",
        "你加我",
    )
    rejection_markers = ("不需要", "不用了", "没兴趣", "不感兴趣", "别打", "别联系", "拉黑", "投诉")

    def _on_background_task_done(task: asyncio.Task[Any]) -> None:
        persistence_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _emit_livekit_event(
                "livekit_background_task_error",
                callId=action_id,
                roomName=room_name,
                error=str(exc),
            )

    def _track_persistence_task(coro: Any) -> None:
        task = asyncio.create_task(coro)
        persistence_tasks.add(task)
        task.add_done_callback(_on_background_task_done)

    def _set_final_intent(text: str, intent: str) -> None:
        if intent == "明确拒绝" or any(marker in text for marker in rejection_markers):
            call_state["intent_level"] = "D"
            call_state["intent_reason"] = f"客户最后明确表示无意向：{text[:120]}"
            call_state["refused"] = True
            return
        if intent in interest_intents or any(marker in text for marker in interest_markers):
            call_state["intent_level"] = "A" if intent == "加微信/发资料" else "B"
            call_state["intent_reason"] = f"客户最后表示有意向：{text[:120]}"
            call_state["refused"] = False

    async def _save_wechat_capture(
        customer_text: str,
        signal: str,
        *,
        wechat_id: str,
        wechat_is_phone: bool,
        summary: str,
    ) -> None:
        try:
            result = await asyncio.to_thread(
                record_realtime_wechat_signal,
                call_id=action_id,
                context=realtime_context,
                text=customer_text,
                signal=signal,
                source="livekit_qwen_omni",
                wechat_id=wechat_id,
                wechat_is_phone=wechat_is_phone,
                summary=summary,
            )
            _emit_livekit_event(
                "realtime_wechat_saved",
                callId=action_id,
                roomName=room_name,
                wechatId=wechat_id,
                wechatIsPhone=wechat_is_phone,
                customerId=str((result or {}).get("customerId") or ""),
                detail=(
                    "客户确认当前手机号就是微信，已写入意向库。"
                    if wechat_is_phone
                    else "客户口述了不同于手机号的微信号，已写入意向库。"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _emit_livekit_event(
                "realtime_wechat_save_error",
                callId=action_id,
                roomName=room_name,
                wechatId=wechat_id,
                error=str(exc),
                detail="微信号实时写库失败；通话结束时仍会随转写和最终意向一起落库。",
            )

    def _refresh_omni_instructions(action: str = "", reply_hint: str = "") -> None:
        llm_obj = getattr(session, "llm", None) or getattr(session, "_llm", None)
        realtime_session = getattr(llm_obj, "last_session", None)
        if realtime_session is None:
            return
        state_instruction = sales_fsm.get_stage_instruction()
        action_instruction = ""
        if action and reply_hint:
            action_instruction = f"\n当前微信收口动作={action}。下一句按这个含义回复：{reply_hint}"
        _track_persistence_task(realtime_session.update_instructions(f"{instructions}\n{state_instruction}{action_instruction}"))

    def _on_user_transcript(text: str) -> None:
        # DashScope 的转写完成回调和 LiveKit conversation 事件可能同时到达，
        # 短窗口去重后再判定意向，避免一句客户话被记两次。
        text = " ".join(str(text or "").strip().split())
        if not text:
            return
        now = time.monotonic()
        fingerprint = re.sub(r"\s+", "", text)
        if transcript_dedupe["text"] == fingerprint and now - transcript_dedupe["at"] < 0.8:
            return
        transcript_dedupe.update(text=fingerprint, at=now)
        _reset_silence_probe()
        conversation_log.append(f"客户：{text}")
        intent, _node = _classify_intent(text)
        signal = classify_realtime_call_input(text)
        sales_fsm.update(text, intent, signal)
        _set_final_intent(text, intent)
        wechat_result = sales_fsm.handle_wechat_closing_turn(text, intent, phone=context_phone)
        if wechat_result is not None:
            _emit_livekit_event(
                "wechat_closing_state",
                callId=action_id,
                roomName=room_name,
                action=wechat_result.action,
                record=wechat_result.record,
                detail="Qwen Omni 微信收口状态已更新。",
            )
            if wechat_result.record and wechat_result.wechat_id:
                call_state["intent_level"] = "A"
                call_state["intent_reason"] = wechat_result.summary or "客户同意加微信"
                call_state["refused"] = False
                call_state["wechat_id"] = wechat_result.wechat_id
                call_state["wechat_is_phone"] = wechat_result.wechat_is_phone
                _track_persistence_task(
                    _save_wechat_capture(
                        text,
                        signal,
                        wechat_id=wechat_result.wechat_id,
                        wechat_is_phone=wechat_result.wechat_is_phone,
                        summary=wechat_result.summary,
                    )
                )
            if wechat_result.action:
                _refresh_omni_instructions(wechat_result.action, wechat_result.reply)
        _emit_livekit_event(
            "user_transcript",
            callId=action_id,
            roomName=room_name,
            text=text[:200],
            intent=intent,
            finalIntentLevel=call_state["intent_level"] or "C",
            detail="客户说话（实时转写）",
        )

    llm_obj = getattr(session, "llm", None) or getattr(session, "_llm", None)
    realtime_session = getattr(llm_obj, "last_session", None)
    if realtime_session is not None:
        realtime_session.on_user_transcript = _on_user_transcript

    @session.on("conversation_item_added")
    def _on_item(ev: Any) -> None:
        item = getattr(ev, "item", None)
        role = str(getattr(item, "role", ""))
        text = str(getattr(item, "text_content", "") or "").strip()
        if not text:
            return
        if role == "user":
            _on_user_transcript(text)
            return
        if role != "assistant":
            return
        was_silence_probe = bool(silence_probe_state["prompt_in_flight"])
        silence_probe_state["prompt_in_flight"] = False
        silence_probe_state["eligible"] = (
            (was_silence_probe and not _FAREWELL_PATTERN.search(text))
            or _assistant_turn_expects_reply(text)
        )
        silence_probe_state["waiting_since"] = 0.0
        if silence_probe_state["eligible"]:
            _arm_silence_probe_wait()
        elif not was_silence_probe:
            silence_probe_state["attempts"] = 0
        conversation_log.append(f"AI：{text}")
        sales_fsm.record_assistant_reply(text)
        _emit_livekit_event(
            "ai_transcript",
            callId=action_id,
            roomName=room_name,
            text=text[:200],
            detail="Qwen Omni Plus 回复（实时转写）",
        )
        _arm_farewell_hangup(text)

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
        call_state["joined_at"] = time.monotonic()
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

    # 开场和后续每一句都由同一 Qwen Omni Plus 实时会话生成。
    # 这里不再检查 opening.wav，也不发布任何录音播放轨。
    call_started["t"] = time.monotonic()
    session.generate_reply(
        instructions=(
            "你现在直接向电话里的客户说开场白。语气亲切、明亮、自然，语速适中，"
            "每个字都要说完整，在标点处清楚停顿，不吞字。"
            "只输出下面的开场白本身，不解释、不增删、不改写：\n"
            f"{opening_text}"
        )
    )
    model_name = str(getattr(llm_obj, "_model", "") or "qwen3.5-omni-plus-realtime")
    voice_name = str(getattr(llm_obj, "_voice", "") or "Aiden")
    _emit_livekit_event(
        "tts_start",
        callId=action_id,
        roomName=room_name,
        provider="qwen_omni_realtime",
        model=model_name,
        voice=voice_name,
        text=opening_text,
        detail="开场白由当前 Qwen Omni Plus 实时会话直接生成；未播放固定录音。",
    )

    def _persist_call() -> None:
        """通话结束落库：CallRecord + 线索状态 + 意向池 + 工单 + 勿扰（需求 7.7.7/7.7.9）。"""
        if call_state["persisted"]:
            return
        # wait_until_answered=true：客户 participant 进房 == 电话已接通（含静默接听/语音信箱）
        connected = call_state["joined_at"] > 0
        duration = int(time.monotonic() - call_state["joined_at"]) if call_state["joined_at"] else 0
        final_level = str(call_state["intent_level"] or "")
        if not connected:
            intent_level, outcome, reason = "无效", "未接通", "未接通或无人说话"
        elif final_level in {"A", "B"}:
            intent_level, outcome = final_level, "有意向"
            reason = str(call_state["intent_reason"] or "客户表示愿意继续了解")
        elif final_level == "D":
            intent_level, outcome = "D", "拒绝"
            reason = str(call_state["intent_reason"] or "客户最后明确表示无意向")
        else:
            intent_level, outcome, reason = "C", "已接通", "接通对话，最终意向未确认"
        final_intent_label = "有意向" if intent_level in {"A", "B"} else "无意向" if intent_level == "D" else "未确认"
        final_summary = f"系统：最终客户意向={final_intent_label}（{intent_level}）；依据={reason}"
        if call_state["wechat_id"]:
            wechat_kind = "当前手机号" if call_state["wechat_is_phone"] else "客户口述微信号"
            final_summary += f"；{wechat_kind}={call_state['wechat_id']}"
        persisted_transcript = "\n".join([*conversation_log, final_summary])
        from app.services.livekit_call_persistence import persist_livekit_call_result

        # 落库对连接类异常有限重试（远程 PG 会静默回收空闲连接）；persist 按
        # gateway_call_id 幂等，重试不会重复写。全部失败才落本地 jsonl 兜底防丢数据。
        last_error = ""
        for attempt in range(3):
            try:
                record_id = persist_livekit_call_result(
                    action_id=action_id,
                    phone=dial_phone,
                    merchant_name=merchant_name if merchant_name not in ("您的门店", "单号真实试拨") else "",
                    task_id=batch_task_id,
                    lead_id=batch_lead_id,
                    duration_seconds=duration,
                    connected=connected,
                    intent_level=intent_level,
                    outcome=outcome,
                    transcript=persisted_transcript,
                    intent_reason=reason,
                    refused=intent_level == "D",
                )
                call_state["persisted"] = True  # 仅成功后置位，失败可由下次挂断回调重试
                _emit_livekit_event(
                    "call_record_saved",
                    callId=action_id,
                    roomName=room_name,
                    recordId=record_id or "",
                    intentLevel=intent_level,
                    outcome=outcome,
                    durationSeconds=duration,
                    detail="通话记录已落库（含线索状态/意向池/工单联动）。",
                )
                return
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                time.sleep(1.0 * (attempt + 1))
        # 三次全失败：写本地 outbox 兜底，避免通话数据永久丢失
        try:
            outbox = os.getenv("CALL_OUTBOX_PATH", "call_persist_outbox.jsonl")
            with open(outbox, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "action_id": action_id, "phone": dial_phone, "task_id": batch_task_id,
                    "lead_id": batch_lead_id, "duration": duration, "connected": connected,
                    "intent_level": intent_level, "outcome": outcome, "reason": reason,
                    "refused": intent_level == "D", "transcript": persisted_transcript,
                    "wechat_id": call_state["wechat_id"],
                    "wechat_is_phone": call_state["wechat_is_phone"],
                    "at": datetime.now().isoformat(timespec="seconds"),
                }, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
        _emit_livekit_event("call_record_save_error", callId=action_id, roomName=room_name, error=last_error, detail="落库失败已写本地 outbox 兜底。")

    async def _on_shutdown(reason: str = "") -> None:
        if persistence_tasks:
            await asyncio.gather(*tuple(persistence_tasks), return_exceptions=True)
        await asyncio.to_thread(_persist_call)
        _emit_livekit_event(
            "livekit_agent_shutdown",
            callId=action_id,
            roomName=room_name,
            reason=reason,
        )
        done.set()

    ctx.add_shutdown_callback(_on_shutdown)

    # 看门狗：只保留硬上限和“三次在线确认”，不再因单一静默时长直接挂断。
    start_t = time.monotonic()
    while not done.is_set():
        try:
            await asyncio.wait_for(done.wait(), timeout=1.0)
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
            ended = await _hangup(
                f"硬上限 {_MAX_CALL_SECONDS}s",
                shutdown_reason="max_call_seconds_reached",
            )
            if not ended:
                done.set()
                ctx.shutdown("max_call_seconds_reached")
            break
        if _conversation_turn_in_progress(last_agent_state["v"], last_user_state["v"]):
            continue
        if hangup_state["pending"] or not silence_probe_state["eligible"]:
            continue
        waiting_since = float(silence_probe_state["waiting_since"] or 0.0)
        if not waiting_since or time.monotonic() - waiting_since < _SILENCE_PROBE_WAIT_SECONDS:
            continue
        attempts = int(silence_probe_state["attempts"])
        if attempts < len(_SILENCE_PROBE_INSTRUCTIONS):
            _request_next_silence_probe()
            continue
        ended = await _hangup(
            "连续三次确认客户均无回应",
            event_name="livekit_no_response_hangup",
            error_event_name="livekit_no_response_hangup_error",
            detail="AI 完整问询后已用三种不同口气确认客户是否在线，仍无任何回应，现主动挂断。",
            shutdown_reason="customer_no_response_after_three_probes",
            remove_participant_first=True,
        )
        if not ended:
            done.set()
            ctx.shutdown("customer_no_response_after_three_probes")
        break
    await done.wait()


def _build_agent_session(*, inference: Any, agent_mode: str, instructions: str = "") -> Any:
    # 无论历史配置或 dispatch metadata 传入什么，正式 worker 只构建
    # Qwen Omni 实时会话；不存在通话中切入 Pipeline 的路径。
    del inference, agent_mode
    return _build_qwen_omni_agent_session(instructions=instructions)


def _build_qwen_omni_agent_session(*, instructions: str = "") -> Any:
    from livekit.agents import AgentSession

    from app.tools.qwen_omni_realtime import QwenOmniRealtimeModel

    runtime_config = get_runtime_ai_config()
    base_url = runtime_config.dashscope_omni_realtime_url.strip() or (
        "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
    )
    api_key = (
        settings.livekit_openai_realtime_api_key.strip()
        or os.getenv("LIVEKIT_OPENAI_REALTIME_API_KEY", "").strip()
        or runtime_config.dashscope_api_key.strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
        or settings.dashscope_api_key.strip()
    )
    # 当前生产组合固定为 Qwen 3.5 Omni Plus + Aiden，开场和后续共用。
    # 不读取历史 flash/Cherry/OpenAI 覆盖，避免老配置在重启后切路。
    return AgentSession(
        llm=QwenOmniRealtimeModel(
            model="qwen3.5-omni-plus-realtime",
            api_key=api_key,
            voice="Aiden",
            base_url=base_url,
            instructions=instructions,
        )
    )


def _build_pipeline_clone_agent_session(inference: Any) -> Any:
    from livekit.agents import AgentSession
    from livekit.plugins import openai

    from app.tools.livekit_cosyvoice_tts import CosyVoiceTTS
    from app.tools.livekit_dashscope_stt import DashScopeSTT

    runtime_config = get_runtime_ai_config()
    if not runtime_config.dashscope_api_key.strip():
        raise RuntimeError("Pipeline clone requires a DashScope API key")
    if not runtime_config.realtime_tts_voice_id.strip():
        raise RuntimeError("Pipeline clone requires a configured clone voice id")

    asr_model = runtime_config.realtime_asr_model.strip()
    if not asr_model.startswith("paraformer-realtime"):
        asr_model = "paraformer-realtime-8k-v2"

    if runtime_config.deepseek_api_key.strip():
        llm_model = runtime_config.deepseek_chat_model.strip() or "deepseek-chat"
        llm_base_url = runtime_config.deepseek_base_url.strip() or "https://api.deepseek.com"
        llm_api_key = runtime_config.deepseek_api_key.strip()
    else:
        llm_model = os.getenv("LIVEKIT_PIPELINE_LLM_MODEL", "qwen-flash").strip() or "qwen-flash"
        llm_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        llm_api_key = runtime_config.dashscope_api_key.strip()

    return AgentSession(
        stt=DashScopeSTT(
            api_key=runtime_config.dashscope_api_key,
            model=asr_model,
            workspace=runtime_config.dashscope_workspace,
        ),
        llm=openai.LLM(
            model=llm_model,
            api_key=llm_api_key,
            base_url=llm_base_url,
            temperature=0.35,
        ),
        tts=CosyVoiceTTS(
            api_key=runtime_config.dashscope_api_key,
            model=runtime_config.dashscope_tts_model or "cosyvoice-v3.5-flash",
            voice_id=runtime_config.realtime_tts_voice_id,
            workspace=runtime_config.dashscope_workspace,
        ),
        vad=inference.VAD(model="silero", min_speech_duration=0.05, min_silence_duration=0.3),
        allow_interruptions=True,
        min_interruption_duration=0.12,
        min_interruption_words=1,
        min_endpointing_delay=0.14,
        max_endpointing_delay=0.7,
        preemptive_generation=True,
        user_away_timeout=20.0,
    )


def _build_agent_instructions(*, merchant_name: str) -> str:
    base = build_video_group_buying_sales_instructions(merchant_name)
    return (
        f"{base}\n"
        "LiveKit 实时电话规则：客户说话或插话时立刻停下听；不要解释打断机制。"
        "回复要像日常外呼，短、自然、有亲和力；每次只解决一个问题，最多两个短句。"
        "咬字要准确完整，语速适中，句号和逗号处自然停顿，不吞字、不抢话、不把多个要点连成长段。"
        "开场亲切明亮；讲解稳定有条理；异议处理放缓且理解；费用口径坚定不生硬；微信收口友好不催促；拒绝收尾平和尊重。"
        "同一句话不要重复超过一遍；客户没听清时换一种更短的说法。"
        "这通电话的最终目标是确认客户是否有意向继续了解。"
        "确认有意向后，问客户方不方便加个微信，我们在微信上继续聊。"
        "客户同意加微信后必须确认当前手机号是不是微信；如果是，就明确记录为当前手机号可加微信；如果不是，就问微信号并复述确认。"
        "商家名称整通电话最多说一次（开场提一下即可），之后一律用「您」称呼对方，禁止每句话重复商家名。"
        "同一个问题整通电话最多问一次（比如「想看案例还是看门店方案」），客户没有正面回答就换个角度说，或直接推进到加微信，禁止原样复读。"
        "客户报出或更正微信号/手机号后，必须复述最新号码请客户确认；客户再次补充或更正时，以最新说法为准重新复述确认，号码未经客户确认不得道别。"
        "客户明确说「再见」「拜拜」或表示要结束通话时，只用一句包含「再见」的话礼貌道别，不再提问或延展话题。"
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
