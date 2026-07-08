from __future__ import annotations

import argparse
import base64
import json
import math
import os
import queue
import signal
import socket
import struct
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from concurrent.futures import ThreadPoolExecutor

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from dashscope.audio.tts_v2 import SpeechSynthesizer
from dashscope.audio.tts_v2.speech_synthesizer import AudioFormat as CosyAudioFormat
from dashscope.audio.qwen_omni import MultiModality, OmniRealtimeCallback, OmniRealtimeConversation
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.growth import VoiceCloneRecord
from app.services.realtime_answer_classifier import AnswerClassifier, CallAnswerType, classify_answer_text
from app.services.realtime_audio_quality import RealtimeAudioQualityChain, analyze_pcm16
from app.services.realtime_call_learning import record_realtime_call_learning
from app.services.realtime_flight_recorder import RealtimeFlightRecorder
from app.services.realtime_intent_capture import (
    _is_strong_realtime_intent,
    claim_realtime_call_context,
    record_realtime_intent_signal,
)
from app.services.realtime_llm import generate_realtime_reply
from app.services.realtime_outbound import _build_reply, _classify_intent
from app.services.realtime_route_health import mark_omni_route_unavailable, omni_route_unavailable_reason
from app.services.realtime_sales_playbook import (
    build_barge_recovery_instruction,
    build_omni_turn_instruction,
    build_video_group_buying_sales_instructions,
    classify_realtime_call_input,
    extract_human_text_after_system_prompt,
)
from app.services.realtime_sales_state import SalesStateMachine
from app.services.realtime_text_normalizer import has_incomplete_realtime_partial, normalize_realtime_sales_text
from app.services.realtime_turn_manager import (
    RealtimeTurnManager,
    compact_customer_text as turn_compact_customer_text,
    should_fast_commit_partial,
    stable_partial_delay_seconds,
)
from app.services.runtime_ai_config import get_runtime_ai_config


AUDIO_SOCKET_KIND_HANGUP = 0x00
AUDIO_SOCKET_KIND_UUID = 0x01
AUDIO_SOCKET_KIND_DTMF = 0x03
AUDIO_SOCKET_KIND_AUDIO = 0x10
AUDIO_SOCKET_KIND_ERROR = 0xFF
PCM_FRAME_BYTES = 320
PCM_FRAME_SECONDS = 0.02
AUDIOSOCKET_IDLE_KEEPALIVE_GAP_SECONDS = PCM_FRAME_SECONDS * 2
REMOTE_AUDIO_SAMPLE_INTERVAL_SECONDS = 1.0
OMNI_LOCAL_BARGE_MIN_SENT_BYTES = PCM_FRAME_BYTES * 12
OMNI_BARGE_RECOVERY_MIN_SECONDS = 0.35
OMNI_BARGE_RECOVERY_SILENCE_SECONDS = 0.35
OMNI_BARGE_RECOVERY_MAX_SECONDS = 1.0
OMNI_BARGE_RECOVERY_WATCHDOG_SECONDS = OMNI_BARGE_RECOVERY_MAX_SECONDS + 0.05
# 【审计A8】打断双阈值：进入打断维持 RMS>=2200/6帧；"客户仍在说话"的维持判定降到 800，
# 使打断后客户的正常音量也能持续刷新说话时间，不被过早恢复打断。
OMNI_BARGE_SUSTAIN_RMS_THRESHOLD = 800
# 【审计A8】barge 恢复 watchdog 期间客户仍在说话时的最长顺延时间。
OMNI_BARGE_RECOVERY_EXTEND_MAX_SECONDS = 6.0
OMNI_BARGE_FORCED_RESPONSE_SKIP_SECONDS = 4.0
# 【审计A5】首音频预算从 1.15s 放宽到 2.0s，避免固定兜底句反复打断正常回复。
OMNI_FIRST_AUDIO_DEADLINE_SECONDS = 2.0
# 【审计A5】打断恢复时旧客户句的最大可复用时效：超过即改用通用接话短句，不再重答旧题。
OMNI_BARGE_STALE_TEXT_MAX_SECONDS = 5.0
# 【审计A3】speech job 最大存活时间：超过即判定状态卡死，强制回到 LISTENING。
SPEECH_JOB_MAX_LIFETIME_SECONDS = 30.0
# 评审修复3：speech job 看门狗周期性检查间隔。
SPEECH_JOB_WATCHDOG_INTERVAL_SECONDS = 5.0
OMNI_NO_AUDIO_FALLBACK_TEXT = "我短说：我是做视频号团购到店获客的，帮门店做套餐和微信同城曝光。"
# 【审计A4】TTS 降级链最后一级的固定兜底句。
TTS_FALLBACK_HOLD_TEXT = "稍等一下啊"
# 【审计A6】开场接听分类等待上限从 7 秒降到 2.5 秒，避免客户喊多次"喂"AI 才说话。
REMOTE_AUDIO_CLASSIFY_WAIT_SECONDS = 2.5
REMOTE_AUDIO_SILENCE_SECONDS = 1.3
BARGE_AUDIO_FORWARD_SECONDS = 2.8
ASR_PARTIAL_STABLE_SECONDS = 0.45
ASR_PARTIAL_DUPLICATE_SECONDS = 6.0
ASR_PARTIAL_MIN_COMPACT_CHARS = 5
ASR_PARTIAL_FAST_SIGNALS = {
    "identity_handoff",
    "audio_issue",
    "repetition_complaint",
    "direct_answer_only",
    "terminal_close",
    "rejection",
    "call_screening",
}
ASR_PARTIAL_FAST_MARKERS = (
    "喂",
    "你谁",
    "谁啊",
    "谁呀",
    "你是谁",
    "哪位",
    "干嘛",
    "做什么",
    "什么事",
    "听不清",
    "没听清",
    "不说话",
    "不会说话",
    "直接说",
    "别绕",
    "收费",
    "怎么收费",
    "价格",
    "报价",
    "多少钱",
    "费用",
    "不需要",
    "不需",
    "不用",
    "不要",
    "不行",
    "加微信",
    "加我微信",
    "发资料",
    "发案例",
    "发给我",
    "给我发",
)
ASR_PARTIAL_COMPLETE_QUESTION_MARKERS = (
    "详细说一下",
    "详细讲一下",
    "具体说一下",
    "介绍一下",
    "说一下吗",
    "讲一下吗",
    "怎么做",
    "怎么合作",
    "流程",
    "有什么优势",
    "有什么用",
    "有啥用",
    "多少钱",
    "费用",
    "收费",
    "价格",
    "报价",
    "成本",
    "手机号",
    "手机号码",
    "电话号码",
    "号码",
    "加微信",
    "加我微信",
    "发资料",
    "发案例",
    "达不到",
    "保证",
    "多少客户",
    "多少单",
    "到店客流",
)
ASR_SIGNIFICANT_QUESTION_MARKERS = (
    "是不是",
    "要不要",
    "是否",
    "怎么",
    "怎么能",
    "怎么看",
    "吗",
    "呢",
    "还是",
)
ASR_SIGNIFICANT_BUSINESS_KEYWORDS = (
    "团购券",
    "券",
    "搜索",
    "不搜索",
    "客户看到",
    "用户看到",
    "看到我",
    "看到券",
    "同城推荐",
    "推荐流",
    "视频",
    "做视频",
    "拍视频",
    "发视频",
    "主页",
    "入口",
)
OPENING_RAW_BARGE_PROTECT_SECONDS = 1.8
# 【审计A7】意向旁路捕获线程池：强意向 DB 写异步执行，绝不在 websocket 回调线程里同步落库。
_INTENT_CAPTURE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-acq-intent-capture")
_DOWNSAMPLE_FACTOR = 3
_DOWNSAMPLE_FIR_TAPS = 31
_DOWNSAMPLE_CUTOFF = 3600 / 24000


def _build_downsample_taps() -> tuple[float, ...]:
    center = (_DOWNSAMPLE_FIR_TAPS - 1) / 2
    taps: list[float] = []
    for index in range(_DOWNSAMPLE_FIR_TAPS):
        distance = index - center
        if abs(distance) < 1e-9:
            sinc = 2 * _DOWNSAMPLE_CUTOFF
        else:
            sinc = math.sin(2 * math.pi * _DOWNSAMPLE_CUTOFF * distance) / (math.pi * distance)
        window = 0.54 - 0.46 * math.cos(2 * math.pi * index / (_DOWNSAMPLE_FIR_TAPS - 1))
        taps.append(sinc * window)
    total = sum(taps) or 1.0
    return tuple(tap / total for tap in taps)


_DOWNSAMPLE_TAPS = _build_downsample_taps()


def _compact_customer_text(text: str) -> str:
    return turn_compact_customer_text(text)


def _has_significant_business_question(text: str) -> bool:
    normalized = normalize_realtime_sales_text(text).normalized_text or text
    compact = _compact_customer_text(normalized)
    if not compact:
        return False
    has_question = any(marker in compact for marker in ASR_SIGNIFICANT_QUESTION_MARKERS)
    has_business_keyword = any(keyword in compact for keyword in ASR_SIGNIFICANT_BUSINESS_KEYWORDS)
    return has_question and has_business_keyword


def _adds_significant_business_question(current: str, previous: str) -> bool:
    if not current or not previous:
        return False
    if has_incomplete_realtime_partial(previous) and not has_incomplete_realtime_partial(current):
        return _has_significant_business_question(current)
    current_norm = normalize_realtime_sales_text(current).normalized_text or current
    previous_norm = normalize_realtime_sales_text(previous).normalized_text or previous
    current_compact = _compact_customer_text(current_norm)
    previous_compact = _compact_customer_text(previous_norm)
    if not current_compact or not previous_compact:
        return False
    if len(current_compact) <= len(previous_compact) + 6:
        return False
    previous_keywords = {
        keyword for keyword in ASR_SIGNIFICANT_BUSINESS_KEYWORDS if keyword in previous_compact
    }
    current_keywords = {
        keyword for keyword in ASR_SIGNIFICANT_BUSINESS_KEYWORDS if keyword in current_compact
    }
    added_keywords = current_keywords - previous_keywords
    if added_keywords and _has_significant_business_question(current_norm):
        return True
    if previous_compact in current_compact:
        suffix = current_compact.split(previous_compact, 1)[-1]
        return len(suffix) >= 6 and _has_significant_business_question(suffix)
    return False


def _is_complete_actionable_asr_partial(text: str) -> bool:
    normalized = normalize_realtime_sales_text(text).normalized_text or text
    compact = _compact_customer_text(normalized)
    if len(compact) < ASR_PARTIAL_MIN_COMPACT_CHARS:
        return False
    if compact.startswith("你需求什么"):
        return False
    has_question_shape = any(marker in text for marker in ("？", "?")) or compact.endswith(("吗", "呢", "嘛"))
    has_actionable_marker = any(marker in compact for marker in ASR_PARTIAL_COMPLETE_QUESTION_MARKERS)
    return has_question_shape and has_actionable_marker


def should_commit_stable_asr_partial(text: str) -> bool:
    return should_fast_commit_partial(text)


def _asr_partial_stable_delay_seconds(text: str) -> float:
    return stable_partial_delay_seconds(text, base_seconds=ASR_PARTIAL_STABLE_SECONDS)


@dataclass(frozen=True)
class BridgeConfig:
    bind_host: str
    port: int
    asr_model: str
    tts_model: str
    tts_voice_id: str
    tts_voice_name: str
    tts_voice_type: str
    conversation_mode: str
    omni_model: str
    omni_url: str
    omni_voice: str
    omni_input_transcription_model: str
    opening_text: str
    log_path: Path
    workspace: str | None
    barge_rms_threshold: int = 2200
    barge_frames: int = 6
    tts_gain: float = 1.0
    opening_grace_seconds: float = 1.2
    debug_audio_capture_enabled: bool = False
    debug_audio_capture_dir: Path = Path("/tmp/ai-acq-realtime-audio")
    flight_recorder_enabled: bool = True
    flight_recorder_dir: Path = Path("/tmp/ai-acq-realtime-flight")
    flight_audio_capture_enabled: bool = False
    turn_manager_enabled: bool = True
    audio_quality_enabled: bool = True
    # 【审计A6】默认接听分类等待从 7.0 降到 2.5 秒。
    answer_classification_seconds: float = 2.5
    call_screening_hangup_seconds: float = 12.0
    no_response_hangup_seconds: float = 20.0


class JsonlEventLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(self, event_type: str, **fields: Any) -> None:
        payload = {
            "at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "type": event_type,
            **fields,
        }
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        print(line, flush=True)


class CallAudioCapture:
    def __init__(self, call_id: str, directory: Path) -> None:
        safe_call_id = "".join(char for char in call_id if char.isalnum() or char in {"-", "_"}) or "unknown"
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.inbound_path = self.directory / f"{safe_call_id}.inbound.wav"
        self.outbound_raw_path = self.directory / f"{safe_call_id}.outbound.raw.wav"
        self.outbound_path = self.directory / f"{safe_call_id}.outbound.wav"
        self._lock = threading.Lock()
        self._inbound = self._open_wave(self.inbound_path)
        self._outbound_raw = self._open_wave(self.outbound_raw_path)
        self._outbound = self._open_wave(self.outbound_path)
        self.closed = False

    @staticmethod
    def _open_wave(path: Path) -> wave.Wave_write:
        handle = wave.open(str(path), "wb")
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        return handle

    def write_inbound(self, payload: bytes) -> None:
        self._write(self._inbound, payload)

    def write_outbound(self, payload: bytes) -> None:
        self._write(self._outbound, payload)

    def write_outbound_raw(self, payload: bytes) -> None:
        self._write(self._outbound_raw, payload)

    def _write(self, handle: wave.Wave_write, payload: bytes) -> None:
        if self.closed or not payload:
            return
        with self._lock:
            if not self.closed:
                handle.writeframesraw(payload)

    def close(self) -> dict[str, str]:
        with self._lock:
            if not self.closed:
                self._inbound.close()
                self._outbound_raw.close()
                self._outbound.close()
                self.closed = True
        return {
            "inboundPath": str(self.inbound_path),
            "outboundRawPath": str(self.outbound_raw_path),
            "outboundPath": str(self.outbound_path),
        }


class AudioSocketProtocolError(RuntimeError):
    pass


class CallRecognitionCallback(RecognitionCallback):
    def __init__(self, call: "AudioSocketCallSession", generation: int = 0) -> None:
        self.call = call
        # 评审修复6：记录构造时的 ASR 会话代数，用于忽略旧会话迟到回调。
        self.generation = generation
        self.last_text = ""

    def _is_stale(self, source: str) -> bool:
        # 评审修复6：代数不等于当前 ASR 会话代数，说明回调来自已被替换的旧会话。
        if self.generation == self.call._asr_generation:
            return False
        self.call.logger.emit(
            "asr_stale_callback_ignored",
            callId=self.call.call_id,
            source=source,
            generation=self.generation,
            currentGeneration=self.call._asr_generation,
        )
        return True

    def on_open(self) -> None:
        self.call.logger.emit("asr_open", callId=self.call.call_id, model=self.call.config.asr_model)

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if not isinstance(sentence, dict):
            return
        text = str(sentence.get("text") or "").strip()
        is_final = RecognitionResult.is_sentence_end(sentence)
        if text and text != self.last_text:
            event_text = text
            normalization = normalize_realtime_sales_text(text) if is_final else None
            if normalization and normalization.changed and normalization.normalized_text:
                event_text = normalization.normalized_text
            self.call.customer_activity_event.set()
            asr_fields: dict[str, Any] = {
                "callId": self.call.call_id,
                "text": event_text,
                "beginMs": sentence.get("begin_time"),
                "endMs": sentence.get("end_time"),
            }
            if normalization and normalization.changed:
                asr_fields["rawText"] = text
                asr_fields["fixes"] = list(normalization.fixes)
            self.call.logger.emit("asr_final" if is_final else "asr_partial", **asr_fields)
            self.call.handle_answer_text(text, is_final=is_final)
            if is_final:
                self.call.commit_asr_final_text(event_text)
            else:
                self.call.note_asr_partial_text(text)
            self.last_text = text

    def on_error(self, message: object) -> None:
        # 评审修复6：旧会话迟到的错误回调直接忽略，防止误触发重建。
        if self._is_stale("on_error"):
            return
        self.call.logger.emit("asr_error", callId=self.call.call_id, error=_safe_error_text(message))
        # 【审计A2】ASR 报错后自动重建会话，避免"失聪"后无人恢复。
        self.call.handle_asr_failure("on_error")

    def on_complete(self) -> None:
        self.call.logger.emit("asr_complete", callId=self.call.call_id)

    def on_close(self) -> None:
        # 评审修复6：旧会话迟到的关闭回调直接忽略，防止误触发重建。
        if self._is_stale("on_close"):
            return
        self.call.logger.emit("asr_close", callId=self.call.call_id)
        # 【审计A2】通话未结束时 ASR 连接被服务端关闭，同样触发自动重建。
        self.call.handle_asr_failure("on_close")


class CallOmniCallback(OmniRealtimeCallback):
    def __init__(self, call: "OmniAudioSocketCallSession") -> None:
        self.call = call

    def on_open(self) -> None:
        self.call.logger.emit("omni_open", callId=self.call.call_id, model=self.call.config.omni_model)

    def on_close(self, close_status_code: object, close_msg: object) -> None:
        self.call.logger.emit(
            "omni_close",
            callId=self.call.call_id,
            code=str(close_status_code),
            message=str(close_msg),
        )
        self.call.handle_omni_closed(close_status_code, close_msg)

    def on_event(self, response: dict[str, Any]) -> None:
        event_type = str(response.get("type") or "")
        if event_type == "session.updated":
            session = response.get("session") if isinstance(response.get("session"), dict) else {}
            self.call.mark_omni_session_ready()
            self.call.logger.emit(
                "omni_session_updated",
                callId=self.call.call_id,
                model=session.get("model") or self.call.config.omni_model,
                voice=session.get("voice") or self.call.config.omni_voice,
            )
            return
        if event_type == "input_audio_buffer.speech_started":
            self.call.handle_omni_speech_started()
            return
        if event_type == "conversation.item.input_audio_transcription.completed":
            text = str(response.get("transcript") or "").strip()
            if text:
                self.call.handle_omni_transcription(text)
            return
        if event_type == "conversation.item.input_audio_transcription.failed":
            self.call.logger.emit(
                "asr_error",
                callId=self.call.call_id,
                provider="qwen_omni",
                error=json.dumps(response, ensure_ascii=False)[:600],
            )
            return
        if event_type in {
            "input_audio_buffer.speech_stopped",
            "input_audio_buffer.committed",
            "input_audio_buffer.cleared",
        }:
            self.call.handle_omni_input_buffer_event(event_type, response)
            return
        if event_type == "response.created":
            response_id = _omni_response_id_from_event(response)
            self.call.start_omni_response(response_id)
            return
        if event_type == "response.audio_transcript.delta":
            self.call.append_omni_transcript_delta(str(response.get("delta") or ""), _omni_response_id_from_event(response))
            return
        if event_type == "response.audio_transcript.done":
            self.call.finish_omni_transcript(
                str(response.get("transcript") or ""),
                _omni_response_id_from_event(response),
            )
            return
        if event_type == "response.audio.delta":
            self.call.play_omni_audio_delta(str(response.get("delta") or ""), _omni_response_id_from_event(response))
            return
        if event_type == "response.done":
            self.call.finish_omni_response(_omni_response_id_from_event(response))
            return
        if event_type == "error" or response.get("error"):
            self.call.logger.emit("omni_error", callId=self.call.call_id, error=json.dumps(response, ensure_ascii=False)[:600])


