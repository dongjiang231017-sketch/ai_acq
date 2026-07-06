from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


TERMINAL_EVENT_TYPES = {
    "call_closed",
    "call_disconnected",
    "call_error",
    "hangup_frame",
    "voicemail_detected",
    "call_screening_hangup_timeout",
    "no_response_hangup_timeout",
}


@dataclass(frozen=True)
class RealtimeCallState:
    call_id: str | None
    state: str
    label: str
    status: str
    close_reason: str | None
    can_auto_close: bool
    auto_close_scheduled: bool
    human_speech_confirmed: bool
    call_screening_detected: bool
    voicemail_detected: bool
    silence_detected: bool
    no_response_detected: bool
    hangup_detected: bool
    ai_speech_confirmed: bool
    customer_speech_confirmed: bool
    interruption_detected: bool
    turn_taking_status: str
    latest_turn_response_ms: int | None
    current_phase: str
    phase_label: str
    turn_action: str
    latency_breakdown: dict[str, int | None]
    last_customer_text: str | None
    last_ai_reply: str | None
    last_event_at: str | None
    issues: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "callId": self.call_id,
            "state": self.state,
            "label": self.label,
            "status": self.status,
            "closeReason": self.close_reason,
            "canAutoClose": self.can_auto_close,
            "autoCloseScheduled": self.auto_close_scheduled,
            "humanSpeechConfirmed": self.human_speech_confirmed,
            "callScreeningDetected": self.call_screening_detected,
            "voicemailDetected": self.voicemail_detected,
            "silenceDetected": self.silence_detected,
            "noResponseDetected": self.no_response_detected,
            "hangupDetected": self.hangup_detected,
            "aiSpeechConfirmed": self.ai_speech_confirmed,
            "customerSpeechConfirmed": self.customer_speech_confirmed,
            "interruptionDetected": self.interruption_detected,
            "turnTakingStatus": self.turn_taking_status,
            "latestTurnResponseMs": self.latest_turn_response_ms,
            "currentPhase": self.current_phase,
            "phaseLabel": self.phase_label,
            "turnAction": self.turn_action,
            "latencyBreakdown": self.latency_breakdown,
            "lastCustomerText": self.last_customer_text,
            "lastAiReply": self.last_ai_reply,
            "lastEventAt": self.last_event_at,
            "issues": self.issues,
        }


def summarize_realtime_call_state(events: list[dict[str, object]]) -> dict[str, object] | None:
    call_events = latest_realtime_call_events(events)
    if not call_events:
        return None
    return reduce_realtime_call_events(call_events).as_dict()


def latest_realtime_call_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    call_ids = [str(event.get("callId") or "") for event in events if event.get("callId")]
    if not call_ids:
        return []
    latest = call_ids[-1]
    return [event for event in events if str(event.get("callId") or "") == latest]


