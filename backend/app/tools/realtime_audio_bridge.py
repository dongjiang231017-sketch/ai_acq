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
from pathlib import Path
from typing import Any

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from dashscope.audio.tts_v2 import SpeechSynthesizer
from dashscope.audio.tts_v2.speech_synthesizer import AudioFormat as CosyAudioFormat
from dashscope.audio.qwen_omni import MultiModality, OmniRealtimeCallback, OmniRealtimeConversation
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.growth import VoiceCloneRecord
from app.services.realtime_llm import generate_realtime_reply
from app.services.realtime_outbound import _build_reply, _classify_intent
from app.services.realtime_sales_playbook import (
    build_omni_turn_instruction,
    build_video_group_buying_sales_instructions,
    classify_realtime_call_input,
)


AUDIO_SOCKET_KIND_HANGUP = 0x00
AUDIO_SOCKET_KIND_UUID = 0x01
AUDIO_SOCKET_KIND_DTMF = 0x03
AUDIO_SOCKET_KIND_AUDIO = 0x10
AUDIO_SOCKET_KIND_ERROR = 0xFF
PCM_FRAME_BYTES = 320
PCM_FRAME_SECONDS = 0.02
OMNI_LOCAL_BARGE_MIN_SENT_BYTES = PCM_FRAME_BYTES * 12
OMNI_BARGE_RECOVERY_MIN_SECONDS = 0.35
OMNI_BARGE_RECOVERY_SILENCE_SECONDS = 0.35
OMNI_BARGE_RECOVERY_MAX_SECONDS = 1.0
OMNI_BARGE_FORCED_RESPONSE_SKIP_SECONDS = 4.0
OMNI_FIRST_AUDIO_DEADLINE_SECONDS = 1.15
OMNI_NO_AUDIO_FALLBACK_TEXT = "我短说：我是做视频号团购到店获客的，帮门店做套餐和微信同城曝光。"
REMOTE_AUDIO_CLASSIFY_WAIT_SECONDS = 7.0
REMOTE_AUDIO_SILENCE_SECONDS = 1.3
BARGE_AUDIO_FORWARD_SECONDS = 2.8
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
        self.outbound_path = self.directory / f"{safe_call_id}.outbound.wav"
        self._lock = threading.Lock()
        self._inbound = self._open_wave(self.inbound_path)
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
                self._outbound.close()
                self.closed = True
        return {
            "inboundPath": str(self.inbound_path),
            "outboundPath": str(self.outbound_path),
        }


class AudioSocketProtocolError(RuntimeError):
    pass