def _omni_response_id_from_event(response: dict[str, Any]) -> str:
    for key in ("response_id", "responseId"):
        value = response.get(key)
        if value:
            return str(value)
    nested = response.get("response")
    if isinstance(nested, dict) and nested.get("id"):
        return str(nested.get("id"))
    return ""


class AudioSocketCallSession:
    def __init__(self, conn: socket.socket, peer: tuple[str, int], config: BridgeConfig, logger: JsonlEventLogger) -> None:
        self.conn = conn
        self.peer = peer
        self.config = config
        self.logger = logger
        self.call_id = ""
        self.customer_texts: queue.Queue[tuple[int, str]] = queue.Queue()
        self.stop_event = threading.Event()
        self.interrupt_event = threading.Event()
        self.speaking_event = threading.Event()
        self.customer_activity_event = threading.Event()
        self.send_lock = threading.Lock()
        self.playback_lock = threading.Lock()
        self.generation_lock = threading.Lock()
        self.asr_partial_lock = threading.Lock()
        self.speech_state_lock = threading.Lock()
        self.speech_generation = 0
        self.speech_jobs = 0
        # 评审修复3：speech job 最近一次 start/finish 变化时刻 + 周期看门狗只启动一次的标志，
        # 看门狗按"jobs>0 且距最后变化超过30s"判定卡死，避免卡死 job 被后续活动掩护永不回收。
        self._speech_job_last_change_at = 0.0
        self._speech_job_watchdog_started = False
        self._loud_frames = 0
        self._last_barge_at = 0.0
        self._barge_forward_until = 0.0
        self._recognition: Recognition | None = None
        # 【审计A2】ASR 保活/自动重建状态。
        self._asr_restart_lock = threading.Lock()
        self._asr_restarting = False
        self._asr_stopping = False
        self._asr_last_fed_at = 0.0
        # 评审修复1：ASR 重建永久放弃标志 + 放弃后错误日志限流时间戳（每5秒最多1条）。
        self._asr_gave_up = False
        self._asr_gave_up_log_at = 0.0
        # 评审修复6：ASR 会话代数（每次 _start_asr 自增），用于忽略旧会话迟到回调。
        self._asr_generation = 0
        self._audio_capture: CallAudioCapture | RealtimeFlightRecorder | None = None
        self._flight_recorder: RealtimeFlightRecorder | None = None
        self._intent_counts: dict[str, int] = {}
        # 【审计A7】意向旁路已提交过的文本（防止同句 final 重复入库刷日志）。
        self._intent_bypass_captured: set[str] = set()
        self._conversation_history: list[dict[str, str]] = []
        self._call_history: list[dict[str, str]] = []
        self._sales_fsm = SalesStateMachine()
        self._answer_classifier = AnswerClassifier(max_wait_seconds=self.config.answer_classification_seconds)
        self._answer_classification_reported: CallAnswerType | None = None
        self._audio_quality = RealtimeAudioQualityChain(enabled=self.config.audio_quality_enabled)
        self._audio_quality_frame_count = 0
        self._human_speech_confirmed = False
        self._call_screening_seen = False
        self._call_screening_answered = False
        self._call_screening_hangup_generation = 0
        self._no_response_hangup_generation = 0
        self._no_response_hangup_active = False
        self._system_prompt_seen = False
        self._opening_started = False
        self._opening_started_at = 0.0
        self._opening_raw_barge_protect_until = 0.0
        self._opening_raw_barge_protected_logged = False
        self._last_remote_audio_at = 0.0
        self._last_remote_speech_started_at = 0.0
        self._asr_partial_generation = 0
        self._asr_partial_text = ""
        self._last_committed_customer_text = ""
        self._last_committed_customer_at = 0.0
        self._last_remote_audio_sample_at = 0.0
        self._remote_audio_sample_peak = 0
        self._last_outbound_audio_at = 0.0
        self._startup_keepalive_active = threading.Event()
        self._intentional_close_reason = ""
        self._learning_recorded = False
        self._call_context: dict[str, Any] = {}
        self._turn_manager = (
            RealtimeTurnManager(
                rms_threshold=self.config.barge_rms_threshold,
                barge_frames=self.config.barge_frames,
            )
            if self.config.turn_manager_enabled
            else None
        )
        self._turn_thread = threading.Thread(target=self._turn_worker, name="ai-acq-audiosocket-turn", daemon=True)

    def run(self) -> None:
        self.conn.settimeout(1.0)
        self.logger.emit("socket_connected", peer=f"{self.peer[0]}:{self.peer[1]}", voice=self.config.tts_voice_name)
        try:
            if not self._await_call_uuid():
                return
            self.logger.emit("call_connected", callId=self.call_id, peer=f"{self.peer[0]}:{self.peer[1]}", voice=self.config.tts_voice_name)
            self._flight_event("call_connected", peer=f"{self.peer[0]}:{self.peer[1]}", mode="pipeline")
            self._start_startup_keepalive()
            self._start_asr()
            self._turn_thread.start()
            threading.Thread(target=self._speak_opening_after_grace, daemon=True).start()
            self._read_loop()
        except Exception as exc:  # noqa: BLE001
            if self._is_intentional_socket_close(exc):
                self.logger.emit(
                    "call_closed",
                    callId=self.call_id,
                    reason=self._intentional_close_reason,
                    detail="客户明确结束后系统主动关闭 AudioSocket。",
                )
            else:
                self.logger.emit("call_error", callId=self.call_id, error=str(exc))
        finally:
            self.stop_event.set()
            self.interrupt_event.set()
            self._record_learning_summary()
            self._stop_startup_keepalive()
            self._stop_asr()
            self._stop_audio_capture()
            try:
                self.conn.close()
            except OSError:
                pass
            self.logger.emit("call_disconnected", callId=self.call_id)

    def _is_intentional_socket_close(self, exc: Exception) -> bool:
        return bool(self._intentional_close_reason) and "AudioSocket connection closed" in str(exc)

    def _record_learning_summary(self) -> None:
        if self._learning_recorded or not self.call_id:
            return
        self._learning_recorded = True
        try:
            lesson = record_realtime_call_learning(
                call_id=self.call_id,
                conversation_history=list(self._call_history or self._conversation_history),
                close_reason=self._intentional_close_reason,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("call_learning_error", callId=self.call_id, error=str(exc))
            return
        if lesson:
            self.logger.emit(
                "call_learning_summary",
                callId=self.call_id,
                topics=lesson.get("topics", {}),
                avoidPhrases=lesson.get("avoidPhrases", []),
                nextGuidance=lesson.get("nextGuidance", []),
            )

    def _record_realtime_intent_signal(self, text: str, intent: str, signal: str, source: str) -> None:
        try:
            result = record_realtime_intent_signal(
                call_id=self.call_id,
                context=self._call_context,
                text=text,
                intent=intent,
                signal=signal,
                source=source,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("intent_capture_error", callId=self.call_id, text=text, intent=intent, error=str(exc))
            return
        if result:
            self.logger.emit(
                "intent_customer_upserted",
                callId=self.call_id,
                text=text,
                intent=intent,
                customerId=result.get("customerId"),
                intentLevel=result.get("intentLevel"),
                sourceRecordId=result.get("sourceRecordId"),
                summary=result.get("summary"),
            )

    def _capture_intent_bypass(self, text: str, source: str) -> None:
        # 【审计A7】意向旁路：每条客户 final 文本在 drain/轮次去重之前先做强意向标记扫描，
        # 命中即用线程池异步落库，不依赖轮次去重，不在 websocket 回调线程同步执行 DB 写。
        clean = " ".join(text.strip().split())
        if not clean or not self.call_id or self.stop_event.is_set():
            return
        try:
            if not _is_strong_realtime_intent(clean, ""):
                return
        except Exception:  # noqa: BLE001
            return
        compact = _compact_customer_text(clean)
        if not compact or compact in self._intent_bypass_captured:
            return
        self._intent_bypass_captured.add(compact)

        def _job() -> None:
            try:
                intent, _node = _classify_intent(clean)
                self._record_realtime_intent_signal(clean, intent, "intent_bypass", source)
            except Exception as exc:  # noqa: BLE001
                self.logger.emit("intent_capture_error", callId=self.call_id, text=clean, error=str(exc))

        try:
            _INTENT_CAPTURE_EXECUTOR.submit(_job)
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("intent_capture_error", callId=self.call_id, text=clean, error=str(exc))

    def _flight_event(self, event_type: str, **fields: Any) -> None:
        if not self._flight_recorder:
            return
        try:
            self._flight_recorder.event(event_type, **fields)
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("flight_recorder_error", callId=self.call_id, eventType=event_type, error=str(exc))

    def _turn_audio_decision(self, rms: int, now: float, *, ai_speaking: bool) -> Any | None:
        if not self._turn_manager:
            return None
        decision = self._turn_manager.on_audio_frame(rms, now=now, ai_speaking=ai_speaking)
        # Flight-recorder-only event: this is the raw VAD timeline used to prove
        # whether the bridge heard the customer before ASR text arrived.
        if decision.speech_started or decision.speech_ended or decision.barge_in:
            self._flight_event(
                f"vad_{decision.reason}",
                rms=rms,
                voiceMs=decision.voice_ms,
                silenceMs=decision.silence_ms,
                loudFrames=decision.loud_frames,
                aiSpeaking=ai_speaking,
            )
        return decision

    def _start_startup_keepalive(self) -> None:
        self._startup_keepalive_active.set()
        threading.Thread(target=self._startup_keepalive_loop, name="ai-acq-audiosocket-keepalive", daemon=True).start()

    def _stop_startup_keepalive(self) -> None:
        self._startup_keepalive_active.clear()

    def _startup_keepalive_loop(self) -> None:
        silence = b"\x00" * PCM_FRAME_BYTES
        sent = 0
        next_frame_at = time.perf_counter()
        while self._startup_keepalive_active.is_set() and not self.stop_event.is_set():
            if time.monotonic() - self._last_outbound_audio_at >= AUDIOSOCKET_IDLE_KEEPALIVE_GAP_SECONDS:
                try:
                    self._send_frame(AUDIO_SOCKET_KIND_AUDIO, silence)
                    self._last_outbound_audio_at = time.monotonic()
                except Exception as exc:  # noqa: BLE001
                    self.logger.emit("idle_keepalive_error", callId=self.call_id, error=str(exc))
                    self._close_after_socket_write_error("idle_keepalive", exc)
                    break
                sent += 1
            next_frame_at += PCM_FRAME_SECONDS
            time.sleep(max(0.0, next_frame_at - time.perf_counter()))
        self._startup_keepalive_active.clear()
        if sent:
            self.logger.emit("idle_keepalive_done", callId=self.call_id, frames=sent)

    def _close_after_socket_write_error(self, source: str, exc: Exception) -> None:
        if self.stop_event.is_set():
            return
        self.logger.emit(
            "socket_write_closed",
            callId=self.call_id,
            source=source,
            error=str(exc),
            detail="向 AudioSocket 写入音频失败，判定电话媒体链路已断开并立即结束本次会话。",
        )
        self.stop_event.set()
        self.interrupt_event.set()
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _await_call_uuid(self) -> bool:
        started = time.monotonic()
        while not self.stop_event.is_set() and time.monotonic() - started < 5:
            try:
                frame_type, payload = self._read_frame()
            except TimeoutError:
                continue
            if frame_type == AUDIO_SOCKET_KIND_UUID:
                self.call_id = _decode_call_id(payload)
                self.logger.emit("call_uuid", callId=self.call_id)
                self._call_context = claim_realtime_call_context(self.call_id)
                if self._call_context:
                    self.logger.emit(
                        "call_context_attached",
                        callId=self.call_id,
                        source="realtime_test_call",
                        merchantName=self._call_context.get("merchantName"),
                        requestedRoute=self._call_context.get("requestedRoute"),
                        effectiveRoute=self._call_context.get("effectiveRoute"),
                    )
                self._start_audio_capture()
                self._flight_event("call_uuid", hasContext=bool(self._call_context))
                return True
            if frame_type == AUDIO_SOCKET_KIND_HANGUP:
                self.logger.emit("hangup_before_uuid")
                return False
            self.logger.emit("frame_before_uuid", frameType=frame_type, bytes=len(payload))
        self.logger.emit("uuid_timeout", peer=f"{self.peer[0]}:{self.peer[1]}")
        return False

    def _start_asr(self) -> None:
        runtime_config = get_runtime_ai_config()
        if not runtime_config.dashscope_api_key:
            raise AudioSocketProtocolError("缺少 DASHSCOPE_API_KEY，不能启动实时 ASR。")
        dashscope.api_key = runtime_config.dashscope_api_key
        # 评审修复6：每次新建 ASR 会话代数 +1，回调携带代数以便忽略旧会话迟到回调。
        self._asr_generation += 1
        callback = CallRecognitionCallback(self, self._asr_generation)
        self._recognition = Recognition(
            model=self.config.asr_model,
            callback=callback,
            format="pcm",
            sample_rate=8000,
            workspace=self.config.workspace,
            disfluency_removal_enabled=True,
        )
        try:
            self._recognition.start()
        except Exception:
            # 评审修复1：start() 失败时清掉半初始化的识别器句柄，避免后续误用未启动的会话。
            self._recognition = None
            raise

    def _stop_asr(self) -> None:
        # 【审计A2】标记主动停止，避免 on_close 回调误触发自动重建。
        self._asr_stopping = True
        if not self._recognition:
            return
        try:
            self._recognition.stop()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("asr_stop_error", callId=self.call_id, error=str(exc))
        self._recognition = None

    def handle_asr_failure(self, source: str) -> None:
        # 【审计A2】ASR on_error/on_close/发送失败统一入口：通话存活时调度自动重建。
        if self.stop_event.is_set() or self._asr_stopping:
            return
        # 评审修复1：重建已永久放弃后不再调度重建，错误日志限流为每5秒最多1条。
        if self._asr_gave_up:
            now = time.monotonic()
            if now - self._asr_gave_up_log_at >= 5.0:
                self._asr_gave_up_log_at = now
                self.logger.emit(
                    "asr_failure_after_give_up",
                    callId=self.call_id,
                    source=source,
                    detail="ASR 重建已永久放弃，忽略后续失败（日志每5秒最多1条）。",
                )
            return
        self._schedule_asr_restart(source)

    def _schedule_asr_restart(self, source: str) -> None:
        with self._asr_restart_lock:
            if self._asr_restarting:
                return
            self._asr_restarting = True
        threading.Thread(
            target=self._asr_restart_worker,
            args=(source,),
            name="ai-acq-asr-restart",
            daemon=True,
        ).start()

    def _asr_restart_worker(self, source: str) -> None:
        # 【审计A2】ASR 会话自动重建：最多 3 次退避重试（0.5s/1s/2s）。
        try:
            for attempt in range(1, 4):
                time.sleep(0.5 * (2 ** (attempt - 1)))
                if self.stop_event.is_set() or self._asr_stopping:
                    return
                old_recognition = self._recognition
                self._recognition = None
                if old_recognition:
                    try:
                        old_recognition.stop()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    self._start_asr()
                except Exception as exc:  # noqa: BLE001
                    self.logger.emit(
                        "asr_restart_error",
                        callId=self.call_id,
                        source=source,
                        attempt=attempt,
                        error=str(exc),
                    )
                    continue
                self.logger.emit(
                    "asr_restarted",
                    callId=self.call_id,
                    source=source,
                    attempt=attempt,
                    detail="ASR 会话已自动重建，恢复实时识别。",
                )
                return
            # 评审修复1：3 次重试全失败后设置永久放弃标志，后续失败/保活路径不再调度重建。
            self._asr_gave_up = True
            self.logger.emit(
                "asr_restart_failed",
                callId=self.call_id,
                source=source,
                detail="ASR 会话重建 3 次仍失败，本通电话不再重试。",
            )
        finally:
            with self._asr_restart_lock:
                self._asr_restarting = False

    def _send_asr_audio_frame(self, payload: bytes) -> None:
        # 【审计A2】所有喂给 ASR 的帧统一经过 try/except，失败触发自动重建。
        recognition = self._recognition
        if not recognition or not payload:
            return
        try:
            recognition.send_audio_frame(payload)
            self._asr_last_fed_at = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("asr_send_error", callId=self.call_id, error=str(exc))
            self.handle_asr_failure("send_audio_frame")

    def _feed_asr_keepalive_silence(self, now: float) -> None:
        # 【审计A2】AI 说话期间每 200ms 喂一帧全零 8k 静音帧，防止流式 ASR 服务端超时关任务。
        # 评审修复1：ASR 重建已永久放弃时不再喂保活帧。
        if self._asr_gave_up or not self._recognition:
            return
        if now - self._asr_last_fed_at < 0.2:
            return
        self._send_asr_audio_frame(b"\x00" * PCM_FRAME_BYTES)

    def _read_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                frame_type, payload = self._read_frame()
            except TimeoutError:
                continue
            if frame_type == AUDIO_SOCKET_KIND_HANGUP:
                self.logger.emit("hangup_frame", callId=self.call_id)
                break
            if frame_type == AUDIO_SOCKET_KIND_UUID:
                self.call_id = _decode_call_id(payload)
                self.logger.emit("call_uuid", callId=self.call_id)
                self._start_audio_capture()
                self._flight_event("call_uuid", source="read_loop")
                continue
            if frame_type == AUDIO_SOCKET_KIND_DTMF:
                self.logger.emit("dtmf", callId=self.call_id, digit=payload.decode("utf-8", errors="replace"))
                continue
            if frame_type == AUDIO_SOCKET_KIND_ERROR:
                self.logger.emit("audiosocket_error_frame", callId=self.call_id, payload=payload.hex())
                break
            if frame_type != AUDIO_SOCKET_KIND_AUDIO:
                self.logger.emit("unknown_frame", callId=self.call_id, frameType=frame_type, bytes=len(payload))
                continue
            self._handle_audio(payload)

    def _handle_audio(self, payload: bytes) -> None:
        if self._audio_capture:
            self._audio_capture.write_inbound(payload)
        rms = _pcm_rms(payload)
        now = time.monotonic()
        turn_audio = self._turn_audio_decision(rms, now, ai_speaking=self.speaking_event.is_set())
        self._emit_remote_audio_sample(rms, now)
        self._handle_answer_audio(rms, now)
        if (turn_audio and turn_audio.has_voice) or (not turn_audio and rms >= self.config.barge_rms_threshold):
            if now - self._last_remote_speech_started_at > 1.5:
                self._last_remote_speech_started_at = now
                self.logger.emit(
                    "remote_speech_started",
                    callId=self.call_id,
                    source="rms",
                    rms=rms,
                    vadReason=turn_audio.reason if turn_audio else "legacy_threshold",
                    detail="检测到客户开始说话，进入听完本轮再回复。",
                )
                self._flight_event(
                    "customer_speech_start",
                    source="rms",
                    rms=rms,
                    vadReason=turn_audio.reason if turn_audio else "legacy_threshold",
                )
            self._note_customer_activity("remote_audio", now=now)
        if self.speaking_event.is_set():
            if now < self._barge_forward_until:
                self._send_asr_audio_frame(payload)
                return
            if self._should_protect_opening_from_raw_barge(now, rms):
                self._loud_frames = 0
                self._send_asr_audio_frame(payload)
                return
            if rms >= self.config.barge_rms_threshold:
                self._loud_frames += 1
            else:
                self._loud_frames = 0
            if (
                (turn_audio and turn_audio.barge_in)
                or (not turn_audio and self._loud_frames >= self.config.barge_frames and now - self._last_barge_at > 0.8)
            ):
                self._barge_forward_until = now + BARGE_AUDIO_FORWARD_SECONDS
                self.cancel_pending_speech("客户插话，停止后续 TTS 音频帧并继续听客户说话。", source="rms", rms=rms)
                self._send_asr_audio_frame(payload)
            else:
                # 【审计A2】AI 说话期间不转发客户音频时，用静音帧给 ASR 保活，防止服务端超时关任务。
                self._feed_asr_keepalive_silence(now)
            return
        self._loud_frames = 0
        self._send_asr_audio_frame(payload)

    def _should_protect_opening_from_raw_barge(self, now: float, rms: int) -> bool:
        if not self._opening_started or now > self._opening_raw_barge_protect_until:
            return False
        if self._human_speech_confirmed or self._last_committed_customer_text:
            return False
        if rms < self.config.barge_rms_threshold:
            return False
        if not self._opening_raw_barge_protected_logged:
            self._opening_raw_barge_protected_logged = True
            self.logger.emit(
                "opening_raw_barge_protected",
                callId=self.call_id,
                rms=rms,
                protectMs=int(max(0.0, self._opening_raw_barge_protect_until - now) * 1000),
                detail="首句刚开始播放时检测到对端问候音，先不断开首句，等待ASR确认后再接话。",
            )
        return True

    def _emit_remote_audio_sample(self, rms: int, now: float) -> None:
        self._remote_audio_sample_peak = max(self._remote_audio_sample_peak, rms)
        if now - self._last_remote_audio_sample_at < REMOTE_AUDIO_SAMPLE_INTERVAL_SECONDS:
            return
        self._last_remote_audio_sample_at = now
        peak = self._remote_audio_sample_peak
        self._remote_audio_sample_peak = rms
        self.logger.emit(
            "remote_audio_sample",
            callId=self.call_id,
            rms=rms,
            peakRms=peak,
            threshold=self.config.barge_rms_threshold,
            active=peak >= max(120, int(self.config.barge_rms_threshold * 0.35)),
        )

    def _handle_answer_audio(self, rms: int, now: float) -> None:
        answer_type = self._answer_classifier.on_audio_frame(rms, now)
        self._handle_answer_classification(answer_type, text="", source="audio")

    def handle_answer_text(self, text: str, *, is_final: bool) -> None:
        if text.strip():
            self._last_remote_audio_at = time.monotonic()
        classifier_text = text
        if classify_realtime_call_input(text) == "system_prompt":
            human_tail = extract_human_text_after_system_prompt(text)
            if human_tail:
                classifier_text = human_tail
        answer_type = self._answer_classifier.on_asr_text(classifier_text, is_final=is_final)
        self._handle_answer_classification(
            answer_type,
            text=classifier_text,
            source="asr_final" if is_final else "asr_partial",
        )

    def note_asr_partial_text(self, text: str) -> None:
        clean = " ".join(text.strip().split())
        if not clean:
            return
        self._note_customer_activity("asr_partial", text=clean)
        endpoint = self._turn_manager.on_partial_text(clean) if self._turn_manager else None
        should_commit = endpoint.should_commit if endpoint else should_commit_stable_asr_partial(clean)
        if not should_commit:
            with self.asr_partial_lock:
                if self._asr_partial_text and clean != self._asr_partial_text:
                    self._asr_partial_generation += 1
                    self._asr_partial_text = ""
            self.logger.emit(
                "turn_waiting_final",
                callId=self.call_id,
                text=clean,
                reason=endpoint.reason if endpoint else "incomplete_or_nonactionable_partial",
                detail="客户这句话还没有足够完整，继续听最终转写，避免抢答或重复旧问题。",
            )
            return
        with self.asr_partial_lock:
            self._asr_partial_generation += 1
            generation = self._asr_partial_generation
            self._asr_partial_text = clean
        delay = endpoint.wait_seconds if endpoint else _asr_partial_stable_delay_seconds(clean)
        self.logger.emit(
            "turn_endpoint_candidate",
            callId=self.call_id,
            text=clean,
            waitMs=int(delay * 1000),
            signal=endpoint.signal if endpoint else classify_realtime_call_input(clean),
            detail="客户短句或完整问题已足够可答，若 ASR final 未到会先接话。",
        )
        self._flight_event(
            "turn_endpoint_candidate",
            text=clean,
            waitMs=int(delay * 1000),
            signal=endpoint.signal if endpoint else classify_realtime_call_input(clean),
            source="asr_partial",
        )
        threading.Thread(
            target=self._commit_stable_asr_partial_after_delay,
            args=(generation, clean, delay),
            name="ai-acq-asr-partial-turn",
            daemon=True,
        ).start()

    def commit_asr_final_text(self, text: str) -> None:
        # 【审计A7】final 文本入口先走意向旁路（在 drain/去重之前），防止强意向被轮次去重吞掉。
        self._capture_intent_bypass(text, "asr_final_bypass")
        self._cancel_pending_asr_partial_turn("asr_final")
        self.logger.emit(
            "turn_endpoint_final",
            callId=self.call_id,
            text=text,
            detail="ASR final 到达，客户本轮说话完成。",
        )
        self._flight_event("turn_endpoint_final", text=text, source="asr_final")
        self._commit_customer_text(text, source="asr_final", detail="客户说话完成，取消旧 TTS 队列。")

    def _commit_stable_asr_partial_after_delay(self, generation: int, text: str, delay: float) -> None:
        time.sleep(delay)
        if self.stop_event.is_set():
            return
        with self.asr_partial_lock:
            if generation != self._asr_partial_generation or text != self._asr_partial_text:
                return
        if not should_commit_stable_asr_partial(text):
            return
        self.logger.emit(
            "asr_partial_stable",
            callId=self.call_id,
            text=text,
            waitMs=int(delay * 1000),
            detail="ASR 最终文本尚未到达，但客户短句已稳定，先触发回复避免客户空等。",
        )
        self._commit_customer_text(text, source="asr_partial_stable", detail="客户语音已稳定，先接话并取消旧 TTS 队列。")

    def _commit_customer_text(self, text: str, *, source: str, detail: str) -> None:
        clean = " ".join(text.strip().split())
        if not clean or self.stop_event.is_set():
            return
        self._note_customer_activity(source, text=clean)
        if self._is_recent_committed_customer_text(clean):
            self.logger.emit(
                "customer_turn_duplicate_ignored",
                callId=self.call_id,
                text=clean,
                source=source,
                detail="ASR final 与前面的稳定 partial 内容重复，避免重复回复或打断刚开始的回复。",
            )
            return
        self.logger.emit(
            "turn_reply_preparing",
            callId=self.call_id,
            text=clean,
            source=source,
            detail="客户本轮已提交给销售脑，准备生成回复。",
        )
        self._flight_event("turn_committed", text=clean, source=source)
        generation = self.cancel_pending_speech(detail, source=source)
        self._remember_committed_customer_text(clean)
        self.customer_texts.put((generation, clean))

    def _note_customer_activity(self, source: str, *, text: str = "", now: float | None = None) -> None:
        self.customer_activity_event.set()
        self._last_remote_audio_at = now or time.monotonic()
        self._cancel_no_response_hangup(source, text=text)

    def _cancel_no_response_hangup(self, source: str, *, text: str = "") -> None:
        if not self._no_response_hangup_active:
            return
        self._no_response_hangup_active = False
        self._no_response_hangup_generation += 1
        self.logger.emit(
            "no_response_hangup_cancelled",
            callId=self.call_id,
            source=source,
            text=text[:100],
            detail="检测到客户新语音，取消 AI 回复后的无响应挂断计时。",
        )

    def _cancel_pending_asr_partial_turn(self, source: str) -> None:
        with self.asr_partial_lock:
            self._asr_partial_generation += 1
            self._asr_partial_text = ""
        self.logger.emit("asr_partial_turn_cancelled", callId=self.call_id, source=source)

    def _remember_committed_customer_text(self, text: str) -> None:
        with self.asr_partial_lock:
            self._last_committed_customer_text = text
            self._last_committed_customer_at = time.monotonic()

    def _is_recent_committed_customer_text(self, text: str) -> bool:
        compact = _compact_customer_text(text)
        if not compact:
            return False
        with self.asr_partial_lock:
            previous = self._last_committed_customer_text
            previous_at = self._last_committed_customer_at
        if not previous or time.monotonic() - previous_at > ASR_PARTIAL_DUPLICATE_SECONDS:
            return False
        previous_compact = _compact_customer_text(previous)
        if not previous_compact:
            return False
        if _adds_significant_business_question(text, previous):
            return False
        if compact == previous_compact:
            return True
        shorter, longer = sorted((compact, previous_compact), key=len)
        if len(shorter) >= 3 and shorter in longer:
            return True
        similarity = SequenceMatcher(None, compact, previous_compact).ratio()
        if similarity >= 0.72:
            return True
        signal = classify_realtime_call_input(text)
        previous_signal = classify_realtime_call_input(previous)
        return (
            similarity >= 0.62
            and signal == previous_signal
            and signal in ASR_PARTIAL_FAST_SIGNALS
            and min(len(compact), len(previous_compact)) >= 2
        )

    def _handle_answer_classification(self, answer_type: CallAnswerType | None, *, text: str, source: str) -> None:
        if not answer_type or answer_type == CallAnswerType.UNKNOWN:
            return
        if self._answer_classification_reported == answer_type:
            return
        self._answer_classification_reported = answer_type
        state = self._answer_classifier.state
        self.logger.emit(
            "answer_classified",
            callId=self.call_id,
            answerType=answer_type.value,
            source=source,
            reason=state.reason,
            text=text,
            speechCount=state.speech_count,
            longestSpeechMs=int(state.longest_speech * 1000),
        )
        if answer_type == CallAnswerType.HUMAN:
            self._confirm_human_speech(text, detail="接听判定确认是真人，进入实时对话。")
            return
        if answer_type == CallAnswerType.PHONE_ASSISTANT:
            self._respond_to_call_screening(text or "电话助理提示", source=f"answer_classifier:{source}")
            return
        if answer_type == CallAnswerType.VOICEMAIL:
            self.logger.emit(
                "voicemail_detected",
                callId=self.call_id,
                text=text,
                detail="检测到语音信箱，直接挂断不留言。",
            )
            self.stop_event.set()
            return
        if answer_type == CallAnswerType.SYSTEM_PROMPT:
            self._system_prompt_seen = True
            self.logger.emit(
                "system_prompt_detected",
                callId=self.call_id,
                text=text,
                detail="检测到运营商或手机系统提示，暂不触发销售话术。",
            )

    def _respond_to_call_screening(self, text: str, *, source: str) -> None:
        self._call_screening_seen = True
        if self._call_screening_answered or self.stop_event.is_set():
            return
        self._call_screening_answered = True
        reply = "您好，我这边做视频号团购到店获客，来电想确认门店微信同城曝光合作，麻烦转接负责人，谢谢。"
        self.logger.emit(
            "call_screening_detected",
            callId=self.call_id,
            text=text,
            source=source,
            detail="识别到电话助理/秘书提示，只说明身份和来电原因，等待真人转接。",
        )
        self.logger.emit(
            "llm_reply",
            callId=self.call_id,
            reply=reply,
            strategy="phone_assistant_handoff",
            latencyMs=0,
            fallbackUsed=True,
            historyTurns=len(self._conversation_history),
            error=None,
        )
        with self.generation_lock:
            generation = self.speech_generation
        threading.Thread(target=self._speak, args=(reply, "call_screening", generation), daemon=True).start()
        self._schedule_call_screening_hangup(source)

    def _confirm_human_speech(self, text: str, *, detail: str) -> None:
        if self._human_speech_confirmed:
            return
        self._human_speech_confirmed = True
        self.logger.emit(
            "human_speech_confirmed",
            callId=self.call_id,
            text=text,
            detail=detail,
        )

    def _schedule_call_screening_hangup(self, source: str) -> None:
        wait_seconds = max(0.0, self.config.call_screening_hangup_seconds)
        if wait_seconds <= 0:
            return
        self._call_screening_hangup_generation += 1
        generation = self._call_screening_hangup_generation
        self.logger.emit(
            "call_screening_hangup_scheduled",
            callId=self.call_id,
            waitMs=int(wait_seconds * 1000),
            source=source,
            detail="电话助理说明来意后进入短等待；若无人转接真人，将主动挂断避免空等计费。",
        )
        threading.Thread(
            target=self._close_if_no_human_after_call_screening,
            args=(generation, wait_seconds),
            daemon=True,
        ).start()

    def _close_if_no_human_after_call_screening(self, generation: int, wait_seconds: float) -> None:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline and not self.stop_event.is_set():
            if self._human_speech_confirmed:
                return
            time.sleep(0.1)
        if (
            self.stop_event.is_set()
            or self._human_speech_confirmed
            or generation != self._call_screening_hangup_generation
        ):
            return
        self.logger.emit(
            "call_screening_hangup_timeout",
            callId=self.call_id,
            waitMs=int(wait_seconds * 1000),
            detail="电话助理后未等到真人转接，主动结束本次通话。",
        )
        self._close_after_terminal_reply("call_screening_no_human")

    def _schedule_no_response_hangup(self, reason: str) -> None:
        if reason == "call_screening":
            return
        wait_seconds = max(0.0, self.config.no_response_hangup_seconds)
        if wait_seconds <= 0:
            return
        self._no_response_hangup_generation += 1
        generation = self._no_response_hangup_generation
        self._no_response_hangup_active = True
        baseline_remote_audio_at = self._last_remote_audio_at
        self.logger.emit(
            "no_response_hangup_scheduled",
            callId=self.call_id,
            waitMs=int(wait_seconds * 1000),
            reason=reason,
            detail="AI 说完后进入短等待；若客户没有新语音，将主动结束通话，避免长时间空等计费。",
        )
        threading.Thread(
            target=self._close_if_no_response_after_speech,
            args=(generation, wait_seconds, baseline_remote_audio_at, reason),
            daemon=True,
        ).start()

    def _close_if_no_response_after_speech(
        self,
        generation: int,
        wait_seconds: float,
        baseline_remote_audio_at: float,
        reason: str,
    ) -> None:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline and not self.stop_event.is_set():
            if self._last_remote_audio_at > baseline_remote_audio_at:
                if generation == self._no_response_hangup_generation:
                    self._no_response_hangup_active = False
                return
            time.sleep(0.2)
        if (
            self.stop_event.is_set()
            or self.speaking_event.is_set()
            or self._last_remote_audio_at > baseline_remote_audio_at
            or generation != self._no_response_hangup_generation
        ):
            if generation == self._no_response_hangup_generation:
                self._no_response_hangup_active = False
            return
        self._no_response_hangup_active = False
        self.logger.emit(
            "no_response_hangup_timeout",
            callId=self.call_id,
            waitMs=int(wait_seconds * 1000),
            reason=reason,
            detail="AI 说完后没有检测到客户新语音，主动结束本次通话。",
        )
        self._close_after_terminal_reply("no_customer_response")

    def _speak_opening_after_grace(self) -> None:
        grace = max(0.0, self.config.opening_grace_seconds)
        if grace and self.customer_activity_event.wait(grace):
            self.logger.emit("opening_deferred", callId=self.call_id, reason="remote_audio_detected")
            if not self._wait_for_remote_classification_before_opening("pipeline"):
                return
        if self._mark_opening_started():
            with self.generation_lock:
                generation = self.speech_generation
            self.logger.emit("opening_start", callId=self.call_id, mode="pipeline", text=self.config.opening_text)
            threading.Thread(target=self._speak, args=(self.config.opening_text, "opening", generation), daemon=True).start()

    def _wait_for_remote_classification_before_opening(self, mode: str) -> bool:
        wait_seconds = max(0.2, self.config.answer_classification_seconds)
        deadline = time.monotonic() + wait_seconds
        saw_remote_audio = bool(self._last_remote_audio_at)
        while time.monotonic() < deadline and not self.stop_event.is_set():
            if self._opening_blocked():
                return False
            if self._answer_classifier.state.done:
                break
            if self._last_remote_audio_at:
                saw_remote_audio = True
            if self._last_remote_audio_at and time.monotonic() - self._last_remote_audio_at < REMOTE_AUDIO_SILENCE_SECONDS:
                time.sleep(0.08)
                continue
            time.sleep(0.08)
        if self._opening_blocked():
            return False
        answer_type = self._answer_classifier.state.detected_type
        if not self._answer_classifier.state.done:
            answer_type = self._answer_classifier.classify_after_wait()
            self._handle_answer_classification(answer_type, text="", source="opening_wait_timeout")
        if answer_type in {CallAnswerType.PHONE_ASSISTANT, CallAnswerType.VOICEMAIL, CallAnswerType.SYSTEM_PROMPT}:
            return False
        if answer_type == CallAnswerType.HUMAN:
            self.logger.emit(
                "opening_after_human_audio",
                callId=self.call_id,
                mode=mode,
                waitMs=int(wait_seconds * 1000),
                detail="已确认对端是真人但还没有最终转写，先播短开场避免电话里长时间沉默。",
            )
            return True
        if saw_remote_audio:
            self.logger.emit(
                "opening_after_unknown_remote",
                callId=self.call_id,
                mode=mode,
                waitMs=int(wait_seconds * 1000),
                answerType=answer_type.value,
                detail="对端已有声音但未能明确分类，避免长时间沉默，使用短开场接话。",
            )
            return True
        self.logger.emit(
            "opening_after_remote_silence",
            callId=self.call_id,
            mode=mode,
            waitMs=int(wait_seconds * 1000),
        )
        return True

    def _opening_blocked(self) -> bool:
        return (
            self.stop_event.is_set()
            or self.speaking_event.is_set()
            or self._opening_started
            or self._call_screening_seen
            or self._system_prompt_seen
        )

    def _mark_opening_started(self) -> bool:
        if self._opening_blocked():
            return False
        self._opening_started = True
        self._opening_started_at = time.monotonic()
        self._opening_raw_barge_protect_until = self._opening_started_at + OPENING_RAW_BARGE_PROTECT_SECONDS
        self._opening_raw_barge_protected_logged = False
        return True

    def _turn_worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                generation, text = self.customer_texts.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.stop_event.is_set():
                break
            generation, text = self._drain_latest_customer_text(generation, text)
            if self.stop_event.is_set() or not text.strip():
                continue
            signal = classify_realtime_call_input(text)
            if signal == "system_prompt":
                human_tail = extract_human_text_after_system_prompt(text)
                if human_tail:
                    self.logger.emit(
                        "system_prompt_stripped",
                        callId=self.call_id,
                        text=text,
                        strippedText=human_tail,
                        detail="ASR 同一句里包含系统提示和真人客户语音，已只剥离系统提示并继续回复真人内容。",
                    )
                    text = human_tail
                    signal = classify_realtime_call_input(text)
                    if signal == "system_prompt":
                        signal = "human_speech"
                else:
                    if classify_answer_text(text) == CallAnswerType.VOICEMAIL:
                        self.logger.emit(
                            "voicemail_detected",
                            callId=self.call_id,
                            text=text,
                            detail="识别到语音信箱/留言提示，直接挂断不留言。",
                        )
                        self.stop_event.set()
                        continue
                    self._system_prompt_seen = True
                    self.logger.emit(
                        "system_prompt_ignored",
                        callId=self.call_id,
                        text=text,
                        detail="识别到运营商、手机系统或语音留言提示，已忽略，不触发销售回复。",
                    )
                    continue
            if signal == "call_screening":
                if self._call_screening_answered:
                    self.logger.emit(
                        "call_screening_followup_ignored",
                        callId=self.call_id,
                        text=text,
                        detail="电话助理后续等待提示已忽略，避免重复说明身份和来电原因。",
                    )
                    continue
                self._respond_to_call_screening(text, source="pipeline_turn")
                continue
            if not self._human_speech_confirmed:
                self._confirm_human_speech(text, detail="已识别到真人客户语音，可以进入实时对话。")
            normalization = normalize_realtime_sales_text(text)
            routed_text = normalization.normalized_text
            if normalization.changed:
                self.logger.emit(
                    "asr_sales_text_normalized",
                    callId=self.call_id,
                    text=text,
                    normalizedText=routed_text,
                    fixes=list(normalization.fixes),
                    detail="ASR 文本进入销售脑前已做高置信语境纠错，原始转写仍保留在 ASR 事件中。",
                )
            intent, node = _classify_intent(routed_text)
            stage = self._sales_fsm.update(routed_text, intent, signal)
            stage_instruction = self._sales_fsm.get_stage_instruction()
            if intent == "系统提示":
                self.logger.emit("intent", callId=self.call_id, text=text, intent=intent, node=node)
                continue
            self._record_realtime_intent_signal(routed_text, intent, signal, "pipeline_turn")
            turn_count, fallback_reply = self._reply_for_turn(routed_text, intent)
            history_snapshot = list(self._conversation_history)
            self.logger.emit(
                "turn_llm_start",
                callId=self.call_id,
                text=routed_text,
                intent=intent,
                signal=signal,
                salesStage=stage.value,
                historyTurns=len(history_snapshot),
                detail="客户本轮已进入回复生成，等待 LLM/本地话术返回。",
            )
            reply_result = generate_realtime_reply(
                text,
                intent,
                "您的门店",
                fallback_reply,
                history_snapshot,
                stage_instruction=stage_instruction,
            )
            if self.stop_event.is_set():
                continue
            reply = self._sales_fsm.constrain_reply(reply_result.reply)
            self._append_conversation_turn(text, reply)
            self._sales_fsm.record_assistant_reply(reply)
            self.logger.emit(
                "intent",
                callId=self.call_id,
                text=text,
                intent=intent,
                node=node,
                turnCount=turn_count,
                salesStage=stage.value,
            )
            self.logger.emit(
                "llm_reply",
                callId=self.call_id,
                reply=reply,
                strategy=reply_result.strategy,
                latencyMs=reply_result.latency_ms,
                fallbackUsed=reply_result.fallback_used,
                historyTurns=len(history_snapshot),
                error=reply_result.error,
            )
            close_after = intent in {"明确拒绝", "礼貌结束"} or self._sales_fsm.should_end_call()
            reason = "closing_reply" if close_after else "reply"
            threading.Thread(target=self._speak, args=(reply, reason, generation, close_after), daemon=True).start()

    def _reply_for_turn(self, text: str, intent: str) -> tuple[int, str]:
        turn_count = self._intent_counts.get(intent, 0)
        self._intent_counts[intent] = turn_count + 1
        clean = text.strip()
        compact = "".join(char for char in clean.lower() if char not in " \t\r\n。！？?!，,、.")
        if intent == "身份确认":
            if compact in {"喂", "喂喂", "你好"}:
                if turn_count == 0:
                    return turn_count, "您好，我在。我是做视频号团购到店获客的，给您来电是确认微信同城曝光这块。"
                return turn_count, "我在。刚才说的是视频号团购到店获客，不方便我就不打扰。"
            if turn_count == 0:
                return turn_count, "我是做视频号团购到店获客的，给您来电是确认门店是否需要微信同城曝光。"
            return turn_count, "我直接说身份：做视频号团购到店获客，不是平台官方，也不是催您马上办理。"
        if intent == "加微信/发资料":
            if "怎么" in clean or "哪里" in clean:
                return turn_count, "短信或微信都可以，您看哪种方便？我只发一份案例资料。"
            if turn_count > 0:
                return turn_count, "可以，我按您方便的方式发资料，不在电话里多占时间。"
        if intent == "听不清/澄清" and turn_count > 0:
            return turn_count, "我再说短一点：做视频号团购，帮门店多拿到店客户。"
        if intent == "合作咨询" and turn_count > 0:
            return turn_count, "流程很简单：先看门店品类，再定团购套餐，小范围测试有效果再放大。"
        if intent == "低信息确认" and turn_count > 0:
            return turn_count, "可以的话我就说重点，不方便我就不打扰。"
        if intent == "需求探索" and turn_count > 0:
            return turn_count, "如果您方便，我可以先发一份案例资料，您看完再决定。"
        return turn_count, _build_reply(text, intent, "您的门店")

    def _append_conversation_turn(self, customer_text: str, assistant_reply: str) -> None:
        self._call_history.append({"role": "user", "content": customer_text.strip()})
        self._call_history.append({"role": "assistant", "content": assistant_reply.strip()})
        self._conversation_history.append({"role": "user", "content": customer_text.strip()})
        self._conversation_history.append({"role": "assistant", "content": assistant_reply.strip()})
        if len(self._conversation_history) > 12:
            del self._conversation_history[: len(self._conversation_history) - 12]

    def _drain_latest_customer_text(self, generation: int, text: str) -> tuple[int, str]:
        latest_generation = generation
        latest_text = text
        while True:
            try:
                latest_generation, latest_text = self.customer_texts.get_nowait()
            except queue.Empty:
                return latest_generation, latest_text

    def cancel_pending_speech(self, detail: str, source: str, rms: int | None = None) -> int:
        now = time.monotonic()
        with self.speech_state_lock:
            active_jobs_at_start = self.speech_jobs
            was_speaking = self.speaking_event.is_set() or active_jobs_at_start > 0
        with self.generation_lock:
            self.speech_generation += 1
            generation = self.speech_generation
        self.interrupt_event.set()
        drained = False
        deadline = now + 0.2
        while time.monotonic() < deadline:
            with self.speech_state_lock:
                active_jobs = self.speech_jobs
            if active_jobs <= 0:
                drained = True
                break
            time.sleep(0.01)
        with self.speech_state_lock:
            remaining_jobs = self.speech_jobs
            if remaining_jobs > 0:
                self.speech_jobs = 0
            self.speaking_event.clear()
        if was_speaking and (remaining_jobs > 0 or drained):
            self.logger.emit(
                "barge_playback_drained",
                callId=self.call_id,
                source=source,
                generation=generation,
                drained=drained,
                remainingJobs=remaining_jobs,
                waitMs=int((time.monotonic() - now) * 1000),
            )
            self._flight_event(
                "playback_cleared",
                source=source,
                generation=generation,
                drained=drained,
                remainingJobs=remaining_jobs,
                waitMs=int((time.monotonic() - now) * 1000),
            )
        if was_speaking and now - self._last_barge_at > 0.8:
            self._last_barge_at = now
            fields: dict[str, Any] = {
                "callId": self.call_id,
                "detail": detail,
                "source": source,
                "generation": generation,
            }
            if rms is not None:
                fields["rms"] = rms
            self.logger.emit("barge_in", **fields)
            self._flight_event("barge_in", source=source, generation=generation, rms=rms)
            self.logger.emit(
                "barge_recovery_ready",
                callId=self.call_id,
                source=source,
                generation=generation,
                waitMs=int((time.monotonic() - now) * 1000),
                detail="已停止当前 AI 语音，恢复监听客户本轮问题。",
            )
        elif not was_speaking:
            self.logger.emit(
                "turn_generation_advanced",
                callId=self.call_id,
                source=source,
                generation=generation,
                detail="客户新一轮输入到达，更新回复代次；当前没有正在播放的 AI 语音。",
            )
        return generation

    def _speak(self, text: str, reason: str, generation: int, close_after: bool = False) -> None:
        if self.stop_event.is_set():
            return
        # 【审计A3】Pipeline 侧先登记 job 但不置位 speaking，等拿到首个 TTS 音频块再置位，
        # 避免 TTS 连接失败时状态卡在 SPEAKING。
        self._mark_speech_job_started(set_speaking=False)
        with self.generation_lock:
            if self.speech_generation == generation:
                self.interrupt_event.clear()
        if self._speech_is_obsolete(generation):
            self.logger.emit(
                "tts_interrupted",
                callId=self.call_id,
                reason=reason,
                phase="queued",
                sentBytes=0,
                totalBytes=0,
                generation=generation,
            )
            self._mark_speech_job_finished()
            return
        start = time.perf_counter()
        playback_started = False
        first_audio_ms = 0
        total_bytes = 0
        sent = 0
        pending = b""
        next_frame_at: float | None = None
        playback_lag_events = 0
        try:
            with self.playback_lock:
                for audio_chunk in iter_tts_pcm_chunks(text, self.config):
                    if not audio_chunk:
                        continue
                    total_bytes += len(audio_chunk)
                    if self._speech_is_obsolete(generation):
                        break
                    if not playback_started:
                        first_audio_ms = int((time.perf_counter() - start) * 1000)
                        playback_started = True
                        # 【审计A3】拿到首个 TTS 音频块后才真正进入 SPEAKING。
                        self.speaking_event.set()
                        self.logger.emit(
                            "tts_start",
                            callId=self.call_id,
                            reason=reason,
                            text=text,
                            bytes=total_bytes,
                            synthMs=first_audio_ms,
                            firstAudioMs=first_audio_ms,
                            voice=self.config.tts_voice_name,
                            voiceType=self.config.tts_voice_type,
                            model=self.config.tts_model,
                            streaming=_is_qwen_realtime_model(self.config.tts_model),
                            generation=generation,
                        )
                        self._flight_event(
                            "tts_start",
                            reason=reason,
                            text=text,
                            firstAudioMs=first_audio_ms,
                            voiceType=self.config.tts_voice_type,
                            model=self.config.tts_model,
                            generation=generation,
                        )
                    pending += audio_chunk
                    while len(pending) >= PCM_FRAME_BYTES:
                        if self.stop_event.is_set() or self._speech_is_obsolete(generation):
                            break
                        frame = pending[:PCM_FRAME_BYTES]
                        pending = pending[PCM_FRAME_BYTES:]
                        next_frame_at, playback_lag_events = self._send_audio_frame_at_cadence(
                            frame,
                            next_frame_at,
                            playback_lag_events,
                            reason,
                            generation,
                        )
                        sent += len(frame)
                    if self.stop_event.is_set() or self._speech_is_obsolete(generation):
                        break
                if pending and not self.stop_event.is_set() and not self._speech_is_obsolete(generation):
                    padded_pending = pending.ljust(PCM_FRAME_BYTES, b"\x00")
                    next_frame_at, playback_lag_events = self._send_audio_frame_at_cadence(
                        padded_pending,
                        next_frame_at,
                        playback_lag_events,
                        reason,
                        generation,
                    )
                    sent += len(pending)
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("tts_error", callId=self.call_id, text=text, error=str(exc))
            self._mark_speech_job_finished()
            # 【审计A4】TTS 失败不再静默吞掉：走降级链（整段合成→固定兜底句），
            # 且必须保留 close_after 语义——原分支丢 close_after 导致电话装死不挂。
            self._speak_tts_fallback(text, reason, generation, close_after, playback_started)
            return
        if not playback_started or self._speech_is_obsolete(generation):
            self.logger.emit(
                "tts_interrupted",
                callId=self.call_id,
                reason=reason,
                phase="playback" if playback_started else "synthesis",
                sentBytes=sent,
                totalBytes=total_bytes,
                synthMs=first_audio_ms or int((time.perf_counter() - start) * 1000),
                generation=generation,
            )
            self._mark_speech_job_finished()
            if close_after:
                self._close_after_terminal_reply("customer_rejected_interrupted")
            return
        interrupted = self._speech_is_obsolete(generation)
        self._mark_speech_job_finished()
        with self.generation_lock:
            if self.speech_generation == generation:
                self.interrupt_event.clear()
        self.logger.emit(
            "tts_interrupted" if interrupted else "tts_done",
            callId=self.call_id,
            reason=reason,
            phase="playback" if playback_started else "queued",
            sentBytes=sent,
            totalBytes=total_bytes,
            firstAudioMs=first_audio_ms,
            generation=generation,
        )
        self._flight_event(
            "tts_interrupted" if interrupted else "tts_done",
            reason=reason,
            sentBytes=sent,
            totalBytes=total_bytes,
            firstAudioMs=first_audio_ms,
            generation=generation,
        )
        if close_after and not interrupted:
            self._close_after_terminal_reply("customer_rejected")
        elif not close_after and not interrupted:
            self._schedule_no_response_hangup(reason)

    def _speak_tts_fallback(
        self,
        text: str,
        reason: str,
        generation: int,
        close_after: bool,
        playback_started: bool,
    ) -> None:
        # 【审计A4】TTS 降级链：realtime TTS 失败 → 整段合成原句 → 固定兜底句。
        # 已播出一部分时不整段重播，只补固定兜底句，避免客户听到重复内容。
        played = False
        attempts: list[tuple[str, str]] = []
        if not playback_started:
            attempts.append(("full_text", text))
        attempts.append(("hold_text", TTS_FALLBACK_HOLD_TEXT))
        for phase, fallback_text in attempts:
            if self.stop_event.is_set() or self._speech_is_obsolete(generation):
                break
            try:
                pcm = self._synthesize_fallback_pcm(fallback_text)
            except Exception as exc:  # noqa: BLE001
                self.logger.emit(
                    "tts_fallback_error",
                    callId=self.call_id,
                    reason=reason,
                    phase=phase,
                    text=fallback_text,
                    error=str(exc),
                    generation=generation,
                )
                continue
            if self._play_fallback_pcm(pcm, f"tts_fallback_{phase}", generation):
                played = True
                self.logger.emit(
                    "tts_fallback_used",
                    callId=self.call_id,
                    reason=reason,
                    phase=phase,
                    text=fallback_text,
                    generation=generation,
                    detail="TTS 主链路失败，已用降级链播出回复，避免本轮无声消失。",
                )
                break
        if close_after:
            # 【审计A4】收尾句无论降级成败都必须挂断，绝不让电话装死不挂。
            self._close_after_terminal_reply("customer_rejected_tts_fallback" if played else "tts_failed_close")
        elif played and not self._speech_is_obsolete(generation):
            self._schedule_no_response_hangup(reason)

    def _synthesize_fallback_pcm(self, text: str) -> bytes:
        # 【审计A4】优先整段合成；整段合成不可用（如仅配置 realtime 模型）时再试一次流式合成。
        try:
            return synthesize_tts_pcm(text, self.config)
        except Exception:  # noqa: BLE001
            chunks = bytearray()
            for chunk in iter_tts_pcm_chunks(text, self.config):
                if chunk:
                    chunks.extend(chunk)
            if not chunks:
                raise RuntimeError("TTS 降级合成未返回音频。")
            return bytes(chunks)

    def _play_fallback_pcm(self, pcm: bytes, reason: str, generation: int) -> bool:
        # 【审计A4】把降级合成好的整段 PCM 按 20ms 节拍播出。
        if not pcm or self.stop_event.is_set() or self._speech_is_obsolete(generation):
            return False
        self._mark_speech_job_started()
        sent = 0
        next_frame_at: float | None = None
        lag_events = 0
        try:
            with self.playback_lock:
                offset = 0
                while offset < len(pcm):
                    if self.stop_event.is_set() or self._speech_is_obsolete(generation):
                        break
                    frame = pcm[offset : offset + PCM_FRAME_BYTES]
                    offset += PCM_FRAME_BYTES
                    if len(frame) < PCM_FRAME_BYTES:
                        frame = frame.ljust(PCM_FRAME_BYTES, b"\x00")
                    next_frame_at, lag_events = self._send_audio_frame_at_cadence(
                        frame,
                        next_frame_at,
                        lag_events,
                        reason,
                        generation,
                    )
                    sent += len(frame)
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("tts_fallback_play_error", callId=self.call_id, reason=reason, error=str(exc))
        finally:
            self._mark_speech_job_finished()
        return sent > 0

    def _send_audio_frame_at_cadence(
        self,
        frame: bytes,
        next_frame_at: float | None,
        lag_events: int,
        reason: str,
        generation: int,
    ) -> tuple[float, int]:
        now = time.perf_counter()
        if next_frame_at is None or next_frame_at < now - PCM_FRAME_SECONDS * 2:
            if next_frame_at is not None and lag_events < 5:
                lag_ms = int((now - next_frame_at) * 1000)
                self.logger.emit(
                    "tts_playback_lag",
                    callId=self.call_id,
                    reason=reason,
                    lagMs=lag_ms,
                    generation=generation,
                )
                lag_events += 1
            next_frame_at = now
        wait_seconds = next_frame_at - now
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        scaled_frame = _scale_pcm16(frame, self.config.tts_gain)
        if self._audio_capture:
            self._audio_capture.write_outbound_raw(scaled_frame)
        processed_frame = self._audio_quality.process(scaled_frame)
        self._audio_quality_frame_count += 1
        if self.config.audio_quality_enabled and self._audio_quality_frame_count % 250 == 0:
            raw_stats = analyze_pcm16(scaled_frame)
            processed_stats = analyze_pcm16(processed_frame)
            self.logger.emit(
                "audio_quality_sample",
                callId=self.call_id,
                generation=generation,
                rawRms=raw_stats.rms,
                rawPeak=raw_stats.peak,
                rawClipped=raw_stats.clipped,
                processedRms=processed_stats.rms,
                processedPeak=processed_stats.peak,
                processedClipped=processed_stats.clipped,
            )
        if self._audio_capture:
            self._audio_capture.write_outbound(processed_frame)
        try:
            self._send_frame(AUDIO_SOCKET_KIND_AUDIO, processed_frame)
        except Exception as exc:  # noqa: BLE001
            self._close_after_socket_write_error("tts_playback", exc)
            raise
        self._last_outbound_audio_at = time.monotonic()
        return next_frame_at + PCM_FRAME_SECONDS, lag_events

    def _read_frame(self) -> tuple[int, bytes]:
        header = _read_exact(self.conn, 3)
        frame_type, payload_length = struct.unpack("!BH", header)
        payload = _read_exact(self.conn, payload_length) if payload_length else b""
        return frame_type, payload

    def _send_frame(self, frame_type: int, payload: bytes = b"") -> None:
        if len(payload) > 65535:
            raise AudioSocketProtocolError("AudioSocket payload too large.")
        packet = struct.pack("!BH", frame_type, len(payload)) + payload
        with self.send_lock:
            self.conn.sendall(packet)

    def _speech_is_obsolete(self, generation: int) -> bool:
        with self.generation_lock:
            return self.stop_event.is_set() or self.interrupt_event.is_set() or self.speech_generation != generation

    def _mark_speech_job_started(self, *, set_speaking: bool = True) -> None:
        start_watchdog = False
        with self.speech_state_lock:
            self.speech_jobs += 1
            self._speech_job_last_change_at = time.monotonic()
            if set_speaking:
                self.speaking_event.set()
            if not self._speech_job_watchdog_started:
                self._speech_job_watchdog_started = True
                start_watchdog = True
        # 评审修复3：全会话只起一个周期性看门狗线程，按"距最后一次 start/finish 变化超过30s"判定卡死，
        # 避免 job A 卡死后被 job B 的 start/finish 活动掩护而永不回收。
        if start_watchdog:
            threading.Thread(
                target=self._speech_job_watchdog,
                name="ai-acq-speech-job-watchdog",
                daemon=True,
            ).start()

    def _mark_speech_job_finished(self) -> None:
        with self.speech_state_lock:
            self.speech_jobs = max(0, self.speech_jobs - 1)
            self._speech_job_last_change_at = time.monotonic()
            if self.speech_jobs == 0:
                self.speaking_event.clear()

    def _speech_job_watchdog(self) -> None:
        # 评审修复3：周期性检查——仅当 speech_jobs>0 且距最后一次 start/finish 变化超过最大存活时间才强制清零。
        while not self.stop_event.is_set():
            time.sleep(SPEECH_JOB_WATCHDOG_INTERVAL_SECONDS)
            if self.stop_event.is_set():
                return
            with self.speech_state_lock:
                if self.speech_jobs <= 0:
                    continue
                if time.monotonic() - self._speech_job_last_change_at < SPEECH_JOB_MAX_LIFETIME_SECONDS:
                    continue
                stuck_jobs = self.speech_jobs
                self.speech_jobs = 0
                self._speech_job_last_change_at = time.monotonic()
                self.speaking_event.clear()
            self.logger.emit(
                "speech_job_watchdog_reset",
                callId=self.call_id,
                stuckJobs=stuck_jobs,
                maxSeconds=SPEECH_JOB_MAX_LIFETIME_SECONDS,
                detail="speech job 超过最大存活时间无 start/finish 变化，已强制清零并回到 LISTENING。",
            )

    def _close_after_terminal_reply(self, reason: str) -> None:
        self._intentional_close_reason = reason
        self.logger.emit("call_closing", callId=self.call_id, reason=reason)
        self.stop_event.set()
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _start_audio_capture(self) -> None:
        if not self.call_id or self._audio_capture:
            return
        try:
            if self.config.flight_recorder_enabled:
                capture_audio = self.config.flight_audio_capture_enabled or self.config.debug_audio_capture_enabled
                self._flight_recorder = RealtimeFlightRecorder(
                    self.call_id,
                    self.config.flight_recorder_dir,
                    capture_audio=capture_audio,
                )
                self._audio_capture = self._flight_recorder
            elif self.config.debug_audio_capture_enabled:
                self._audio_capture = CallAudioCapture(self.call_id, self.config.debug_audio_capture_dir)
            else:
                return
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("audio_capture_error", callId=self.call_id, error=str(exc))
            return
        if self._flight_recorder:
            self.logger.emit(
                "flight_recorder_started",
                callId=self.call_id,
                flightRoot=str(self._flight_recorder.call_root),
                tracePath=str(self._flight_recorder.trace_path),
                captureAudio=self._flight_recorder.capture_audio,
                detail="本通电话已开启飞行记录仪，用于对齐真实音频、VAD、ASR、回复和播放耗时。",
            )
        else:
            self.logger.emit(
                "audio_capture_started",
                callId=self.call_id,
                inboundPath=str(self._audio_capture.inbound_path),
                outboundPath=str(self._audio_capture.outbound_path),
            )

    def _stop_audio_capture(self) -> None:
        if not self._audio_capture:
            return
        try:
            paths = self._audio_capture.close()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("audio_capture_error", callId=self.call_id, error=str(exc))
            self._audio_capture = None
            return
        self.logger.emit("audio_capture_saved", callId=self.call_id, **paths)
        self._audio_capture = None
        self._flight_recorder = None


class OmniAudioSocketCallSession(AudioSocketCallSession):
    def __init__(self, conn: socket.socket, peer: tuple[str, int], config: BridgeConfig, logger: JsonlEventLogger) -> None:
        super().__init__(conn, peer, config, logger)
        self._omni: OmniRealtimeConversation | None = None
        self._omni_downsample_state = _PcmDownsampleState()
        self._omni_lock = threading.Lock()
        self._omni_generation = 0
        self._omni_response_id = ""
        self._omni_cancelled_response_ids: set[str] = set()
        self._omni_reply_parts: list[str] = []
        self._omni_pending_audio = b""
        self._omni_next_frame_at: float | None = None
        self._omni_playback_lag_events = 0
        self._omni_first_audio_ms = 0
        self._omni_audio_sent = 0
        self._omni_audio_total = 0
        self._omni_response_started_at = 0.0
        self._omni_tts_started = False
        self._omni_session_ready = False
        self._omni_closed = False
        self._omni_pipeline_fallback = False
        self._omni_unavailable_closing = False
        self._omni_barge_collecting = False
        self._omni_barge_started_at = 0.0
        self._omni_barge_last_voice_at = 0.0
        self._omni_barge_forced_response_until = 0.0
        self._omni_barge_forced_audio_started = False
        self._omni_barge_forced_requested = False
        self._omni_barge_server_stopped = False
        self._omni_barge_server_committed = False
        self._omni_barge_recovery_generation = 0
        self._omni_barge_last_text = ""
        # 【审计A1】Omni 播放帧有界队列 + 专职播放线程：dashscope websocket 回调线程只解码入队，
        # 由播放线程按 20ms 节拍写 AudioSocket，避免回调线程被播放节拍阻塞导致心跳超时/打断滞后。
        self._omni_play_queue: queue.Queue[tuple[str, int, str, Any]] = queue.Queue(maxsize=500)
        self._omni_playback_thread = threading.Thread(
            target=self._omni_playback_worker,
            name="ai-acq-omni-playback",
            daemon=True,
        )
        self._omni_dropped_frames = 0
        self._omni_drop_log_count = 0
        # 【审计A5】当前是否有活跃 response：response_id 为空的音频 delta 只在活跃期内接受。
        self._omni_response_active = False
        self._human_speech_confirmed = False
        self._last_remote_speech_started_at = 0.0
        self._call_screening_seen = False
        self._call_screening_answered = False
        self._call_screening_hangup_generation = 0
        self._no_response_hangup_generation = 0
        self._no_response_hangup_active = False
        self._system_prompt_seen = False
        self._opening_started = False
        self._last_remote_audio_at = 0.0
        self._omni_pending_customer_text = ""
        self._omni_pending_signal = ""
        self._last_omni_reply = ""

    def run(self) -> None:
        self.conn.settimeout(1.0)
        self.logger.emit(
            "socket_connected",
            peer=f"{self.peer[0]}:{self.peer[1]}",
            voice=self.config.omni_voice,
            mode="omni",
        )
        try:
            if not self._await_call_uuid():
                return
            self.logger.emit(
                "call_connected",
                callId=self.call_id,
                peer=f"{self.peer[0]}:{self.peer[1]}",
                voice=self.config.omni_voice,
                mode="omni",
            )
            self._flight_event("call_connected", peer=f"{self.peer[0]}:{self.peer[1]}", mode="omni")
            self._start_startup_keepalive()
            # 【审计A1】启动专职 Omni 播放线程（pipeline 降级时空转等待，无副作用）。
            self._omni_playback_thread.start()
            requested_route = self._context_conversation_route()
            if requested_route == "pipeline":
                self._enable_omni_pipeline_fallback(
                    "requested_pipeline_route",
                    RuntimeError("本通电话在前端选择稳定分段语音 Pipeline。"),
                )
            else:
                circuit_reason = omni_route_unavailable_reason()
                if circuit_reason:
                    self._enable_omni_pipeline_fallback("omni_circuit_open", RuntimeError(circuit_reason))
                else:
                    try:
                        self._start_omni()
                    except Exception as exc:  # noqa: BLE001
                        mark_omni_route_unavailable(str(exc))
                        self._enable_omni_pipeline_fallback("omni_start", exc)
            self._start_omni_sidecar_asr()
            threading.Thread(target=self._speak_opening_after_grace, daemon=True).start()
            self._read_loop()
        except Exception as exc:  # noqa: BLE001
            if self._is_intentional_socket_close(exc):
                self.logger.emit(
                    "call_closed",
                    callId=self.call_id,
                    reason=self._intentional_close_reason,
                    detail="客户明确结束后系统主动关闭 AudioSocket。",
                    mode="omni",
                )
            else:
                self.logger.emit("call_error", callId=self.call_id, error=str(exc), mode="omni")
        finally:
            self.stop_event.set()
            self.interrupt_event.set()
            self._record_learning_summary()
            self._stop_startup_keepalive()
            self._stop_asr()
            self._stop_omni()
            self._stop_audio_capture()
            try:
                self.conn.close()
            except OSError:
                pass
            self.logger.emit("call_disconnected", callId=self.call_id, mode="omni")

    def _start_omni(self) -> None:
        runtime_config = get_runtime_ai_config()
        if not runtime_config.dashscope_api_key:
            raise AudioSocketProtocolError("缺少 DASHSCOPE_API_KEY，不能启动 Qwen Omni Realtime。")
        dashscope.api_key = runtime_config.dashscope_api_key
        callback = CallOmniCallback(self)
        self._omni = OmniRealtimeConversation(
            model=self.config.omni_model,
            callback=callback,
            url=self.config.omni_url,
            workspace=self.config.workspace,
        )
        self._omni.connect()
        self._omni_closed = False
        self._omni.update_session(
            output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],
            voice=self.config.omni_voice,
            enable_input_audio_transcription=True,
            input_audio_transcription_model=self.config.omni_input_transcription_model,
            enable_turn_detection=True,
            turn_detection_type="semantic_vad",
            turn_detection_threshold=0.5,
            turn_detection_silence_duration_ms=650,
            turn_detection_param={"interrupt_response": True, "create_response": False},
            instructions=build_video_group_buying_sales_instructions(),
        )

    def _enable_omni_pipeline_fallback(self, source: str, exc: Exception) -> None:
        with self._omni_lock:
            if self._omni_pipeline_fallback:
                return
            self._omni_pipeline_fallback = True
            self._omni = None
            self._omni_closed = True
        self.logger.emit(
            "omni_start_failed_fallback",
            callId=self.call_id,
            source=source,
            error=str(exc),
            mode="omni",
            fallbackMode="pipeline",
            detail=(
                "本通电话前端选择稳定分段语音 Pipeline，当前 Omni bridge 已按单通话切到本地 ASR+LLM+TTS pipeline。"
                if source == "requested_pipeline_route"
                else "Omni 实时连接启动失败，本通电话自动降级到本地 ASR+LLM+TTS pipeline，避免接通后直接挂断。"
            ),
        )
        self._flight_event("route_fallback", source=source, effectiveRoute="pipeline", error=str(exc))
        try:
            if not self._turn_thread.is_alive():
                self._turn_thread.start()
        except RuntimeError:
            pass

    def _context_conversation_route(self) -> str:
        value = str(
            self._call_context.get("effectiveRoute")
            or self._call_context.get("requestedRoute")
            or ""
        ).strip().lower()
        if value in {"pipeline", "omni"}:
            return value
        return ""

    def _is_omni_pipeline_fallback(self) -> bool:
        with self._omni_lock:
            return self._omni_pipeline_fallback

    def _start_omni_sidecar_asr(self) -> None:
        try:
            self._start_asr()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit(
                "omni_sidecar_asr_error",
                callId=self.call_id,
                error=str(exc),
                detail="Omni 旁路实时 ASR 启动失败，将退回仅等待 Omni final 转写。",
            )
            return
        self.logger.emit(
            "omni_sidecar_asr_started",
            callId=self.call_id,
            model=self.config.asr_model,
            detail="已启动旁路实时 ASR，用于快速断句和低延迟回复兜底。",
        )

    def _stop_omni(self) -> None:
        if not self._omni:
            return
        try:
            self._omni.close()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("omni_close_error", callId=self.call_id, error=str(exc))
        self._omni = None

    def handle_omni_closed(self, close_status_code: object, close_msg: object) -> None:
        with self._omni_lock:
            self._omni_closed = True
            self._omni = None
            already_closing = self._omni_unavailable_closing
            self._omni_unavailable_closing = True
        # 【审计A3】Omni 断开后 response.done 永远不会到达：强制清零 speech_jobs 并清 speaking_event，
        # 同时清空播放队列，防止卡死在 SPEAKING 回不到 LISTENING。
        with self.speech_state_lock:
            self.speech_jobs = 0
            self.speaking_event.clear()
        self._clear_omni_play_queue("omni_closed")
        if self.stop_event.is_set() or already_closing:
            return
        self.logger.emit(
            "omni_unavailable",
            callId=self.call_id,
            code=str(close_status_code),
            message=str(close_msg),
            detail="Omni 实时连接已关闭，停止继续写入音频并准备结束本次通话。",
        )
        threading.Thread(target=self._close_after_omni_unavailable, daemon=True).start()

    def _close_after_omni_unavailable(self) -> None:
        with self.generation_lock:
            self.speech_generation += 1
            generation = self.speech_generation
        self.interrupt_event.set()
        self._speak("这边线路有点不稳，我稍后再联系您。", "omni_unavailable", generation, close_after=True)

    def _speak_opening_after_grace(self) -> None:
        if self._is_omni_pipeline_fallback():
            super()._speak_opening_after_grace()
            return
        grace = max(0.0, self.config.opening_grace_seconds)
        if grace and self.customer_activity_event.wait(grace):
            self.logger.emit("opening_deferred", callId=self.call_id, reason="remote_audio_detected", mode="omni")
            if not self._wait_for_remote_classification_before_opening("omni"):
                return
        if self._mark_opening_started():
            self.logger.emit("opening_start", callId=self.call_id, mode="omni", text=self.config.opening_text)
            if not self._is_omni_session_ready():
                with self.generation_lock:
                    generation = self.speech_generation
                self.logger.emit(
                    "omni_opening_local_fallback",
                    callId=self.call_id,
                    generation=generation,
                    detail="真人已接听但 Omni session 尚未 ready，先用本地实时 TTS 播短开场，避免电话里沉默。",
                )
                threading.Thread(
                    target=self._speak,
                    args=(self.config.opening_text, "omni_opening_local_fallback", generation),
                    daemon=True,
                ).start()
                return
            self._request_omni_response(f"电话刚接通。只说这一句，不要改写，不要加问句，不要展开：{self.config.opening_text}")

    def mark_omni_session_ready(self) -> None:
        with self._omni_lock:
            self._omni_session_ready = True

    def _is_omni_session_ready(self) -> bool:
        with self._omni_lock:
            return self._omni_session_ready

    def _request_omni_response(self, instruction: str) -> None:
        if not self._omni or self.stop_event.is_set():
            return
        try:
            self._omni.create_response(
                instructions=f"{build_video_group_buying_sales_instructions()}\n{instruction}",
                output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("omni_response_request_error", callId=self.call_id, error=str(exc))

    def _respond_to_call_screening(self, text: str, *, source: str) -> None:
        self._call_screening_seen = True
        if self._call_screening_answered or self.stop_event.is_set():
            return
        self._call_screening_answered = True
        self.logger.emit(
            "call_screening_detected",
            callId=self.call_id,
            text=text,
            source=source,
            detail="Omni 识别到电话助理/秘书提示，只说明身份和来电原因，等待真人转接。",
        )
        with self._omni_lock:
            self._omni_pending_customer_text = text
            self._omni_pending_signal = "call_screening"
        self._request_omni_response(build_omni_turn_instruction(text, "call_screening"))
        self._schedule_call_screening_hangup(source)

    def note_asr_partial_text(self, text: str) -> None:
        if self._is_omni_pipeline_fallback():
            super().note_asr_partial_text(text)
            return
        clean = " ".join(text.strip().split())
        if not clean:
            return
        self._note_customer_activity("omni_sidecar_asr_partial", text=clean)
        with self._omni_lock:
            if self._omni_barge_collecting:
                self._omni_barge_last_text = clean
        endpoint = self._turn_manager.on_partial_text(clean) if self._turn_manager else None
        should_commit = endpoint.should_commit if endpoint else should_commit_stable_asr_partial(clean)
        if not should_commit:
            with self.asr_partial_lock:
                if self._asr_partial_text and clean != self._asr_partial_text:
                    self._asr_partial_generation += 1
                    self._asr_partial_text = ""
            self.logger.emit(
                "turn_waiting_final",
                callId=self.call_id,
                text=clean,
                provider="qwen_asr_sidecar",
                reason=endpoint.reason if endpoint else "incomplete_or_nonactionable_partial",
                detail="旁路 ASR partial 还不够完整，继续等 final 或更稳定的短句。",
            )
            return
        with self.asr_partial_lock:
            self._asr_partial_generation += 1
            generation = self._asr_partial_generation
            self._asr_partial_text = clean
        delay = endpoint.wait_seconds if endpoint else _asr_partial_stable_delay_seconds(clean)
        self.logger.emit(
            "turn_endpoint_candidate",
            callId=self.call_id,
            text=clean,
            provider="qwen_asr_sidecar",
            waitMs=int(delay * 1000),
            signal=endpoint.signal if endpoint else classify_realtime_call_input(clean),
            detail="旁路 ASR 已拿到可回答短句；若 Omni final 未到，将先触发回复。",
        )
        self._flight_event(
            "turn_endpoint_candidate",
            text=clean,
            waitMs=int(delay * 1000),
            signal=endpoint.signal if endpoint else classify_realtime_call_input(clean),
            source="omni_sidecar_asr_partial",
        )
        threading.Thread(
            target=self._commit_omni_sidecar_asr_partial_after_delay,
            args=(generation, clean, delay),
            name="ai-acq-omni-sidecar-asr-partial-turn",
            daemon=True,
        ).start()

    def commit_asr_final_text(self, text: str) -> None:
        if self._is_omni_pipeline_fallback():
            super().commit_asr_final_text(text)
            return
        self._cancel_pending_asr_partial_turn("omni_sidecar_asr_final")
        self.logger.emit(
            "turn_endpoint_final",
            callId=self.call_id,
            text=text,
            provider="qwen_asr_sidecar",
            detail="旁路 ASR final 已到达，先触发 Omni 回复，避免等待 Omni 自身 final。",
        )
        self._flight_event("turn_endpoint_final", text=text, source="omni_sidecar_asr_final", provider="qwen_asr_sidecar")
        self.handle_omni_transcription(text, provider="qwen_asr_sidecar", source="omni_sidecar_asr_final")

    def _commit_omni_sidecar_asr_partial_after_delay(self, generation: int, text: str, delay: float) -> None:
        time.sleep(delay)
        if self.stop_event.is_set():
            return
        with self.asr_partial_lock:
            if generation != self._asr_partial_generation or text != self._asr_partial_text:
                return
        if not should_commit_stable_asr_partial(text):
            return
        self.logger.emit(
            "asr_partial_stable",
            callId=self.call_id,
            text=text,
            provider="qwen_asr_sidecar",
            waitMs=int(delay * 1000),
            detail="Omni final 尚未到达，旁路 ASR 短句已稳定，先接话避免客户空等。",
        )
        self.handle_omni_transcription(text, provider="qwen_asr_sidecar", source="omni_sidecar_asr_partial_stable")

    def handle_omni_speech_started(self) -> None:
        now = time.monotonic()
        self._note_customer_activity("omni_speech_started", now=now)
        if self.speaking_event.is_set():
            self.cancel_pending_speech("Omni 检测到客户插话，停止当前语音回复。", source="omni_vad")
            self._release_omni_playback_after_barge("omni_vad", now=now)
            return
        if now - self._last_remote_speech_started_at > 1.5:
            self._last_remote_speech_started_at = now
            self.logger.emit(
                "remote_speech_started",
                callId=self.call_id,
                detail="线路已接通并检测到对端声音，等待最终识别文本确认是真人还是电话助理。",
                provider="qwen_omni",
            )

    def handle_omni_input_buffer_event(self, event_type: str, response: dict[str, Any]) -> None:
        fields: dict[str, Any] = {"callId": self.call_id, "event": event_type, "provider": "qwen_omni"}
        item_id = response.get("item_id")
        if item_id:
            fields["itemId"] = item_id
        with self._omni_lock:
            if self._omni_barge_collecting:
                if event_type == "input_audio_buffer.speech_stopped":
                    self._omni_barge_server_stopped = True
                if event_type == "input_audio_buffer.committed":
                    self._omni_barge_server_committed = True
        self.logger.emit("omni_input_buffer_event", **fields)

    def handle_omni_transcription(
        self,
        text: str,
        *,
        provider: str = "qwen_omni",
        source: str = "omni_transcription",
    ) -> None:
        clean = " ".join(text.strip().split())
        if not clean:
            return
        self._note_customer_activity(source, text=clean)
        # 【审计A7】Omni/旁路 ASR 的 final 文本入口先走意向旁路（去重之前），防止强意向漏记。
        self._capture_intent_bypass(clean, f"{source}_bypass")
        raw_clean = clean
        signal = classify_realtime_call_input(clean)
        if signal == "system_prompt":
            human_tail = extract_human_text_after_system_prompt(clean)
            if human_tail:
                self.logger.emit(
                    "system_prompt_stripped",
                    callId=self.call_id,
                    text=raw_clean,
                    strippedText=human_tail,
                    provider=provider,
                    detail="ASR 同一句里包含系统提示和真人客户语音，已只剥离系统提示并继续回复真人内容。",
                )
                clean = human_tail
                signal = classify_realtime_call_input(clean)
                if signal == "system_prompt":
                    signal = "human_speech"
        human_confirmed_before = self._human_speech_confirmed
        self.handle_answer_text(clean, is_final=True)
        duplicate_turn = self._is_recent_committed_customer_text(clean)
        with self._omni_lock:
            barge_collecting = self._omni_barge_collecting
        if duplicate_turn:
            if barge_collecting:
                with self._omni_lock:
                    self._omni_barge_last_text = clean
                    self._omni_barge_last_voice_at = time.monotonic()
                self.logger.emit(
                    "customer_turn_duplicate_ignored",
                    callId=self.call_id,
                    text=clean,
                    provider=provider,
                    source=source,
                    detail="打断恢复期间只收到重复转写，继续等待恢复兜底，不能让 AI 静默。",
                )
                return
            self.logger.emit(
                "customer_turn_duplicate_ignored",
                callId=self.call_id,
                text=clean,
                provider=provider,
                source=source,
                detail="同一句客户话已经由更快的 ASR/Omni 通道触发过回复，避免重复回答。",
            )
            return
        skip_response_after_forced_barge = False
        replace_forced_barge_response = False
        with self._omni_lock:
            self._omni_barge_collecting = False
            if self._omni_barge_forced_response_until > time.monotonic():
                if self._omni_barge_forced_audio_started:
                    skip_response_after_forced_barge = True
                else:
                    replace_forced_barge_response = True
        asr_fields: dict[str, Any] = {"callId": self.call_id, "text": clean, "provider": provider, "signal": signal}
        if source != "omni_transcription":
            asr_fields["source"] = source
        if raw_clean != clean:
            asr_fields["rawText"] = raw_clean
        self.logger.emit("asr_final", **asr_fields)
        self.logger.emit(
            "turn_endpoint_final",
            callId=self.call_id,
            text=clean,
            provider=provider,
            source=source,
            detail="客户本轮说话已由实时 ASR 端点提交，可以触发回复。",
        )
        self._flight_event("turn_endpoint_final", text=clean, source=source, provider=provider)
        if signal == "system_prompt":
            if classify_answer_text(clean) == CallAnswerType.VOICEMAIL:
                self.logger.emit(
                    "voicemail_detected",
                    callId=self.call_id,
                    text=clean,
                    detail="识别到语音信箱/留言提示，直接挂断不留言。",
                )
                self.stop_event.set()
                return
            self._system_prompt_seen = True
            self.logger.emit(
                "system_prompt_ignored",
                callId=self.call_id,
                text=clean,
                detail="识别到运营商或手机系统提示，已忽略，不触发销售回复。",
            )
            return
        normalization = normalize_realtime_sales_text(clean)
        routed_clean = normalization.normalized_text
        if normalization.changed:
            self.logger.emit(
                "asr_sales_text_normalized",
                callId=self.call_id,
                text=clean,
                normalizedText=routed_clean,
                provider=provider,
                fixes=list(normalization.fixes),
                detail="实时 ASR 文本进入销售脑前已做高置信语境纠错，原始转写仍保留在 ASR 事件中。",
            )
        intent, _node = _classify_intent(routed_clean)
        stage = self._sales_fsm.update(routed_clean, intent, signal)
        stage_instruction = self._sales_fsm.get_stage_instruction()
        if signal in {"terminal_close", "rejection"}:
            if self._omni:
                try:
                    self._omni.cancel_response()
                except Exception as exc:  # noqa: BLE001
                    self.logger.emit("omni_cancel_error", callId=self.call_id, error=str(exc), source=signal)
            self.logger.emit(
                "terminal_close_detected",
                callId=self.call_id,
                text=clean,
                signal=signal,
                salesStage=stage.value,
                detail="客户已明确结束通话，直接短句收口并关闭电话。",
            )
            with self.generation_lock:
                self.speech_generation += 1
                generation = self.speech_generation
            self.interrupt_event.set()
            threading.Thread(target=self._speak, args=("好的，不打扰了，再见。", "terminal_close", generation, True), daemon=True).start()
            return
        first_human_after_screening = False
        if signal == "call_screening":
            self._call_screening_seen = True
            if self._call_screening_answered:
                self.logger.emit(
                    "call_screening_followup_ignored",
                    callId=self.call_id,
                    text=clean,
                    detail="电话助理后续等待提示已忽略，避免重复说明身份和来电原因。",
                )
                return
            self._call_screening_answered = True
            self.logger.emit(
                "call_screening_detected",
                callId=self.call_id,
                text=clean,
                detail="识别到电话助理/秘书提示，先说明身份和来电原因，等待真人转接。",
            )
            self._schedule_call_screening_hangup("omni_transcription")
        elif not human_confirmed_before:
            first_human_after_screening = self._call_screening_seen
            if not self._human_speech_confirmed:
                self._confirm_human_speech(clean, detail="已识别到真人客户语音，可以进入实时对话。")
        if signal != "call_screening":
            # 【审计A7】DB 写移出 websocket 回调线程，改为线程池异步执行。
            try:
                _INTENT_CAPTURE_EXECUTOR.submit(
                    self._record_realtime_intent_signal, routed_clean, intent, signal, source
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.emit("intent_capture_error", callId=self.call_id, text=routed_clean, error=str(exc))
        if skip_response_after_forced_barge:
            self.logger.emit(
                "barge_transcription_after_forced_response",
                callId=self.call_id,
                text=clean,
                detail="打断后已用提交的音频创建回复，这条转写只记录，不重复触发回复。",
            )
            return
        if replace_forced_barge_response and self._omni:
            try:
                self._omni.cancel_response()
            except Exception as exc:  # noqa: BLE001
                self.logger.emit("omni_cancel_error", callId=self.call_id, error=str(exc), source="barge_transcription")
            self.logger.emit(
                "barge_transcription_replaces_forced_response",
                callId=self.call_id,
                text=clean,
                detail="打断后的文字转写先于强制回复音频到达，改用文字转写生成更准确回复。",
            )
        history_snapshot = list(self._conversation_history)
        self._remember_committed_customer_text(clean)
        self.logger.emit(
            "turn_reply_preparing",
            callId=self.call_id,
            text=routed_clean,
            source=source,
            detail="客户本轮已提交给实时语音模型，准备生成回复。",
        )
        self._flight_event("turn_committed", text=routed_clean, source=source, provider=provider)
        self.logger.emit(
            "turn_llm_start",
            callId=self.call_id,
            text=routed_clean,
            intent=intent,
            signal=signal,
            salesStage=stage.value,
            historyTurns=len(history_snapshot),
            provider=provider,
            detail="客户本轮已进入 Omni 回复生成，等待首个音频块。",
        )
        with self._omni_lock:
            self._omni_pending_customer_text = clean
            self._omni_pending_signal = signal
            last_reply = self._last_omni_reply
        self._request_omni_response(
            build_omni_turn_instruction(
                clean,
                signal,
                recent_history=history_snapshot,
                first_human_after_screening=first_human_after_screening,
                last_reply=last_reply,
                stage_instruction=stage_instruction,
            ),
        )

    def _handle_audio(self, payload: bytes) -> None:
        if self._is_omni_pipeline_fallback():
            super()._handle_audio(payload)
            return
        if self._audio_capture:
            self._audio_capture.write_inbound(payload)
        rms = _pcm_rms(payload)
        now = time.monotonic()
        turn_audio = self._turn_audio_decision(rms, now, ai_speaking=self.speaking_event.is_set())
        self._emit_remote_audio_sample(rms, now)
        self._handle_answer_audio(rms, now)
        if (turn_audio and turn_audio.has_voice) or (not turn_audio and rms >= self.config.barge_rms_threshold):
            self._note_customer_activity("omni_remote_audio", now=now)
        if self.speaking_event.is_set() and self._omni_local_barge_ready():
            if rms >= self.config.barge_rms_threshold:
                self._loud_frames += 1
            else:
                self._loud_frames = 0
            if (
                (turn_audio and turn_audio.barge_in)
                or (not turn_audio and self._loud_frames >= self.config.barge_frames and now - self._last_barge_at > 0.8)
            ):
                self.cancel_pending_speech("客户插话，停止 Omni 语音回复。", source="omni_rms", rms=rms)
                self._release_omni_playback_after_barge("omni_rms", now=now)
        else:
            self._loud_frames = 0
        if self._omni and not self._omni_closed and payload:
            try:
                self._omni.append_audio(base64.b64encode(_upsample_pcm_8k_to_16k(payload)).decode("ascii"))
            except Exception as exc:  # noqa: BLE001
                if "already closed" in str(exc).lower():
                    self.handle_omni_closed("append_error", exc)
                else:
                    self.logger.emit("omni_audio_append_error", callId=self.call_id, error=str(exc))
        # 【审计A2】旁路 ASR 统一走带重建的安全发送。
        self._send_asr_audio_frame(payload)
        self._maybe_commit_omni_barge_turn(now, rms)

    def _omni_local_barge_ready(self) -> bool:
        with self._omni_lock:
            return self._omni_tts_started and self._omni_audio_sent >= OMNI_LOCAL_BARGE_MIN_SENT_BYTES

    def _release_omni_playback_after_barge(self, source: str, now: float | None = None) -> None:
        now = now or time.monotonic()
        with self.speech_state_lock:
            self.speech_jobs = 0
            self.speaking_event.clear()
        cancelled_response_id = ""
        with self._omni_lock:
            cancelled_response_id = self._omni_response_id
            if cancelled_response_id:
                self._omni_cancelled_response_ids.add(cancelled_response_id)
                self._omni_response_id = ""
            self._omni_pending_audio = b""
            self._omni_next_frame_at = None
            # 【审计A5】打断后不再有活跃 response，空 response_id 的残余音频将被严格丢弃。
            self._omni_response_active = False
            self._omni_barge_collecting = True
            self._omni_barge_started_at = now
            self._omni_barge_last_voice_at = now
            self._omni_barge_forced_requested = False
            self._omni_barge_server_stopped = False
            self._omni_barge_server_committed = False
            self._omni_barge_last_text = ""
            self._omni_barge_recovery_generation += 1
            recovery_generation = self._omni_barge_recovery_generation
            self._omni_drop_log_count = 0
        # 【审计A1】打断时清空播放队列，旧 generation/response 的剩余帧全部丢弃。
        self._clear_omni_play_queue(source)
        if self._omni:
            try:
                self._omni.cancel_response()
            except Exception as exc:  # noqa: BLE001
                self.logger.emit("omni_cancel_error", callId=self.call_id, error=str(exc), source=source)
        self._loud_frames = 0
        self.logger.emit(
            "barge_recovery_ready",
            callId=self.call_id,
            source=source,
            cancelledResponseId=cancelled_response_id,
            detail="已停止本地播放并恢复监听，等待客户本轮语音最终识别后再回复。",
        )
        threading.Thread(
            target=self._omni_barge_recovery_watchdog,
            args=(recovery_generation,),
            name="ai-acq-omni-barge-recovery-watchdog",
            daemon=True,
        ).start()

    def _maybe_commit_omni_barge_turn(self, now: float, rms: int) -> None:
        # 【审计A8】维持判定用低阈值 800（进入打断仍是 2200/6帧），客户说话声不需要一直很大才算"还在说"。
        if rms >= OMNI_BARGE_SUSTAIN_RMS_THRESHOLD:
            with self._omni_lock:
                if self._omni_barge_collecting:
                    self._omni_barge_last_voice_at = now
        self._commit_omni_barge_recovery("omni_rms_recovery", now=now)

    def _omni_barge_recovery_watchdog(self, generation: int) -> None:
        time.sleep(OMNI_BARGE_RECOVERY_WATCHDOG_SECONDS)
        if self.stop_event.is_set():
            return
        # 【审计A8】watchdog 到点时客户仍在说话则顺延恢复，等客户停顿后再接话（有最长顺延上限）。
        extend_deadline = time.monotonic() + OMNI_BARGE_RECOVERY_EXTEND_MAX_SECONDS
        while not self.stop_event.is_set() and time.monotonic() < extend_deadline:
            with self._omni_lock:
                if not self._omni_barge_collecting or generation != self._omni_barge_recovery_generation:
                    return
                last_voice_at = self._omni_barge_last_voice_at
            if time.monotonic() - last_voice_at >= OMNI_BARGE_RECOVERY_SILENCE_SECONDS:
                break
            time.sleep(0.1)
        if self.stop_event.is_set():
            return
        self._commit_omni_barge_recovery(
            "barge_recovery_watchdog",
            now=time.monotonic(),
            recovery_generation=generation,
        )

    def _commit_omni_barge_recovery(
        self,
        source: str,
        *,
        now: float,
        recovery_generation: int | None = None,
    ) -> bool:
        with self._omni_lock:
            collecting = self._omni_barge_collecting
            started_at = self._omni_barge_started_at
            last_voice_at = self._omni_barge_last_voice_at
            forced_requested = self._omni_barge_forced_requested
            current_generation = self._omni_barge_recovery_generation
            if recovery_generation is not None and recovery_generation != current_generation:
                return False
            if not collecting or forced_requested:
                return False
            elapsed = now - started_at
            silence = now - last_voice_at
            should_commit = elapsed >= OMNI_BARGE_RECOVERY_MIN_SECONDS and (
                silence >= OMNI_BARGE_RECOVERY_SILENCE_SECONDS
                or elapsed >= OMNI_BARGE_RECOVERY_MAX_SECONDS
            )
            if not should_commit:
                return False
            self._omni_barge_collecting = False
            self._omni_barge_forced_requested = True
            self._omni_barge_forced_response_until = now + OMNI_BARGE_FORCED_RESPONSE_SKIP_SECONDS
            self._omni_barge_forced_audio_started = False
            last_reply = self._last_omni_reply
            last_customer_text = self._omni_barge_last_text or self._omni_pending_customer_text
        if not last_customer_text:
            with self.asr_partial_lock:
                # 【审计A5】超过 5 秒的旧句不再重答（否则几十秒前的问题会"复活"），
                # 留空让 build_barge_recovery_instruction 走通用接话短句。
                if (
                    self._last_committed_customer_text
                    and now - self._last_committed_customer_at <= OMNI_BARGE_STALE_TEXT_MAX_SECONDS
                ):
                    last_customer_text = self._last_committed_customer_text
        if not self._omni or self.stop_event.is_set():
            return False
        self.logger.emit(
            "barge_turn_committed",
            callId=self.call_id,
            source=source,
            elapsedMs=int(elapsed * 1000),
            silenceMs=int(silence * 1000),
            detail="客户打断后短暂停顿，已在一秒内请求恢复回复；若随后转写到达会改用转写回复。",
        )
        self._request_omni_response(
            build_barge_recovery_instruction(
                list(self._conversation_history),
                last_customer_text=last_customer_text,
                last_assistant_reply=last_reply,
            )
        )
        return True

    def start_omni_response(self, response_id: str) -> None:
        with self._omni_lock:
            if response_id and response_id in self._omni_cancelled_response_ids:
                self.logger.emit("omni_stale_response_start_ignored", callId=self.call_id, responseId=response_id)
                return
        with self.generation_lock:
            self.speech_generation += 1
            generation = self.speech_generation
        with self._omni_lock:
            self._omni_generation = generation
            self._omni_response_id = response_id
            # 【审计A5】标记进入活跃 response 期，允许 response_id 为空的音频 delta 归属当前 response。
            self._omni_response_active = True
            self._omni_reply_parts = []
            self._omni_pending_audio = b""
            self._omni_next_frame_at = None
            self._omni_playback_lag_events = 0
            self._omni_first_audio_ms = 0
            self._omni_audio_sent = 0
            self._omni_audio_total = 0
            self._omni_response_started_at = time.perf_counter()
            self._omni_tts_started = False
            # 【审计A1】新 response 开始，重置播放队列的丢帧/日志限流计数。
            self._omni_dropped_frames = 0
            self._omni_drop_log_count = 0
        self.interrupt_event.clear()
        self._mark_speech_job_started()
        self.logger.emit("omni_response_start", callId=self.call_id, responseId=response_id, generation=generation)
        threading.Thread(
            target=self._omni_response_audio_watchdog,
            args=(generation, response_id),
            daemon=True,
        ).start()

    def _omni_response_audio_watchdog(self, generation: int, response_id: str) -> None:
        time.sleep(OMNI_FIRST_AUDIO_DEADLINE_SECONDS)
        with self._omni_lock:
            should_fallback = (
                self._omni_generation == generation
                and self._omni_response_id == response_id
                and not self._omni_tts_started
                and not self._omni_closed
            )
            pending_text = self._omni_pending_customer_text
            pending_signal = self._omni_pending_signal
        if not should_fallback or self.stop_event.is_set() or self._speech_is_obsolete(generation):
            return
        fallback_text = self._local_omni_timeout_reply(pending_text, pending_signal)
        with self._omni_lock:
            # 【审计A5】超时取消后该 response 不再活跃，迟到的空 response_id 音频会被丢弃。
            self._omni_response_active = False
        if self._omni:
            try:
                self._omni.cancel_response()
            except Exception as exc:  # noqa: BLE001
                self.logger.emit("omni_cancel_error", callId=self.call_id, error=str(exc), source="first_audio_watchdog")
        self._mark_speech_job_finished()
        with self.generation_lock:
            if self.speech_generation != generation:
                return
            self.speech_generation += 1
            fallback_generation = self.speech_generation
        self.interrupt_event.set()
        self.logger.emit(
            "omni_response_slow_fallback",
            callId=self.call_id,
            responseId=response_id,
            text=pending_text,
            signal=pending_signal,
            fallbackText=fallback_text,
            deadlineMs=int(OMNI_FIRST_AUDIO_DEADLINE_SECONDS * 1000),
            generation=fallback_generation,
            detail="实时模型超过首音频预算，已切到本地短句，避免电话里长时间沉默。",
        )
        threading.Thread(
            target=self._speak,
            args=(fallback_text, "omni_response_slow_fallback", fallback_generation),
            daemon=True,
        ).start()

    def _local_omni_timeout_reply(self, pending_text: str, pending_signal: str) -> str:
        signal = (pending_signal or "").strip()
        normalization = normalize_realtime_sales_text(pending_text or "")
        text = normalization.normalized_text
        if signal == "call_screening":
            return "您好，我这边做视频号团购到店获客，来电想确认门店微信同城曝光合作，麻烦转接负责人，谢谢。"
        if signal in {"identity_handoff", "human_greeting"}:
            return "您好，我在。我是做视频号团购到店获客的，来电是确认微信同城曝光这块。"
        if signal == "audio_issue":
            return "我短说：我是做视频号团购到店获客的，帮门店做套餐和微信同城曝光。"
        if signal == "repetition_complaint":
            return "我不重复。您想听费用、效果，还是和美团区别？"
        if signal == "direct_answer_only":
            return "不推资料。您直接问费用、效果或流程，我按问题答。"
        if signal in {"terminal_close", "rejection"}:
            return "好的，不打扰了，再见。"
        if normalization.has_fix("group_buying_package"):
            return "不是4G套餐，是团购套餐，就是客户线上下单、到店核销的优惠套餐。"
        if any(keyword in text for keyword in ["套餐", "介绍", "流程", "怎么合作", "说一下", "讲一下"]):
            return "套餐主要三块：看品类，设计团购券，再小范围测曝光、咨询和到店。"
        if any(keyword in text for keyword in ["费用", "价格", "收费", "要钱", "付费"]):
            return "这是付费服务，费用看套餐和投放节奏，不合适不建议做。"
        if any(keyword in text for keyword in ["美团", "抖音", "大众点评"]):
            return "美团偏搜索成交，视频号偏微信同城曝光和私域沉淀，是补充。"
        if any(keyword in text for keyword in ["效果", "客流", "到店", "保证", "保底"]):
            return "效果不能空口保底，只能先测曝光、咨询和到店数据。"
        return OMNI_NO_AUDIO_FALLBACK_TEXT

    def _is_omni_response_stale_locked(self, response_id: str) -> bool:
        if response_id and response_id in self._omni_cancelled_response_ids:
            return True
        return bool(response_id and self._omni_response_id and response_id != self._omni_response_id)

    def append_omni_transcript_delta(self, delta: str, response_id: str = "") -> None:
        if not delta:
            return
        with self._omni_lock:
            if self._is_omni_response_stale_locked(response_id):
                self.logger.emit(
                    "omni_stale_transcript_delta_dropped",
                    callId=self.call_id,
                    responseId=response_id,
                    currentResponseId=self._omni_response_id,
                )
                return
            self._omni_reply_parts.append(delta)

    def finish_omni_transcript(self, transcript: str, response_id: str = "") -> None:
        with self._omni_lock:
            if self._is_omni_response_stale_locked(response_id):
                self.logger.emit(
                    "omni_stale_transcript_done_dropped",
                    callId=self.call_id,
                    responseId=response_id,
                    currentResponseId=self._omni_response_id,
                )
                return
            reply = transcript.strip() or "".join(self._omni_reply_parts).strip()
            pending_text = self._omni_pending_customer_text
            pending_signal = self._omni_pending_signal
        if reply:
            if pending_text and pending_signal != "call_screening":
                self._append_conversation_turn(pending_text, reply)
            self._sales_fsm.record_assistant_reply(reply)
            history_turns = len(self._conversation_history)
            with self._omni_lock:
                self._last_omni_reply = reply
                if self._omni_pending_customer_text == pending_text:
                    self._omni_pending_customer_text = ""
                    self._omni_pending_signal = ""
            self.logger.emit(
                "llm_reply",
                callId=self.call_id,
                reply=reply,
                strategy="qwen_omni_realtime",
                latencyMs=0,
                fallbackUsed=False,
                historyTurns=history_turns,
                error=None,
            )

    def play_omni_audio_delta(self, delta: str, response_id: str = "") -> None:
        # 【审计A1】本方法运行在 dashscope websocket 回调线程：只做解码+切帧+入有界队列，
        # 严禁持锁按节拍 sleep 播放，播放节拍由 _omni_playback_worker 专职线程负责。
        if not delta:
            return
        try:
            audio = base64.b64decode(delta)
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("omni_audio_decode_error", callId=self.call_id, error=str(exc))
            return
        frames: list[bytes] = []
        first_audio_fields: dict[str, Any] | None = None
        with self._omni_lock:
            if self._omni_barge_collecting or self._is_omni_response_stale_locked(response_id):
                self._omni_drop_log_count += 1
                if self._omni_drop_log_count <= 3:
                    self.logger.emit(
                        "omni_audio_delta_dropped",
                        callId=self.call_id,
                        responseId=response_id,
                        currentResponseId=self._omni_response_id,
                        bytes=len(audio),
                        collecting=self._omni_barge_collecting,
                        detail="打断恢复期间或旧 response 的音频已丢弃，避免串音。",
                    )
                return
            # 【审计A5】response_id 为空的音频 delta 按当前 response 严格校验：
            # 没有活跃 response 时一律视为陈旧音频丢弃，避免旧回复的残帧复活。
            if not response_id and not self._omni_response_active:
                self._omni_drop_log_count += 1
                if self._omni_drop_log_count <= 3:
                    self.logger.emit(
                        "omni_audio_delta_dropped",
                        callId=self.call_id,
                        responseId="",
                        currentResponseId=self._omni_response_id,
                        bytes=len(audio),
                        collecting=False,
                        detail="response_id 为空且当前没有活跃 response，按陈旧音频丢弃。",
                    )
                return
            generation = self._omni_generation
            self._omni_audio_total += len(audio)
            pcm_8k = _downsample_pcm_24k_to_8k(audio, self._omni_downsample_state)
            if not pcm_8k or self._speech_is_obsolete(generation):
                return
            if not self._omni_tts_started:
                self._omni_first_audio_ms = int((time.perf_counter() - self._omni_response_started_at) * 1000)
                self._omni_tts_started = True
                if self._omni_barge_forced_response_until > time.monotonic():
                    self._omni_barge_forced_audio_started = True
                first_audio_fields = {
                    "firstAudioMs": self._omni_first_audio_ms,
                    "bytes": len(pcm_8k),
                    "generation": generation,
                }
            self._omni_pending_audio += pcm_8k
            while len(self._omni_pending_audio) >= PCM_FRAME_BYTES:
                frames.append(self._omni_pending_audio[:PCM_FRAME_BYTES])
                self._omni_pending_audio = self._omni_pending_audio[PCM_FRAME_BYTES:]
            effective_response_id = response_id or self._omni_response_id
        if first_audio_fields is not None:
            self.logger.emit(
                "tts_start",
                callId=self.call_id,
                reason="omni_response",
                text="",
                bytes=first_audio_fields["bytes"],
                synthMs=first_audio_fields["firstAudioMs"],
                firstAudioMs=first_audio_fields["firstAudioMs"],
                voice=self.config.omni_voice,
                voiceType="omni",
                model=self.config.omni_model,
                streaming=True,
                generation=first_audio_fields["generation"],
            )
            self._flight_event(
                "tts_start",
                reason="omni_response",
                firstAudioMs=first_audio_fields["firstAudioMs"],
                voiceType="omni",
                model=self.config.omni_model,
                generation=first_audio_fields["generation"],
            )
        for frame in frames:
            self._enqueue_omni_playback("frame", generation, effective_response_id, frame)

    def _enqueue_omni_playback(self, kind: str, generation: int, response_id: str, payload: Any = b"") -> None:
        # 【审计A1】有界队列入队：队列满时绝不阻塞 websocket 回调线程。
        item = (kind, generation, response_id, payload)
        try:
            self._omni_play_queue.put_nowait(item)
            return
        except queue.Full:
            pass
        if kind == "done":
            # done 收尾信号必须送达（否则 speaking 状态卡死），丢最旧音频帧腾出位置。
            while not self.stop_event.is_set():
                try:
                    self._omni_play_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._omni_play_queue.put_nowait(item)
                    return
                except queue.Full:
                    continue
            return
        self._omni_dropped_frames += 1
        if self._omni_dropped_frames in {1, 50, 250}:
            self.logger.emit(
                "omni_play_queue_overflow",
                callId=self.call_id,
                droppedFrames=self._omni_dropped_frames,
                detail="播放队列已满（约10秒积压），丢弃最新音频帧以保护回调线程不被阻塞。",
            )

    def _clear_omni_play_queue(self, source: str) -> None:
        # 【审计A1】打断/断开时清空播放队列，丢弃旧 generation/response 的剩余帧。
        cleared = 0
        while True:
            try:
                self._omni_play_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        if cleared:
            self.logger.emit("omni_play_queue_cleared", callId=self.call_id, frames=cleared, source=source)

    def _omni_playback_worker(self) -> None:
        # 【审计A1】专职播放线程：按 20ms 节拍从有界队列取帧写 AudioSocket，
        # 打断/换代后的旧帧在此按 generation + response_id 丢弃。
        next_frame_at: float | None = None
        lag_events = 0
        while not self.stop_event.is_set():
            try:
                kind, generation, response_id, payload = self._omni_play_queue.get(timeout=0.2)
            except queue.Empty:
                next_frame_at = None
                continue
            if kind == "done":
                stats = payload if isinstance(payload, dict) else {}
                try:
                    self._finalize_omni_response_playback(generation, response_id, stats)
                except Exception as exc:  # noqa: BLE001
                    self.logger.emit("omni_playback_finalize_error", callId=self.call_id, error=str(exc))
                next_frame_at = None
                lag_events = 0
                continue
            if self.stop_event.is_set() or self._speech_is_obsolete(generation):
                next_frame_at = None
                continue
            with self._omni_lock:
                stale = self._omni_barge_collecting or (
                    bool(response_id) and response_id in self._omni_cancelled_response_ids
                )
            if stale:
                next_frame_at = None
                continue
            try:
                with self.playback_lock:
                    next_frame_at, lag_events = self._send_audio_frame_at_cadence(
                        payload,
                        next_frame_at,
                        lag_events,
                        "omni_response",
                        generation,
                    )
            except Exception:  # noqa: BLE001
                # _send_audio_frame_at_cadence 内部已触发 socket 断开收尾。
                next_frame_at = None
                continue
            with self._omni_lock:
                self._omni_audio_sent += len(payload)

    def finish_omni_response(self, response_id: str = "") -> None:
        with self._omni_lock:
            current_response_id = self._omni_response_id
            # 评审修复2：改用 _is_omni_response_stale_locked（含已取消 response 集合判断），
            # 防止被 cancel 的 response 迟到的 done 穿透，错扣新 response 的 speech job。
            stale = self._is_omni_response_stale_locked(response_id)
        if stale:
            self.logger.emit(
                "omni_stale_response_done",
                callId=self.call_id,
                responseId=response_id,
                currentResponseId=current_response_id,
            )
            return
        # 【审计A1】回调线程只把剩余尾帧和 done 收尾信号入队，
        # 由播放线程按节拍播完队列音频后再执行收尾（_finalize_omni_response_playback）。
        with self._omni_lock:
            generation = self._omni_generation
            pending = self._omni_pending_audio
            self._omni_pending_audio = b""
            # 【审计A5】response 已完成，此后 response_id 为空的音频 delta 一律丢弃。
            self._omni_response_active = False
            effective_response_id = response_id or current_response_id
            stats = {
                "audioSent": self._omni_audio_sent,
                "audioTotal": self._omni_audio_total,
                "firstAudioMs": self._omni_first_audio_ms,
                "reply": "".join(self._omni_reply_parts).strip(),
            }
        if pending and not self.stop_event.is_set() and not self._speech_is_obsolete(generation):
            self._enqueue_omni_playback(
                "frame",
                generation,
                effective_response_id,
                pending.ljust(PCM_FRAME_BYTES, b"\x00"),
            )
        self._enqueue_omni_playback("done", generation, effective_response_id, stats)

    def _finalize_omni_response_playback(self, generation: int, response_id: str, stats: dict[str, Any]) -> None:
        # 【审计A1】原 finish_omni_response 的收尾逻辑：在播放线程里等队列音频播完后执行，
        # 保证 speaking 状态与真实播放对齐。若此时已开始新 response，则用 done 时刻的快照统计。
        with self._omni_lock:
            if self._omni_generation == generation:
                audio_sent = self._omni_audio_sent
                audio_total = self._omni_audio_total
                first_audio_ms = self._omni_first_audio_ms
                reply = "".join(self._omni_reply_parts).strip()
            else:
                audio_sent = int(stats.get("audioSent") or 0)
                audio_total = int(stats.get("audioTotal") or 0)
                first_audio_ms = int(stats.get("firstAudioMs") or 0)
                reply = str(stats.get("reply") or "")
        interrupted = self._speech_is_obsolete(generation)
        self._mark_speech_job_finished()
        if not interrupted and audio_sent == 0 and audio_total == 0:
            fallback_text = reply or OMNI_NO_AUDIO_FALLBACK_TEXT
            with self._omni_lock:
                self._omni_barge_forced_response_until = 0.0
                self._omni_barge_forced_audio_started = False
            self.logger.emit(
                "omni_no_audio_response",
                callId=self.call_id,
                responseId=response_id,
                fallbackText=fallback_text,
                generation=generation,
                detail="Omni 完成了回复但没有返回可播放音频，改用本地实时 TTS 播放兜底句。",
            )
            threading.Thread(
                target=self._speak,
                args=(fallback_text, "omni_no_audio_fallback", generation),
                daemon=True,
            ).start()
            return
        if not interrupted:
            with self._omni_lock:
                self._omni_barge_forced_response_until = 0.0
                self._omni_barge_forced_audio_started = False
        self.logger.emit(
            "tts_interrupted" if interrupted else "tts_done",
            callId=self.call_id,
            reason="omni_response",
            phase="playback",
            sentBytes=audio_sent,
            totalBytes=audio_total,
            firstAudioMs=first_audio_ms,
            generation=generation,
        )
        self._flight_event(
            "tts_interrupted" if interrupted else "tts_done",
            reason="omni_response",
            sentBytes=audio_sent,
            totalBytes=audio_total,
            firstAudioMs=first_audio_ms,
            generation=generation,
        )
        if not interrupted:
            self._schedule_no_response_hangup("omni_response")


def synthesize_tts_pcm(text: str, config: BridgeConfig) -> bytes:
    runtime_config = get_runtime_ai_config()
    dashscope.api_key = runtime_config.dashscope_api_key
    synthesizer = SpeechSynthesizer(
        model=config.tts_model,
        voice=config.tts_voice_id,
        format=CosyAudioFormat.PCM_8000HZ_MONO_16BIT,
        workspace=config.workspace,
    )
    audio = synthesizer.call(text, timeout_millis=20000)
    if not audio:
        raise RuntimeError("DashScope TTS 未返回音频。")
    return bytes(audio)


def iter_tts_pcm_chunks(text: str, config: BridgeConfig):
    if _is_qwen_realtime_model(config.tts_model):
        yield from stream_qwen_realtime_tts_pcm(text, config)
        return
    yield synthesize_tts_pcm(text, config)


@dataclass
class _PcmDownsampleState:
    leftover: bytes = b""
    history: list[int] = field(default_factory=list)
    phase: int = 0


def stream_qwen_realtime_tts_pcm(text: str, config: BridgeConfig):
    runtime_config = get_runtime_ai_config()
    if not runtime_config.dashscope_api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，不能启动 Qwen 实时 TTS。")

    from dashscope.audio.qwen_tts_realtime import AudioFormat as QwenAudioFormat
    from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback

    class Callback(QwenTtsRealtimeCallback):
        def __init__(self) -> None:
            self.items: queue.Queue[tuple[str, bytes | str | None]] = queue.Queue()
            self.closed = False
            self.received_audio = False

        def on_event(self, response: object) -> None:
            payload = _qwen_event_payload(response)
            event_type = str(payload.get("type") or "")
            if event_type == "response.audio.delta":
                delta = str(payload.get("delta") or "")
                if delta:
                    try:
                        audio = base64.b64decode(delta)
                    except Exception as exc:  # noqa: BLE001
                        self.items.put(("error", f"Qwen 实时 TTS 音频解码失败：{exc}"))
                        return
                    self.received_audio = True
                    self.items.put(("audio", audio))
                return
            if event_type in {"response.done", "session.finished"}:
                self.closed = True
                self.items.put(("done", None))
                return
            if event_type == "error" or payload.get("error"):
                self.items.put(("error", json.dumps(payload, ensure_ascii=False)[:400]))

        def on_close(self, close_status_code: object, close_msg: object) -> None:
            self.closed = True
            self.items.put(("done", None))

    dashscope.api_key = runtime_config.dashscope_api_key
    callback = Callback()
    tts = QwenTtsRealtime(model=config.tts_model, callback=callback, workspace=config.workspace)
    downsample_state = _PcmDownsampleState()
    try:
        tts.connect()
        tts.update_session(
            voice=config.tts_voice_id,
            response_format=QwenAudioFormat.PCM_24000HZ_MONO_16BIT,
            mode="commit",
            language_type=runtime_config.dashscope_system_tts_language_type,
        )
        tts.append_text(text)
        tts.commit()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                item_type, item = callback.items.get(timeout=0.2)
            except queue.Empty:
                if callback.closed:
                    break
                continue
            if item_type == "done":
                break
            if item_type == "error":
                raise RuntimeError(str(item))
            if item_type == "audio" and isinstance(item, bytes):
                pcm_8k = _downsample_pcm_24k_to_8k(item, downsample_state)
                if pcm_8k:
                    yield pcm_8k
        if not callback.received_audio:
            raise RuntimeError("Qwen 实时 TTS 未返回音频。")
    finally:
        try:
            tts.close()
        except Exception:
            pass


def _qwen_event_payload(response: object) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if isinstance(response, str):
        try:
            payload = json.loads(response)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _downsample_pcm_24k_to_8k(chunk: bytes, state: _PcmDownsampleState) -> bytes:
    data = state.leftover + chunk
    usable = (len(data) // 2) * 2
    state.leftover = data[usable:]
    if usable <= 0:
        return b""
    output = bytearray()
    # Qwen realtime emits 24 kHz PCM, while Asterisk AudioSocket expects 8 kHz.
    # A small FIR low-pass before decimation avoids trembly/metallic artifacts
    # caused by dropping or averaging isolated 3-sample groups.
    taps_len = len(_DOWNSAMPLE_TAPS)
    for offset in range(0, usable, 2):
        sample = int.from_bytes(data[offset : offset + 2], "little", signed=True)
        state.history.append(sample)
        if len(state.history) > taps_len:
            del state.history[: len(state.history) - taps_len]
        if state.phase == 0:
            if len(state.history) < taps_len:
                padded_history = [0] * (taps_len - len(state.history)) + state.history
            else:
                padded_history = state.history
            filtered = sum(sample_value * tap for sample_value, tap in zip(reversed(padded_history), _DOWNSAMPLE_TAPS))
            output.extend(max(-32768, min(32767, int(round(filtered)))).to_bytes(2, "little", signed=True))
        state.phase = (state.phase + 1) % _DOWNSAMPLE_FACTOR
    return bytes(output)


def _upsample_pcm_8k_to_16k(chunk: bytes) -> bytes:
    usable = (len(chunk) // 2) * 2
    if usable <= 0:
        return b""
    output = bytearray(usable * 2)
    output.clear()
    for (sample,) in struct.iter_unpack("<h", chunk[:usable]):
        encoded = sample.to_bytes(2, "little", signed=True)
        output.extend(encoded)
        output.extend(encoded)
    return bytes(output)


def build_config(args: argparse.Namespace) -> BridgeConfig:
    runtime_config = get_runtime_ai_config()
    voice = resolve_tts_voice(args.voice_id, args.voice_name)
    workspace = runtime_config.dashscope_workspace.strip() or None
    return BridgeConfig(
        bind_host=args.host or settings.asterisk_audio_socket_bind_host,
        port=int(args.port or settings.asterisk_audio_socket_port),
        asr_model=args.asr_model or runtime_config.realtime_asr_model,
        tts_model=args.tts_model or voice.tts_model,
        tts_voice_id=voice.voice_id,
        tts_voice_name=voice.voice_name,
        tts_voice_type=voice.voice_type,
        conversation_mode=(args.conversation_mode or runtime_config.realtime_conversation_mode or "omni").strip().lower(),
        omni_model=(args.omni_model or runtime_config.dashscope_omni_realtime_model).strip(),
        omni_url=(args.omni_url or runtime_config.dashscope_omni_realtime_url).strip(),
        omni_voice=(args.omni_voice or runtime_config.dashscope_omni_realtime_voice or voice.voice_id or "Serena").strip(),
        omni_input_transcription_model=(
            args.omni_input_transcription_model or runtime_config.dashscope_omni_input_transcription_model
        ).strip(),
        opening_text=args.opening_text or settings.realtime_call_opening_text,
        log_path=Path(args.log_path or settings.realtime_call_event_log_path).expanduser(),
        workspace=workspace,
        barge_rms_threshold=max(1, settings.realtime_barge_rms_threshold),
        barge_frames=max(1, settings.realtime_barge_frames),
        tts_gain=max(0.1, min(3.0, settings.realtime_tts_gain)),
        opening_grace_seconds=max(0.0, min(5.0, settings.realtime_opening_grace_seconds)),
        debug_audio_capture_enabled=settings.realtime_debug_audio_capture_enabled,
        debug_audio_capture_dir=Path(settings.realtime_debug_audio_capture_dir).expanduser(),
        flight_recorder_enabled=settings.realtime_flight_recorder_enabled,
        flight_recorder_dir=Path(settings.realtime_flight_recorder_dir).expanduser(),
        flight_audio_capture_enabled=settings.realtime_flight_audio_capture_enabled,
        turn_manager_enabled=settings.realtime_turn_manager_enabled,
        audio_quality_enabled=settings.realtime_audio_quality_enabled,
        # 【审计A6】接听分类等待硬上限压到 2.5 秒，环境配置更大也不生效。
        answer_classification_seconds=max(0.5, min(2.5, settings.realtime_answer_classification_seconds)),
        call_screening_hangup_seconds=max(0.0, min(45.0, settings.realtime_call_screening_hangup_seconds)),
        no_response_hangup_seconds=max(0.0, min(90.0, settings.realtime_no_response_hangup_seconds)),
    )


@dataclass(frozen=True)
class ResolvedTtsVoice:
    voice_id: str
    voice_name: str
    voice_type: str
    tts_model: str


def resolve_tts_voice(explicit_voice_id: str | None = None, explicit_voice_name: str | None = None) -> ResolvedTtsVoice:
    runtime_config = get_runtime_ai_config()
    voice_id = (
        explicit_voice_id
        or os.environ.get("AI_ACQ_REALTIME_TTS_VOICE_ID")
        or os.environ.get("REALTIME_TTS_VOICE_ID")
        or settings.realtime_tts_voice_id
    ).strip()
    voice_type = (
        os.environ.get("AI_ACQ_REALTIME_TTS_VOICE_TYPE")
        or os.environ.get("REALTIME_TTS_VOICE_TYPE")
        or settings.realtime_tts_voice_type
        or "system"
    ).strip().lower()
    voice_name = (explicit_voice_name or settings.realtime_tts_voice_name or "").strip()
    if voice_id:
        if voice_type in {"clone", "cloned", "voice_clone"} or voice_id.lower().startswith("cosyvoice"):
            return ResolvedTtsVoice(
                voice_id=voice_id,
                voice_name=voice_name or voice_id,
                voice_type="clone",
                tts_model=runtime_config.dashscope_tts_model,
            )
        voice_param = _qwen_voice_param(voice_id)
        return ResolvedTtsVoice(
            voice_id=voice_param,
            voice_name=voice_name or _qwen_voice_display_name(voice_param),
            voice_type="system",
            tts_model=runtime_config.dashscope_realtime_tts_model,
        )

    if voice_type in {"clone", "cloned", "voice_clone"}:
        with SessionLocal() as db:
            record = db.scalar(
                select(VoiceCloneRecord)
                .where(VoiceCloneRecord.status == "可用", VoiceCloneRecord.external_voice_id != "")
                .order_by(VoiceCloneRecord.completed_at.desc(), VoiceCloneRecord.created_at.desc())
            )
            if record and record.external_voice_id:
                return ResolvedTtsVoice(
                    voice_id=record.external_voice_id,
                    voice_name=record.cloned_voice_name or record.external_voice_id,
                    voice_type="clone",
                    tts_model=runtime_config.dashscope_tts_model,
                )
        raise RuntimeError("没有可用于实时电话 TTS 的复刻 voice_id，请先在声音档案训练可用音色或设置 REALTIME_TTS_VOICE_ID。")

    default_voice = _qwen_voice_param(runtime_config.dashscope_realtime_tts_voice or "Ethan")
    return ResolvedTtsVoice(
        voice_id=default_voice,
        voice_name=voice_name or _qwen_voice_display_name(default_voice),
        voice_type="system",
        tts_model=runtime_config.dashscope_realtime_tts_model,
    )


def _is_qwen_realtime_model(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith("qwen") and "realtime" in normalized


def _qwen_voice_param(voice_id: str) -> str:
    value = voice_id.strip()
    lower = value.lower()
    if lower.startswith("qwen_tts_"):
        value = value[len("qwen_tts_") :]
        return " ".join(part.capitalize() for part in value.replace("-", "_").split("_") if part)
    return value or "Ethan"


def _qwen_voice_display_name(voice_param: str) -> str:
    names = {
        "Cherry": "芊悦（Cherry）",
        "Serena": "苏瑶（Serena）",
        "Ethan": "晨煦（Ethan）",
        "Chelsie": "千雪（Chelsie）",
        "Moon": "月白（Moon）",
        "Maia": "四月（Maia）",
        "Kai": "凯（Kai）",
        "Sunny": "四川-晴儿（Sunny）",
        "Rocky": "粤语-阿强（Rocky）",
        "Kiki": "粤语-阿清（Kiki）",
    }
    return names.get(voice_param, f"系统音色（{voice_param}）")


def serve(config: BridgeConfig, stop_event: threading.Event) -> None:
    logger = JsonlEventLogger(config.log_path)
    logger.emit(
        "bridge_start",
        bind=f"{config.bind_host}:{config.port}",
        conversationMode=config.conversation_mode,
        asrModel=config.asr_model,
        ttsModel=config.tts_model,
        omniModel=config.omni_model,
        voice=config.tts_voice_name,
        omniVoice=config.omni_voice,
        voiceType=config.tts_voice_type,
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((config.bind_host, config.port))
        server.listen(8)
        server.settimeout(0.8)
        while not stop_event.is_set():
            try:
                conn, peer = server.accept()
            except TimeoutError:
                continue
            session_cls = OmniAudioSocketCallSession if config.conversation_mode == "omni" else AudioSocketCallSession
            threading.Thread(
                target=session_cls(conn, peer, config, logger).run,
                name=f"ai-acq-audiosocket-{peer[0]}:{peer[1]}",
                daemon=True,
            ).start()
    logger.emit("bridge_stop")


def config_summary(config: BridgeConfig) -> dict[str, object]:
    return {
        "bind": f"{config.bind_host}:{config.port}",
        "conversationMode": config.conversation_mode,
        "asrModel": config.asr_model,
        "ttsModel": config.tts_model,
        "omniModel": config.omni_model,
        "omniUrl": config.omni_url,
        "omniVoice": config.omni_voice,
        "omniInputTranscriptionModel": config.omni_input_transcription_model,
        "voice": config.tts_voice_name,
        "voiceType": config.tts_voice_type,
        "voiceConfigured": bool(config.tts_voice_id),
        "dashscopeKeyConfigured": bool(get_runtime_ai_config().dashscope_api_key.strip()),
        "workspaceConfigured": bool(config.workspace),
        "logPath": str(config.log_path),
        "bargeRmsThreshold": config.barge_rms_threshold,
        "bargeFrames": config.barge_frames,
        "ttsGain": config.tts_gain,
        "openingGraceSeconds": config.opening_grace_seconds,
        "debugAudioCaptureEnabled": config.debug_audio_capture_enabled,
        "debugAudioCaptureDir": str(config.debug_audio_capture_dir),
        "audioQualityEnabled": config.audio_quality_enabled,
        "answerClassificationSeconds": config.answer_classification_seconds,
        "callScreeningHangupSeconds": config.call_screening_hangup_seconds,
        "noResponseHangupSeconds": config.no_response_hangup_seconds,
    }


def _read_exact(conn: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        try:
            chunk = conn.recv(size - len(chunks))
        except socket.timeout as exc:
            raise TimeoutError from exc
        if not chunk:
            raise AudioSocketProtocolError("AudioSocket connection closed.")
        chunks.extend(chunk)
    return bytes(chunks)


def _decode_call_id(payload: bytes) -> str:
    if len(payload) == 16:
        return str(uuid.UUID(bytes=payload))
    return payload.decode("utf-8", errors="replace")


def _pcm_rms(payload: bytes) -> int:
    sample_count = len(payload) // 2
    if sample_count <= 0:
        return 0
    total = 0
    for (sample,) in struct.iter_unpack("<h", payload[: sample_count * 2]):
        total += sample * sample
    return int((total / sample_count) ** 0.5)


def _scale_pcm16(payload: bytes, gain: float) -> bytes:
    if not payload or abs(gain - 1.0) < 0.01:
        return payload
    usable = (len(payload) // 2) * 2
    output = bytearray(usable + (len(payload) - usable))
    output.clear()
    for (sample,) in struct.iter_unpack("<h", payload[:usable]):
        scaled = int(sample * gain)
        output.extend(max(-32768, min(32767, scaled)).to_bytes(2, "little", signed=True))
    if usable < len(payload):
        output.extend(payload[usable:])
    return bytes(output)


def _safe_error_text(message: object) -> str:
    try:
        return str(message)
    except Exception as exc:  # noqa: BLE001
        return f"{type(message).__name__}: <unprintable error: {exc}>"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AI ACQ Asterisk AudioSocket realtime bridge.")
    parser.add_argument("--host", help="TCP bind host for Asterisk AudioSocket.")
    parser.add_argument("--port", type=int, help="TCP port for Asterisk AudioSocket.")
    parser.add_argument("--voice-id", help="DashScope CosyVoice voice_id for realtime TTS.")
    parser.add_argument("--voice-name", help="Human label for the realtime TTS voice.")
    parser.add_argument("--asr-model", help="DashScope realtime ASR model.")
    parser.add_argument("--tts-model", help="DashScope realtime TTS model.")
    parser.add_argument("--conversation-mode", choices=["pipeline", "omni"], help="Realtime engine: pipeline or omni.")
    parser.add_argument("--omni-model", help="DashScope Qwen Omni realtime model.")
    parser.add_argument("--omni-url", help="DashScope Qwen Omni realtime WebSocket base URL.")
    parser.add_argument("--omni-voice", help="Qwen Omni realtime voice.")
    parser.add_argument("--omni-input-transcription-model", help="Qwen Omni realtime input transcription model.")
    parser.add_argument("--opening-text", help="Opening sentence spoken after the call is answered.")
    parser.add_argument("--log-path", help="JSONL event log path.")
    parser.add_argument("--check", action="store_true", help="Print non-secret bridge configuration and exit.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stop_event = threading.Event()

    def _stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    config = build_config(args)
    if args.check:
        print(json.dumps(config_summary(config), ensure_ascii=False, indent=2))
        return
    serve(config, stop_event)


if __name__ == "__main__":
    main()