def reduce_realtime_call_events(events: list[dict[str, object]]) -> RealtimeCallState:
    sorted_events = sorted(events, key=lambda event: _parse_event_time(event) or datetime.min)
    call_id = next((str(event.get("callId") or "") for event in reversed(sorted_events) if event.get("callId")), "") or None
    event_types = {str(event.get("type") or "") for event in sorted_events}
    answer_types = {
        str(_raw(event).get("answerType") or "")
        for event in sorted_events
        if event.get("type") == "answer_classified"
    }

    human = "human_speech_confirmed" in event_types or "human" in answer_types
    call_screening = "call_screening_detected" in event_types or "phone_assistant" in answer_types
    voicemail = "voicemail_detected" in event_types or "voicemail" in answer_types
    silence = "silence" in answer_types or "opening_after_remote_silence" in event_types
    no_response = "no_response_hangup_timeout" in event_types
    hangup = bool(event_types.intersection({"hangup_frame", "call_disconnected"}))
    ai_speech = _has_ai_speech(sorted_events)
    customer_speech = human or any(
        event.get("type") in {"asr_final", "asr_partial_stable", "remote_speech_started"}
        for event in sorted_events
    )
    interruption = any(
        event.get("type") in {"barge_in", "barge_recovery_ready", "barge_turn_committed", "tts_interrupted"}
        for event in sorted_events
    )
    auto_close_ever_scheduled = any(
        event.get("type") in {"call_screening_hangup_scheduled", "no_response_hangup_scheduled"}
        for event in sorted_events
    )
    scheduled_auto_close = _active_auto_close_scheduled(sorted_events)

    latency_breakdown = _latency_breakdown(sorted_events)
    latest_turn_response_ms = latency_breakdown.get("turnToFirstAudioMs")
    turn_taking_status = _turn_taking_status(latest_turn_response_ms, sorted_events)
    last_customer_text = _last_text(sorted_events, {"asr_final", "asr_partial_stable", "human_speech_confirmed"})
    last_ai_reply = _last_reply(sorted_events)
    last_event_at = str(sorted_events[-1].get("at") or "") or None

    state, label, status, close_reason = _derive_state(
        sorted_events,
        human=human,
        call_screening=call_screening,
        voicemail=voicemail,
        silence=silence,
        no_response=no_response,
        hangup=hangup,
        ai_speech=ai_speech,
        scheduled_auto_close=scheduled_auto_close,
    )
    issues = _derive_issues(
        sorted_events,
        state=state,
        human=human,
        call_screening=call_screening,
        voicemail=voicemail,
        no_response=no_response,
        ai_speech=ai_speech,
        latest_turn_response_ms=latest_turn_response_ms,
    )
    current_phase, phase_label, turn_action = _derive_current_phase(
        sorted_events,
        state=state,
        scheduled_auto_close=scheduled_auto_close,
    )

    return RealtimeCallState(
        call_id=call_id,
        state=state,
        label=label,
        status=status,
        close_reason=close_reason,
        can_auto_close=call_screening or ai_speech or voicemail or silence,
        auto_close_scheduled=auto_close_ever_scheduled,
        human_speech_confirmed=human,
        call_screening_detected=call_screening,
        voicemail_detected=voicemail,
        silence_detected=silence,
        no_response_detected=no_response,
        hangup_detected=hangup,
        ai_speech_confirmed=ai_speech,
        customer_speech_confirmed=customer_speech,
        interruption_detected=interruption,
        turn_taking_status=turn_taking_status,
        latest_turn_response_ms=latest_turn_response_ms,
        current_phase=current_phase,
        phase_label=phase_label,
        turn_action=turn_action,
        latency_breakdown=latency_breakdown,
        last_customer_text=last_customer_text,
        last_ai_reply=last_ai_reply,
        last_event_at=last_event_at,
        issues=issues,
    )


def _derive_state(
    events: list[dict[str, object]],
    *,
    human: bool,
    call_screening: bool,
    voicemail: bool,
    silence: bool,
    no_response: bool,
    hangup: bool,
    ai_speech: bool,
    scheduled_auto_close: bool,
) -> tuple[str, str, str, str | None]:
    event_types = {str(event.get("type") or "") for event in events}
    if "call_screening_hangup_timeout" in event_types:
        return "call_screening_timeout", "电话助理未转真人，已自动关闭", "closed", "call_screening_no_human"
    if no_response:
        return "no_response_timeout", "客户无响应，已自动关闭", "closed", "no_customer_response"
    if voicemail:
        return "voicemail", "语音信箱，已关闭", "closed", "voicemail"
    if "call_closed" in event_types:
        return "closed", "通话已正常结束", "closed", "customer_closed"
    if "call_error" in event_types and human and ai_speech and _has_audiosocket_closed_error(events):
        return "closed", "通话已正常结束", "closed", "remote_hangup"
    if "call_error" in event_types:
        return "error", "通话链路异常", "closed", "call_error"
    if hangup and "call_disconnected" in event_types:
        return "hangup", "通话已挂断", "closed", "remote_hangup"
    if call_screening and not human:
        if scheduled_auto_close:
            return "phone_assistant_waiting", "电话助理，等待真人转接", "attention", None
        return "phone_assistant", "电话助理/秘书", "attention", None
    if silence and not human and not ai_speech:
        return "silence", "接通后静音/无有效语音", "attention", None
    if scheduled_auto_close and "no_response_hangup_scheduled" in event_types:
        return "waiting_customer_response", "AI已回复，等待客户回应", "active", None
    if _last_meaningful_event_type(events) == "tts_start":
        return "ai_speaking", "AI正在说话", "active", None
    if _last_meaningful_event_type(events) in {"asr_partial", "turn_waiting_final"}:
        return "customer_speaking", "客户正在说话/等待转写完成", "active", None
    if _last_meaningful_event_type(events) in {"asr_final", "asr_partial_stable", "human_speech_confirmed", "remote_speech_started"}:
        return "customer_speaking", "客户正在说话/刚说完", "active", None
    if human:
        return "human", "真人客户已接听", "active", None
    if "call_connected" in event_types:
        return "answer_classifying", "已接通，正在判断接听方", "active", None
    return "unknown", "状态未知", "unknown", None


