from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import signal
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from dashscope.audio.tts_v2 import SpeechSynthesizer
from dashscope.audio.tts_v2.speech_synthesizer import AudioFormat as CosyAudioFormat
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.growth import VoiceCloneRecord
from app.services.realtime_llm import generate_realtime_reply
from app.services.realtime_outbound import _build_reply, _classify_intent


AUDIO_SOCKET_KIND_HANGUP = 0x00
AUDIO_SOCKET_KIND_UUID = 0x01
AUDIO_SOCKET_KIND_DTMF = 0x03
AUDIO_SOCKET_KIND_AUDIO = 0x10
AUDIO_SOCKET_KIND_ERROR = 0xFF
PCM_FRAME_BYTES = 320
PCM_FRAME_SECONDS = 0.02


@dataclass(frozen=True)
class BridgeConfig:
    bind_host: str
    port: int
    asr_model: str
    tts_model: str
    tts_voice_id: str
    tts_voice_name: str
    tts_voice_type: str
    opening_text: str
    log_path: Path
    workspace: str | None
    barge_rms_threshold: int = 900
    barge_frames: int = 4


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
        self.call.logger.emit("asr_error", callId=self.call.call_id, error=str(message))

    def on_complete(self) -> None:
        self.call.logger.emit("asr_complete", callId=self.call.call_id)

    def on_close(self) -> None:
        self.call.logger.emit("asr_close", callId=self.call.call_id)


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
        self.send_lock = threading.Lock()
        self.playback_lock = threading.Lock()
        self.generation_lock = threading.Lock()
        self.speech_state_lock = threading.Lock()
        self.speech_generation = 0
        self.speech_jobs = 0
        self._loud_frames = 0
        self._last_barge_at = 0.0
        self._recognition: Recognition | None = None
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
            threading.Thread(target=self._speak, args=(self.config.opening_text, "opening", 0), daemon=True).start()
            self._read_loop()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("call_error", callId=self.call_id, error=str(exc))
        finally:
            self.stop_event.set()
            self.interrupt_event.set()
            self._stop_asr()
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
        if self._recognition:
            self._recognition.send_audio_frame(payload)
        if self.speaking_event.is_set() and _pcm_rms(payload) >= self.config.barge_rms_threshold:
            self._loud_frames += 1
        else:
            self._loud_frames = 0
        if self._loud_frames >= self.config.barge_frames and time.monotonic() - self._last_barge_at > 0.8:
            self.cancel_pending_speech("客户插话，停止后续 TTS 音频帧并继续听客户说话。", source="rms", rms=_pcm_rms(payload))

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
            intent, node = _classify_intent(text)
            fallback_reply = _build_reply(text, intent, "您的门店")
            reply_result = generate_realtime_reply(text, intent, "您的门店", fallback_reply)
            if self.stop_event.is_set():
                continue
            reply = reply_result.reply
            self.logger.emit("intent", callId=self.call_id, text=text, intent=intent, node=node)
            self.logger.emit(
                "llm_reply",
                callId=self.call_id,
                reply=reply,
                strategy=reply_result.strategy,
                latencyMs=reply_result.latency_ms,
                fallbackUsed=reply_result.fallback_used,
                error=reply_result.error,
            )
            close_after = intent == "明确拒绝"
            reason = "closing_reply" if close_after else "reply"
            threading.Thread(target=self._speak, args=(reply, reason, generation, close_after), daemon=True).start()

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
                        self._send_frame(AUDIO_SOCKET_KIND_AUDIO, frame)
                        sent += len(frame)
                        time.sleep(PCM_FRAME_SECONDS)
                    if self.stop_event.is_set() or self._speech_is_obsolete(generation):
                        break
                if pending and not self.stop_event.is_set() and not self._speech_is_obsolete(generation):
                    self._send_frame(AUDIO_SOCKET_KIND_AUDIO, pending)
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
            self.logger.emit("call_closing", callId=self.call_id, reason="customer_rejected")
            self.stop_event.set()
            try:
                self.conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

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
    usable = (len(data) // 6) * 6
    state.leftover = data[usable:]
    if usable <= 0:
        return b""
    output = bytearray(usable // 3)
    output.clear()
    for offset in range(0, usable, 6):
        first = int.from_bytes(data[offset : offset + 2], "little", signed=True)
        second = int.from_bytes(data[offset + 2 : offset + 4], "little", signed=True)
        third = int.from_bytes(data[offset + 4 : offset + 6], "little", signed=True)
        sample = int((first + second + third) / 3)
        output.extend(max(-32768, min(32767, sample)).to_bytes(2, "little", signed=True))
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
        opening_text=args.opening_text or settings.realtime_call_opening_text,
        log_path=Path(args.log_path or settings.realtime_call_event_log_path).expanduser(),
        workspace=workspace,
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
        asrModel=config.asr_model,
        ttsModel=config.tts_model,
        voice=config.tts_voice_name,
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
            threading.Thread(
                target=AudioSocketCallSession(conn, peer, config, logger).run,
                name=f"ai-acq-audiosocket-{peer[0]}:{peer[1]}",
                daemon=True,
            ).start()
    logger.emit("bridge_stop")


def config_summary(config: BridgeConfig) -> dict[str, object]:
    return {
        "bind": f"{config.bind_host}:{config.port}",
        "asrModel": config.asr_model,
        "ttsModel": config.tts_model,
        "voice": config.tts_voice_name,
        "voiceType": config.tts_voice_type,
        "voiceConfigured": bool(config.tts_voice_id),
        "dashscopeKeyConfigured": bool(settings.dashscope_api_key.strip()),
        "workspaceConfigured": bool(config.workspace),
        "logPath": str(config.log_path),
        "bargeRmsThreshold": config.barge_rms_threshold,
        "bargeFrames": config.barge_frames,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AI ACQ Asterisk AudioSocket realtime bridge.")
    parser.add_argument("--host", help="TCP bind host for Asterisk AudioSocket.")
    parser.add_argument("--port", type=int, help="TCP port for Asterisk AudioSocket.")
    parser.add_argument("--voice-id", help="DashScope CosyVoice voice_id for realtime TTS.")
    parser.add_argument("--voice-name", help="Human label for the realtime TTS voice.")
    parser.add_argument("--asr-model", help="DashScope realtime ASR model.")
    parser.add_argument("--tts-model", help="DashScope realtime TTS model.")
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