class CallRecognitionCallback(RecognitionCallback):
    def __init__(self, call: "AudioSocketCallSession") -> None:
        self.call = call
        self.last_text = ""

    def on_open(self) -> None:
        self.call.logger.emit("asr_open", callId=self.call.call_id, model=self.call.config.asr_model)

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if not isinstance(sentence, dict):
            return
        text = str(sentence.get("text") or "").strip()
        is_final = RecognitionResult.is_sentence_end(sentence)
        if text and text != self.last_text:
            self.call.customer_activity_event.set()
            self.call.logger.emit(
                "asr_final" if is_final else "asr_partial",
                callId=self.call.call_id,
                text=text,
                beginMs=sentence.get("begin_time"),
                endMs=sentence.get("end_time"),
            )
            self.last_text = text
        if is_final and text:
            generation = self.call.cancel_pending_speech("客户说话完成，取消旧 TTS 队列。", source="asr_final")
            self.call.customer_texts.put((generation, text))

    def on_error(self, message: object) -> None:
        self.call.logger.emit("asr_error", callId=self.call.call_id, error=_safe_error_text(message))

    def on_complete(self) -> None:
        self.call.logger.emit("asr_complete", callId=self.call.call_id)

    def on_close(self) -> None:
        self.call.logger.emit("asr_close", callId=self.call.call_id)


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
            response_id = ""
            if isinstance(response.get("response"), dict):
                response_id = str(response["response"].get("id") or "")
            self.call.start_omni_response(response_id)
            return
        if event_type == "response.audio_transcript.delta":
            self.call.append_omni_transcript_delta(str(response.get("delta") or ""))
            return
        if event_type == "response.audio_transcript.done":
            self.call.finish_omni_transcript(str(response.get("transcript") or ""))
            return
        if event_type == "response.audio.delta":
            self.call.play_omni_audio_delta(str(response.get("delta") or ""))
            return
        if event_type == "response.done":
            response_id = ""
            if isinstance(response.get("response"), dict):
                response_id = str(response["response"].get("id") or "")
            self.call.finish_omni_response(response_id)
            return
        if event_type == "error" or response.get("error"):
            self.call.logger.emit("omni_error", callId=self.call.call_id, error=json.dumps(response, ensure_ascii=False)[:600])


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
        self.speech_state_lock = threading.Lock()
        self.speech_generation = 0
        self.speech_jobs = 0
        self._loud_frames = 0
        self._last_barge_at = 0.0
        self._barge_forward_until = 0.0
        self._recognition: Recognition | None = None
        self._audio_capture: CallAudioCapture | None = None
        self._intent_counts: dict[str, int] = {}
        self._conversation_history: list[dict[str, str]] = []
        self._human_speech_confirmed = False
        self._call_screening_seen = False
        self._call_screening_answered = False
        self._system_prompt_seen = False
        self._opening_started = False
        self._last_remote_audio_at = 0.0
        self._turn_thread = threading.Thread(target=self._turn_worker, name="ai-acq-audiosocket-turn", daemon=True)

    def run(self) -> None:
        self.conn.settimeout(1.0)
        self.logger.emit("socket_connected", peer=f"{self.peer[0]}:{self.peer[1]}", voice=self.config.tts_voice_name)
        try:
            if not self._await_call_uuid():
                return
            self.logger.emit("call_connected", callId=self.call_id, peer=f"{self.peer[0]}:{self.peer[1]}", voice=self.config.tts_voice_name)
            self._start_asr()
            self._turn_thread.start()
            threading.Thread(target=self._speak_opening_after_grace, daemon=True).start()
            self._read_loop()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("call_error", callId=self.call_id, error=str(exc))
        finally:
            self.stop_event.set()
            self.interrupt_event.set()
            self._stop_asr()
            self._stop_audio_capture()
            try:
                self.conn.close()
            except OSError:
                pass
            self.logger.emit("call_disconnected", callId=self.call_id)

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
                self._start_audio_capture()
                return True
            if frame_type == AUDIO_SOCKET_KIND_HANGUP:
                self.logger.emit("hangup_before_uuid")
                return False
            self.logger.emit("frame_before_uuid", frameType=frame_type, bytes=len(payload))
        self.logger.emit("uuid_timeout", peer=f"{self.peer[0]}:{self.peer[1]}")
        return False

    def _start_asr(self) -> None:
        if not settings.dashscope_api_key:
            raise AudioSocketProtocolError("缺少 DASHSCOPE_API_KEY，不能启动实时 ASR。")
        dashscope.api_key = settings.dashscope_api_key
        callback = CallRecognitionCallback(self)
        self._recognition = Recognition(
            model=self.config.asr_model,
            callback=callback,
            format="pcm",
            sample_rate=8000,
            workspace=self.config.workspace,
            disfluency_removal_enabled=True,
        )
        self._recognition.start()

    def _stop_asr(self) -> None:
        if not self._recognition:
            return
        try:
            self._recognition.stop()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("asr_stop_error", callId=self.call_id, error=str(exc))
        self._recognition = None

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
        if rms >= self.config.barge_rms_threshold:
            self.customer_activity_event.set()
            self._last_remote_audio_at = now
        if self.speaking_event.is_set():
            if now < self._barge_forward_until:
                if self._recognition:
                    self._recognition.send_audio_frame(payload)
                return
            if rms >= self.config.barge_rms_threshold:
                self._loud_frames += 1
            else:
                self._loud_frames = 0
            if self._loud_frames >= self.config.barge_frames and now - self._last_barge_at > 0.8:
                self._barge_forward_until = now + BARGE_AUDIO_FORWARD_SECONDS
                self.cancel_pending_speech("客户插话，停止后续 TTS 音频帧并继续听客户说话。", source="rms", rms=rms)
                if self._recognition:
                    self._recognition.send_audio_frame(payload)
            return
        self._loud_frames = 0
        if self._recognition:
            self._recognition.send_audio_frame(payload)

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
        deadline = time.monotonic() + REMOTE_AUDIO_CLASSIFY_WAIT_SECONDS
        saw_remote_audio = bool(self._last_remote_audio_at)
        while time.monotonic() < deadline and not self.stop_event.is_set():
            if self._opening_blocked():
                return False
            if self._last_remote_audio_at:
                saw_remote_audio = True
            if self._last_remote_audio_at and time.monotonic() - self._last_remote_audio_at < REMOTE_AUDIO_SILENCE_SECONDS:
                time.sleep(0.08)
                continue
            time.sleep(0.08)
        if self._opening_blocked():
            return False
        if saw_remote_audio:
            self.logger.emit(
                "human_confirmation_pending",
                callId=self.call_id,
                mode=mode,
                waitMs=int(REMOTE_AUDIO_CLASSIFY_WAIT_SECONDS * 1000),
                detail="对端已有声音但还没有分清真人/电话助理，暂不主动开销售话术。",
            )
            return False
        self.logger.emit(
            "opening_after_remote_silence",
            callId=self.call_id,
            mode=mode,
            waitMs=int(REMOTE_AUDIO_CLASSIFY_WAIT_SECONDS * 1000),
        )
        return True

    def _opening_blocked(self) -> bool:
        return (
            self.stop_event.is_set()
            or self.speaking_event.is_set()
            or self._opening_started
            or self._human_speech_confirmed
            or self._call_screening_seen
            or self._system_prompt_seen
        )

    def _mark_opening_started(self) -> bool:
        if self._opening_blocked():
            return False
        self._opening_started = True
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
                self._system_prompt_seen = True
                self.logger.emit(
                    "system_prompt_ignored",
                    callId=self.call_id,
                    text=text,
                    detail="识别到运营商、手机系统或语音留言提示，已忽略，不触发销售回复。",
                )
                continue
            if signal == "call_screening":
                self._call_screening_seen = True
                if self._call_screening_answered:
                    self.logger.emit(
                        "call_screening_followup_ignored",
                        callId=self.call_id,
                        text=text,
                        detail="电话助理后续等待提示已忽略，避免重复说明身份和来电原因。",
                    )
                    continue
                self._call_screening_answered = True
                reply = "您好，我这边做视频号团购到店获客，来电想确认门店微信同城曝光合作，麻烦转接负责人，谢谢。"
                self.logger.emit(
                    "call_screening_detected",
                    callId=self.call_id,
                    text=text,
                    detail="识别到电话助理/秘书提示，先说明身份和来电原因，等待真人转接。",
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
                threading.Thread(target=self._speak, args=(reply, "call_screening", generation), daemon=True).start()
                continue
            if not self._human_speech_confirmed:
                self._human_speech_confirmed = True
                self.logger.emit(
                    "human_speech_confirmed",
                    callId=self.call_id,
                    text=text,
                    detail="已识别到真人客户语音，可以进入实时对话。",
                )
            intent, node = _classify_intent(text)
            if intent == "系统提示":
                self.logger.emit("intent", callId=self.call_id, text=text, intent=intent, node=node)
                continue
            turn_count, fallback_reply = self._reply_for_turn(text, intent)
            history_snapshot = list(self._conversation_history)
            reply_result = generate_realtime_reply(text, intent, "您的门店", fallback_reply, history_snapshot)
            if self.stop_event.is_set():
                continue
            reply = reply_result.reply
            self._append_conversation_turn(text, reply)
            self.logger.emit("intent", callId=self.call_id, text=text, intent=intent, node=node, turnCount=turn_count)
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
            close_after = intent in {"明确拒绝", "礼貌结束"}
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
        self._conversation_history.append({"role": "user", "content": customer_text.strip()})
        self._conversation_history.append({"role": "assistant", "content": assistant_reply.strip()})
        if len(self._conversation_history) > 8:
            del self._conversation_history[: len(self._conversation_history) - 8]

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
        with self.generation_lock:
            self.speech_generation += 1
            generation = self.speech_generation
        self.interrupt_event.set()
        if now - self._last_barge_at > 0.8:
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
        return generation

    def _speak(self, text: str, reason: str, generation: int, close_after: bool = False) -> None:
        if self.stop_event.is_set():
            return
        self._mark_speech_job_started()
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
        if close_after and not interrupted:
            self._close_after_terminal_reply("customer_rejected")

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
            self._audio_capture.write_outbound(scaled_frame)
        self._send_frame(AUDIO_SOCKET_KIND_AUDIO, scaled_frame)
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

    def _mark_speech_job_started(self) -> None:
        with self.speech_state_lock:
            self.speech_jobs += 1
            self.speaking_event.set()

    def _mark_speech_job_finished(self) -> None:
        with self.speech_state_lock:
            self.speech_jobs = max(0, self.speech_jobs - 1)
            if self.speech_jobs == 0:
                self.speaking_event.clear()

    def _close_after_terminal_reply(self, reason: str) -> None:
        self.logger.emit("call_closing", callId=self.call_id, reason=reason)
        self.stop_event.set()
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _start_audio_capture(self) -> None:
        if not self.config.debug_audio_capture_enabled or not self.call_id or self._audio_capture:
            return
        try:
            self._audio_capture = CallAudioCapture(self.call_id, self.config.debug_audio_capture_dir)
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("audio_capture_error", callId=self.call_id, error=str(exc))
            return
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


class OmniAudioSocketCallSession(AudioSocketCallSession):
    def __init__(self, conn: socket.socket, peer: tuple[str, int], config: BridgeConfig, logger: JsonlEventLogger) -> None:
        super().__init__(conn, peer, config, logger)
        self._omni: OmniRealtimeConversation | None = None
        self._omni_downsample_state = _PcmDownsampleState()
        self._omni_lock = threading.Lock()
        self._omni_generation = 0
        self._omni_response_id = ""
        self._omni_reply_parts: list[str] = []
        self._omni_pending_audio = b""
        self._omni_next_frame_at: float | None = None
        self._omni_playback_lag_events = 0
        self._omni_first_audio_ms = 0
        self._omni_audio_sent = 0
        self._omni_audio_total = 0
        self._omni_response_started_at = 0.0
        self._omni_tts_started = False
        self._omni_closed = False
        self._omni_unavailable_closing = False
        self._omni_barge_collecting = False
        self._omni_barge_started_at = 0.0
        self._omni_barge_last_voice_at = 0.0
        self._omni_barge_forced_response_until = 0.0
        self._omni_barge_forced_audio_started = False
        self._omni_barge_forced_requested = False
        self._omni_barge_server_stopped = False
        self._omni_barge_server_committed = False
        self._human_speech_confirmed = False
        self._last_remote_speech_started_at = 0.0
        self._call_screening_seen = False
        self._call_screening_answered = False
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
            self._start_omni()
            threading.Thread(target=self._speak_opening_after_grace, daemon=True).start()
            self._read_loop()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("call_error", callId=self.call_id, error=str(exc), mode="omni")
        finally:
            self.stop_event.set()
            self.interrupt_event.set()
            self._stop_omni()
            self._stop_audio_capture()
            try:
                self.conn.close()
            except OSError:
                pass
            self.logger.emit("call_disconnected", callId=self.call_id, mode="omni")

    def _start_omni(self) -> None:
        if not settings.dashscope_api_key:
            raise AudioSocketProtocolError("缺少 DASHSCOPE_API_KEY，不能启动 Qwen Omni Realtime。")
        dashscope.api_key = settings.dashscope_api_key
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
        grace = max(0.0, self.config.opening_grace_seconds)
        if grace and self.customer_activity_event.wait(grace):
            self.logger.emit("opening_deferred", callId=self.call_id, reason="remote_audio_detected", mode="omni")
            if not self._wait_for_remote_classification_before_opening("omni"):
                return
        if self._mark_opening_started():
            self.logger.emit("opening_start", callId=self.call_id, mode="omni", text=self.config.opening_text)
            self._request_omni_response(f"电话刚接通。只说这一句，不要改写，不要加问句，不要展开：{self.config.opening_text}")

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

    def handle_omni_speech_started(self) -> None:
        self.customer_activity_event.set()
        now = time.monotonic()
        self._last_remote_audio_at = now
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

    def handle_omni_transcription(self, text: str) -> None:
        clean = " ".join(text.strip().split())
        if not clean:
            return
        self.customer_activity_event.set()
        skip_response_after_forced_barge = False
        replace_forced_barge_response = False
        with self._omni_lock:
            self._omni_barge_collecting = False
            if self._omni_barge_forced_response_until > time.monotonic():
                if self._omni_barge_forced_audio_started:
                    skip_response_after_forced_barge = True
                else:
                    replace_forced_barge_response = True
        signal = classify_realtime_call_input(clean)
        self.logger.emit("asr_final", callId=self.call_id, text=clean, provider="qwen_omni", signal=signal)
        if signal == "system_prompt":
            self._system_prompt_seen = True
            self.logger.emit(
                "system_prompt_ignored",
                callId=self.call_id,
                text=clean,
                detail="识别到运营商或手机系统提示，已忽略，不触发销售回复。",
            )
            return
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
        elif not self._human_speech_confirmed:
            first_human_after_screening = self._call_screening_seen
            self._human_speech_confirmed = True
            self.logger.emit(
                "human_speech_confirmed",
                callId=self.call_id,
                text=clean,
                detail="已识别到真人客户语音，可以进入实时对话。",
            )
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
            ),
        )

    def _handle_audio(self, payload: bytes) -> None:
        if self._audio_capture:
            self._audio_capture.write_inbound(payload)
        rms = _pcm_rms(payload)
        now = time.monotonic()
        if rms >= self.config.barge_rms_threshold:
            self.customer_activity_event.set()
            self._last_remote_audio_at = now
        if self.speaking_event.is_set() and self._omni_local_barge_ready():
            if rms >= self.config.barge_rms_threshold:
                self._loud_frames += 1
            else:
                self._loud_frames = 0
            if self._loud_frames >= self.config.barge_frames and now - self._last_barge_at > 0.8:
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
        self._maybe_commit_omni_barge_turn(now, rms)

    def _omni_local_barge_ready(self) -> bool:
        with self._omni_lock:
            return self._omni_tts_started and self._omni_audio_sent >= OMNI_LOCAL_BARGE_MIN_SENT_BYTES

    def _release_omni_playback_after_barge(self, source: str, now: float | None = None) -> None:
        now = now or time.monotonic()
        with self.speech_state_lock:
            self.speech_jobs = 0
            self.speaking_event.clear()
        with self._omni_lock:
            self._omni_pending_audio = b""
            self._omni_next_frame_at = None
            self._omni_barge_collecting = True
            self._omni_barge_started_at = now
            self._omni_barge_last_voice_at = now
            self._omni_barge_forced_requested = False
            self._omni_barge_server_stopped = False
            self._omni_barge_server_committed = False
        self._loud_frames = 0
        self.logger.emit(
            "barge_recovery_ready",
            callId=self.call_id,
            source=source,
            detail="已停止本地播放并恢复监听，等待客户本轮语音最终识别后再回复。",
        )

    def _maybe_commit_omni_barge_turn(self, now: float, rms: int) -> None:
        if rms >= self.config.barge_rms_threshold:
            with self._omni_lock:
                if self._omni_barge_collecting:
                    self._omni_barge_last_voice_at = now
        with self._omni_lock:
            collecting = self._omni_barge_collecting
            started_at = self._omni_barge_started_at
            last_voice_at = self._omni_barge_last_voice_at
            forced_requested = self._omni_barge_forced_requested
            if not collecting or forced_requested:
                return
            elapsed = now - started_at
            silence = now - last_voice_at
            should_commit = elapsed >= OMNI_BARGE_RECOVERY_MIN_SECONDS and (
                silence >= OMNI_BARGE_RECOVERY_SILENCE_SECONDS
                or elapsed >= OMNI_BARGE_RECOVERY_MAX_SECONDS
            )
            if not should_commit:
                return
            self._omni_barge_collecting = False
            self._omni_barge_forced_requested = True
            self._omni_barge_forced_response_until = now + OMNI_BARGE_FORCED_RESPONSE_SKIP_SECONDS
            self._omni_barge_forced_audio_started = False
        if not self._omni or self.stop_event.is_set():
            return
        self.logger.emit(
            "barge_turn_committed",
            callId=self.call_id,
            elapsedMs=int(elapsed * 1000),
            silenceMs=int(silence * 1000),
            detail="客户打断后短暂停顿，已在一秒内请求恢复回复；若随后转写到达会改用转写回复。",
        )
        self._request_omni_response(
            "客户插话后继续说了内容。请根据刚才提交的客户语音直接回答。"
            "如果语音不完整或客户没有给出具体问题，禁止猜费用、效果、美团、餐饮或美业。"
            "只自然澄清一句：您刚才是问我身份，还是问具体做什么？"
            "不要解释技术状态，不要说被打断，不要说没听完整，不要沉默。"
        )

    def start_omni_response(self, response_id: str) -> None:
        with self.generation_lock:
            self.speech_generation += 1
            generation = self.speech_generation
        with self._omni_lock:
            self._omni_generation = generation
            self._omni_response_id = response_id
            self._omni_reply_parts = []
            self._omni_pending_audio = b""
            self._omni_next_frame_at = None
            self._omni_playback_lag_events = 0
            self._omni_first_audio_ms = 0
            self._omni_audio_sent = 0
            self._omni_audio_total = 0
            self._omni_response_started_at = time.perf_counter()
            self._omni_tts_started = False
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
        text = (pending_text or "").strip()
        if signal == "call_screening":
            return "您好，我这边做视频号团购到店获客，来电想确认门店微信同城曝光合作，麻烦转接负责人，谢谢。"
        if signal in {"identity_handoff", "human_greeting"}:
            return "您好，我在。我是做视频号团购到店获客的，来电是确认微信同城曝光这块。"
        if signal == "audio_issue":
            return "我短说：我是做视频号团购到店获客的，帮门店做套餐和微信同城曝光。"
        if signal == "repetition_complaint":
            return "明白，我不重复。您想听费用、效果，还是和美团区别？"
        if signal == "direct_answer_only":
            return "明白，不推资料。您直接问费用、效果或流程，我按问题答。"
        if signal in {"terminal_close", "rejection"}:
            return "好的，不打扰了，再见。"
        if any(keyword in text for keyword in ["费用", "价格", "收费", "要钱", "付费"]):
            return "这是付费服务，费用看套餐和投放节奏，不合适不建议做。"
        if any(keyword in text for keyword in ["美团", "抖音", "大众点评"]):
            return "美团偏搜索成交，视频号偏微信同城曝光和私域沉淀，是补充。"
        if any(keyword in text for keyword in ["效果", "客流", "到店", "保证", "保底"]):
            return "效果不能空口保底，只能先测曝光、咨询和到店数据。"
        return OMNI_NO_AUDIO_FALLBACK_TEXT

    def append_omni_transcript_delta(self, delta: str) -> None:
        if not delta:
            return
        with self._omni_lock:
            self._omni_reply_parts.append(delta)

    def finish_omni_transcript(self, transcript: str) -> None:
        with self._omni_lock:
            reply = transcript.strip() or "".join(self._omni_reply_parts).strip()
            pending_text = self._omni_pending_customer_text
            pending_signal = self._omni_pending_signal
        if reply:
            if pending_text and pending_signal != "call_screening":
                self._append_conversation_turn(pending_text, reply)
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

    def play_omni_audio_delta(self, delta: str) -> None:
        if not delta:
            return
        try:
            audio = base64.b64decode(delta)
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("omni_audio_decode_error", callId=self.call_id, error=str(exc))
            return
        with self.playback_lock:
            with self._omni_lock:
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
                    self.logger.emit(
                        "tts_start",
                        callId=self.call_id,
                        reason="omni_response",
                        text="",
                        bytes=len(pcm_8k),
                        synthMs=self._omni_first_audio_ms,
                        firstAudioMs=self._omni_first_audio_ms,
                        voice=self.config.omni_voice,
                        voiceType="omni",
                        model=self.config.omni_model,
                        streaming=True,
                        generation=generation,
                    )
                self._omni_pending_audio += pcm_8k
                pending = self._omni_pending_audio
                next_frame_at = self._omni_next_frame_at
                lag_events = self._omni_playback_lag_events
            while len(pending) >= PCM_FRAME_BYTES:
                if self.stop_event.is_set() or self._speech_is_obsolete(generation):
                    break
                frame = pending[:PCM_FRAME_BYTES]
                pending = pending[PCM_FRAME_BYTES:]
                next_frame_at, lag_events = self._send_audio_frame_at_cadence(
                    frame,
                    next_frame_at,
                    lag_events,
                    "omni_response",
                    generation,
                )
                with self._omni_lock:
                    self._omni_audio_sent += len(frame)
            with self._omni_lock:
                self._omni_pending_audio = pending
                self._omni_next_frame_at = next_frame_at
                self._omni_playback_lag_events = lag_events

    def finish_omni_response(self, response_id: str = "") -> None:
        with self._omni_lock:
            current_response_id = self._omni_response_id
        if response_id and current_response_id and response_id != current_response_id:
            self.logger.emit(
                "omni_stale_response_done",
                callId=self.call_id,
                responseId=response_id,
                currentResponseId=current_response_id,
            )
            return
        with self.playback_lock:
            with self._omni_lock:
                generation = self._omni_generation
                pending = self._omni_pending_audio
                next_frame_at = self._omni_next_frame_at
                lag_events = self._omni_playback_lag_events
            if pending and not self.stop_event.is_set() and not self._speech_is_obsolete(generation):
                padded = pending.ljust(PCM_FRAME_BYTES, b"\x00")
                next_frame_at, lag_events = self._send_audio_frame_at_cadence(
                    padded,
                    next_frame_at,
                    lag_events,
                    "omni_response",
                    generation,
                )
                with self._omni_lock:
                    self._omni_audio_sent += len(pending)
                    self._omni_pending_audio = b""
                    self._omni_next_frame_at = next_frame_at
                    self._omni_playback_lag_events = lag_events
        with self._omni_lock:
            generation = self._omni_generation
            audio_sent = self._omni_audio_sent
            audio_total = self._omni_audio_total
            first_audio_ms = self._omni_first_audio_ms
            reply = "".join(self._omni_reply_parts).strip()
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