def _derive_issues(
    events: list[dict[str, object]],
    *,
    state: str,
    human: bool,
    call_screening: bool,
    voicemail: bool,
    no_response: bool,
    ai_speech: bool,
    latest_turn_response_ms: int | None,
) -> list[str]:
    issues: list[str] = []
    if call_screening and not human and state not in {"call_screening_timeout", "phone_assistant_waiting"}:
        issues.append("检测到电话助理，但没有明确等待/关闭事件。")
    if not human and not call_screening and not voicemail and _has_event(events, "call_connected"):
        issues.append("接通后还没有确认是真人客户。")
    if ai_speech and _has_event(events, "tts_done") and not _has_event(events, "no_response_hangup_scheduled") and not _has_terminal_event(events):
        issues.append("AI播报完成后没有看到无响应自动关闭计时。")
    if no_response:
        issues.append("客户在AI回复后没有继续说话，系统已自动关闭以避免空等。")
    if latest_turn_response_ms is not None and latest_turn_response_ms > 1000:
        issues.append(f"客户说完到AI首个声音约 {latest_turn_response_ms}ms，超过1秒目标。")
    if human and _has_unanswered_customer_turn(events):
        issues.append("客户最后一句没有得到可听见的AI回复。")
    return issues


def _has_unanswered_customer_turn(events: list[dict[str, object]]) -> bool:
    last_customer_at: datetime | None = None
    for event in events:
        if event.get("type") not in {"asr_final", "asr_partial_stable", "turn_endpoint_final", "turn_endpoint_candidate"}:
            continue
        text = str(event.get("text") or "")
        if not _is_actionable_customer_text(text):
            continue
        event_at = _parse_event_time(event)
        if event_at:
            last_customer_at = event_at
    if not last_customer_at:
        return False
    for event in events:
        event_at = _parse_event_time(event)
        if not event_at or event_at <= last_customer_at:
            continue
        if event.get("type") in {"tts_start", "tts_done"} and _speech_event_has_audio(event):
            return False
    return any(
        event.get("type") in {"call_error", "call_disconnected", "call_closed", "hangup_frame"}
        and (event_at := _parse_event_time(event)) is not None
        and event_at >= last_customer_at
        for event in events
    )


def _is_actionable_customer_text(text: str) -> bool:
    compact = "".join(
        char.lower()
        for char in str(text or "")
        if char not in " \t\r\n。！？?!，,、.；;：:\"'“”‘’（）()[]【】"
    )
    if not compact or compact in {"喂", "喂喂", "你好", "您好", "你好你好", "在吗"}:
        return False
    return len(compact) >= 2


def _speech_event_has_audio(event: dict[str, object]) -> bool:
    raw = _raw(event)
    return int(event.get("sentBytes") or event.get("bytes") or raw.get("sentBytes") or raw.get("bytes") or raw.get("totalBytes") or 0) > 0


def _latest_turn_response_ms(events: list[dict[str, object]]) -> int | None:
    return _latency_breakdown(events).get("turnToFirstAudioMs")


def _latency_breakdown(events: list[dict[str, object]]) -> dict[str, int | None]:
    latest_turn = _latest_event(events, {"asr_final", "asr_partial_stable", "barge_turn_committed"})
    turn_to_reply_ms = _diff_to_next_event(events, latest_turn, {"llm_reply", "omni_response_slow_fallback"})
    turn_to_first_audio_ms = _diff_to_next_event(events, latest_turn, {"tts_start"})
    latest_stable = _latest_event(events, {"asr_partial_stable"})
    latest_final = _latest_event(events, {"asr_final"})
    latest_llm = _latest_event(events, {"llm_reply"})
    latest_tts = _latest_event(events, {"tts_start"})
    return {
        "turnToReplyMs": turn_to_reply_ms,
        "turnToFirstAudioMs": turn_to_first_audio_ms,
        "asrPartialToFinalMs": _asr_partial_to_final_ms(events, latest_final),
        "stablePartialWaitMs": _event_int(latest_stable, "waitMs"),
        "llmMs": _event_int(latest_llm, "latencyMs"),
        "ttsFirstAudioMs": _event_int(latest_tts, "firstAudioMs") or _event_int(latest_tts, "synthMs"),
        "bargeStopMs": _barge_stop_ms(events),
    }


def _derive_current_phase(
    events: list[dict[str, object]],
    *,
    state: str,
    scheduled_auto_close: bool,
) -> tuple[str, str, str]:
    if state in {"closed", "hangup", "voicemail", "no_response_timeout", "call_screening_timeout", "error"}:
        labels = {
            "closed": ("closed", "通话已结束", "复盘本通电话。"),
            "hangup": ("closed", "客户已挂断", "结束并保存记录。"),
            "voicemail": ("closed", "语音信箱", "不留言，直接关闭。"),
            "no_response_timeout": ("closed", "无响应关闭", "避免继续空等计费。"),
            "call_screening_timeout": ("closed", "电话助理超时", "未转真人，已关闭。"),
            "error": ("error", "链路异常", "检查 AudioSocket/ASR/TTS。"),
        }
        return labels.get(state, ("closed", "通话已结束", "复盘本通电话。"))

    last_type = _last_meaningful_event_type(events)
    if last_type in {"asr_partial", "remote_speech_started"}:
        return "waiting_asr_final", "客户说话中/等待最终转写", "先听完，不抢答。"
    if last_type == "turn_waiting_final":
        return "waiting_asr_final", "等待客户说完", "ASR partial 还不完整，继续听。"
    if last_type in {"asr_final", "asr_partial_stable", "turn_endpoint_final", "turn_reply_preparing"}:
        return "reply_preparing", "客户已说完，准备回复", "取消旧播放，进入销售脑。"
    if last_type in {"turn_llm_start", "intent", "llm_reply"}:
        return "reply_generating", "正在生成/等待首个声音", "目标 1 秒内开始播。"
    if last_type == "tts_start":
        return "ai_speaking", "AI正在说话", "客户插话要立刻停。"
    if last_type in {"barge_in", "tts_interrupted", "barge_playback_drained", "barge_recovery_ready", "barge_turn_committed"}:
        return "barge_listening", "客户打断，已停嘴听", "等客户说完后再回。"
    if scheduled_auto_close or last_type in {"tts_done", "no_response_hangup_scheduled"}:
        return "listening_after_ai", "AI已说完，监听客户", "客户无响应会自动关闭。"
    if state == "phone_assistant_waiting":
        return "phone_assistant_waiting", "电话助理，等待真人", "短等待后自动关闭。"
    if state == "silence":
        return "silence", "接通后静音", "短开场或关闭，避免空等。"
    if state == "answer_classifying":
        return "answer_classifying", "正在判断接听方", "区分真人、电话助理、语音信箱。"
    return "listening", "监听客户", "等待客户下一句话。"


def _latest_turn_response_ms_legacy(events: list[dict[str, object]]) -> int | None:
    customer_events = [
        event
        for event in events
        if event.get("type") in {"asr_final", "asr_partial_stable", "barge_turn_committed", "barge_recovery_ready"}
    ]
    response_types = {"llm_reply", "tts_start", "omni_response_slow_fallback"}
    for customer_event in reversed(customer_events):
        customer_at = _parse_event_time(customer_event)
        if not customer_at:
            continue
        best: int | None = None
        for event in events:
            if event.get("type") not in response_types:
                continue
            response_at = _parse_event_time(event)
            if not response_at or response_at < customer_at:
                continue
            diff = int((response_at - customer_at).total_seconds() * 1000)
            if best is None or diff < best:
                best = diff
        if best is not None:
            return best
    return None


def _turn_taking_status(latency_ms: int | None, events: list[dict[str, object]]) -> str:
    if latency_ms is None:
        if any(event.get("type") in {"barge_in", "barge_recovery_ready", "tts_interrupted"} for event in events):
            return "warn"
        return "unknown"
    if latency_ms <= 1000:
        return "pass"
    if latency_ms <= 1500:
        return "warn"
    return "fail"


def _has_ai_speech(events: list[dict[str, object]]) -> bool:
    for event in events:
        if event.get("type") not in {"tts_start", "tts_done"}:
            continue
        raw = _raw(event)
        if int(raw.get("sentBytes") or raw.get("bytes") or raw.get("totalBytes") or 0) > 0:
            return True
        if event.get("type") == "tts_start":
            return True
    return False


def _last_text(events: list[dict[str, object]], event_types: set[str]) -> str | None:
    for event in reversed(events):
        if event.get("type") in event_types and event.get("text"):
            return str(event.get("text"))
    return None