def synthesize_tts_pcm(text: str, config: BridgeConfig) -> bytes:
    dashscope.api_key = settings.dashscope_api_key
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
    if not settings.dashscope_api_key:
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

    dashscope.api_key = settings.dashscope_api_key
    callback = Callback()
    tts = QwenTtsRealtime(model=config.tts_model, callback=callback, workspace=config.workspace)
    downsample_state = _PcmDownsampleState()
    try:
        tts.connect()
        tts.update_session(
            voice=config.tts_voice_id,
            response_format=QwenAudioFormat.PCM_24000HZ_MONO_16BIT,
            mode="commit",
            language_type=settings.dashscope_system_tts_language_type,
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
    voice = resolve_tts_voice(args.voice_id, args.voice_name)
    workspace = settings.dashscope_workspace.strip() or None
    return BridgeConfig(
        bind_host=args.host or settings.asterisk_audio_socket_bind_host,
        port=int(args.port or settings.asterisk_audio_socket_port),
        asr_model=args.asr_model or settings.realtime_asr_model,
        tts_model=args.tts_model or voice.tts_model,
        tts_voice_id=voice.voice_id,
        tts_voice_name=voice.voice_name,
        tts_voice_type=voice.voice_type,
        conversation_mode=(args.conversation_mode or settings.realtime_conversation_mode or "pipeline").strip().lower(),
        omni_model=(args.omni_model or settings.dashscope_omni_realtime_model).strip(),
        omni_url=(args.omni_url or settings.dashscope_omni_realtime_url).strip(),
        omni_voice=(args.omni_voice or settings.dashscope_omni_realtime_voice or voice.voice_id or "Serena").strip(),
        omni_input_transcription_model=(
            args.omni_input_transcription_model or settings.dashscope_omni_input_transcription_model
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
    )


@dataclass(frozen=True)
class ResolvedTtsVoice:
    voice_id: str
    voice_name: str
    voice_type: str
    tts_model: str


def resolve_tts_voice(explicit_voice_id: str | None = None, explicit_voice_name: str | None = None) -> ResolvedTtsVoice:
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
                tts_model=settings.dashscope_tts_model,
            )
        voice_param = _qwen_voice_param(voice_id)
        return ResolvedTtsVoice(
            voice_id=voice_param,
            voice_name=voice_name or _qwen_voice_display_name(voice_param),
            voice_type="system",
            tts_model=settings.dashscope_realtime_tts_model,
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
                    tts_model=settings.dashscope_tts_model,
                )
        raise RuntimeError("没有可用于实时电话 TTS 的复刻 voice_id，请先在声音档案训练可用音色或设置 REALTIME_TTS_VOICE_ID。")

    default_voice = _qwen_voice_param(settings.dashscope_realtime_tts_voice or "Ethan")
    return ResolvedTtsVoice(
        voice_id=default_voice,
        voice_name=voice_name or _qwen_voice_display_name(default_voice),
        voice_type="system",
        tts_model=settings.dashscope_realtime_tts_model,
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
        "dashscopeKeyConfigured": bool(settings.dashscope_api_key.strip()),
        "workspaceConfigured": bool(config.workspace),
        "logPath": str(config.log_path),
        "bargeRmsThreshold": config.barge_rms_threshold,
        "bargeFrames": config.barge_frames,
        "ttsGain": config.tts_gain,
        "openingGraceSeconds": config.opening_grace_seconds,
        "debugAudioCaptureEnabled": config.debug_audio_capture_enabled,
        "debugAudioCaptureDir": str(config.debug_audio_capture_dir),
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