def _last_reply(events: list[dict[str, object]]) -> str | None:
    for event in reversed(events):
        if event.get("type") == "llm_reply" and event.get("reply"):
            return str(event.get("reply"))
        if event.get("type") == "omni_no_audio_response" and _raw(event).get("fallbackText"):
            return str(_raw(event).get("fallbackText"))
    return None


def _last_event_type(events: list[dict[str, object]]) -> str:
    return str(events[-1].get("type") or "") if events else ""


def _last_meaningful_event_type(events: list[dict[str, object]]) -> str:
    skip_types = {
        "remote_audio_sample",
        "idle_keepalive_done",
        "asr_partial_turn_cancelled",
        "audio_capture_saved",
        "audio_capture_started",
    }
    for event in reversed(events):
        event_type = str(event.get("type") or "")
        if event_type and event_type not in skip_types:
            return event_type
    return ""


def _has_event(events: list[dict[str, object]], event_type: str) -> bool:
    return any(event.get("type") == event_type for event in events)


def _has_terminal_event(events: list[dict[str, object]]) -> bool:
    return any(event.get("type") in TERMINAL_EVENT_TYPES for event in events)


def _has_audiosocket_closed_error(events: list[dict[str, object]]) -> bool:
    for event in events:
        if event.get("type") != "call_error":
            continue
        raw = _raw(event)
        message = " ".join(
            str(value or "")
            for value in (
                event.get("error"),
                event.get("detail"),
                raw.get("error"),
                raw.get("detail"),
            )
        )
        if "AudioSocket connection closed" in message:
            return True
    return False


def _active_auto_close_scheduled(events: list[dict[str, object]]) -> bool:
    active = False
    for event in events:
        event_type = event.get("type")
        if event_type in {"call_screening_hangup_scheduled", "no_response_hangup_scheduled"}:
            active = True
        elif event_type in {
            "no_response_hangup_cancelled",
            "human_speech_confirmed",
            "asr_partial_stable",
            "asr_final",
            "call_screening_hangup_timeout",
            "no_response_hangup_timeout",
            "voicemail_detected",
            "hangup_frame",
            "call_closed",
            "call_disconnected",
            "call_error",
        }:
            active = False
    return active


def _raw(event: dict[str, object]) -> dict[str, Any]:
    raw = event.get("raw")
    if isinstance(raw, dict):
        return raw
    return event


def _latest_event(events: list[dict[str, object]], event_types: set[str]) -> dict[str, object] | None:
    for event in reversed(events):
        if event.get("type") in event_types:
            return event
    return None


def _diff_to_next_event(
    events: list[dict[str, object]],
    start_event: dict[str, object] | None,
    response_types: set[str],
) -> int | None:
    if not start_event:
        return None
    start_at = _parse_event_time(start_event)
    if not start_at:
        return None
    best: int | None = None
    for event in events:
        if event.get("type") not in response_types:
            continue
        event_at = _parse_event_time(event)
        if not event_at or event_at < start_at:
            continue
        diff = int((event_at - start_at).total_seconds() * 1000)
        if best is None or diff < best:
            best = diff
    return best


def _asr_partial_to_final_ms(
    events: list[dict[str, object]],
    final_event: dict[str, object] | None,
) -> int | None:
    if not final_event:
        return None
    final_at = _parse_event_time(final_event)
    if not final_at:
        return None
    previous_partial: dict[str, object] | None = None
    for event in events:
        event_at = _parse_event_time(event)
        if not event_at or event_at >= final_at:
            break
        if event.get("type") in {"asr_partial", "remote_speech_started"}:
            previous_partial = event
        elif event.get("type") in {"llm_reply", "tts_start", "tts_done", "asr_final", "asr_partial_stable"}:
            previous_partial = None
    if not previous_partial:
        return None
    partial_at = _parse_event_time(previous_partial)
    if not partial_at:
        return None
    return int((final_at - partial_at).total_seconds() * 1000)


def _barge_stop_ms(events: list[dict[str, object]]) -> int | None:
    latest_barge = _latest_event(events, {"barge_in"})
    return _diff_to_next_event(events, latest_barge, {"tts_interrupted", "barge_recovery_ready", "barge_playback_drained"})


def _event_int(event: dict[str, object] | None, key: str) -> int | None:
    if not event:
        return None
    raw = _raw(event)
    value = event.get(key)
    if value is None:
        value = raw.get(key)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_event_time(event: dict[str, object]) -> datetime | None:
    value = str(event.get("at") or "")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo:
        return parsed.replace(tzinfo=None)
    return parsed
