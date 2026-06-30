from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import socket
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from dashscope.audio.tts_v2 import SpeechSynthesizer
from dashscope.audio.tts_v2.speech_synthesizer import AudioFormat
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.growth import VoiceCloneRecord
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
            self.call.customer_texts.put(text)

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
        self.customer_texts: queue.Queue[str] = queue.Queue()
        self.stop_event = threading.Event()
        self.interrupt_event = threading.Event()
        self.speaking_event = threading.Event()
        self.send_lock = threading.Lock()
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
            threading.Thread(target=self._speak, args=(self.config.opening_text, "opening"), daemon=True).start()
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
                self.call_id = payload.decode("utf-8", errors="replace")
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
                self.call_id = payload.decode("utf-8", errors="replace")
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
            self._last_barge_at = time.monotonic()
            self.interrupt_event.set()
            self.logger.emit(
                "barge_in",
                callId=self.call_id,
                rms=_pcm_rms(payload),
                detail="客户插话，停止后续 TTS 音频帧并继续听客户说话。",
            )

    def _turn_worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                text = self.customer_texts.get(timeout=0.2)
            except queue.Empty:
                continue
            if not text.strip():
                continue
            intent, node = _classify_intent(text)
            reply = _build_reply(text, intent, "您的门店")
            self.logger.emit("intent", callId=self.call_id, text=text, intent=intent, node=node)
            self.logger.emit("llm_reply", callId=self.call_id, reply=reply, strategy="rules_first")
            self._speak(reply, "reply")

    def _speak(self, text: str, reason: str) -> None:
        if self.stop_event.is_set():
            return
        self.interrupt_event.clear()
        start = time.perf_counter()
        try:
            audio = synthesize_tts_pcm(text, self.config)
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("tts_error", callId=self.call_id, text=text, error=str(exc))
            return
        synth_ms = int((time.perf_counter() - start) * 1000)
        self.logger.emit(
            "tts_start",
            callId=self.call_id,
            reason=reason,
            text=text,
            bytes=len(audio),
            synthMs=synth_ms,
            voice=self.config.tts_voice_name,
        )
        self.speaking_event.set()
        sent = 0
        try:
            for offset in range(0, len(audio), PCM_FRAME_BYTES):
                if self.stop_event.is_set() or self.interrupt_event.is_set():
                    break
                chunk = audio[offset : offset + PCM_FRAME_BYTES]
                self._send_frame(AUDIO_SOCKET_KIND_AUDIO, chunk)
                sent += len(chunk)
                time.sleep(PCM_FRAME_SECONDS)
        finally:
            interrupted = self.interrupt_event.is_set()
            self.speaking_event.clear()
            self.interrupt_event.clear()
            self.logger.emit(
                "tts_interrupted" if interrupted else "tts_done",
                callId=self.call_id,
                reason=reason,
                sentBytes=sent,
                totalBytes=len(audio),
            )

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


def synthesize_tts_pcm(text: str, config: BridgeConfig) -> bytes:
    dashscope.api_key = settings.dashscope_api_key
    synthesizer = SpeechSynthesizer(
        model=config.tts_model,
        voice=config.tts_voice_id,
        format=AudioFormat.PCM_8000HZ_MONO_16BIT,
        workspace=config.workspace,
    )
    audio = synthesizer.call(text, timeout_millis=20000)
    if not audio:
        raise RuntimeError("DashScope TTS 未返回音频。")
    return bytes(audio)


def build_config(args: argparse.Namespace) -> BridgeConfig:
    voice_id, voice_name = resolve_tts_voice(args.voice_id, args.voice_name)
    workspace = settings.dashscope_workspace.strip() or None
    return BridgeConfig(
        bind_host=args.host or settings.asterisk_audio_socket_bind_host,
        port=int(args.port or settings.asterisk_audio_socket_port),
        asr_model=args.asr_model or settings.realtime_asr_model,
        tts_model=args.tts_model or settings.dashscope_tts_model,
        tts_voice_id=voice_id,
        tts_voice_name=voice_name,
        opening_text=args.opening_text or settings.realtime_call_opening_text,
        log_path=Path(args.log_path or settings.realtime_call_event_log_path).expanduser(),
        workspace=workspace,
    )


def resolve_tts_voice(explicit_voice_id: str | None = None, explicit_voice_name: str | None = None) -> tuple[str, str]:
    voice_id = (
        explicit_voice_id
        or os.environ.get("AI_ACQ_REALTIME_TTS_VOICE_ID")
        or os.environ.get("REALTIME_TTS_VOICE_ID")
        or settings.realtime_tts_voice_id
    ).strip()
    voice_name = (explicit_voice_name or settings.realtime_tts_voice_name or "").strip()
    if voice_id:
        return voice_id, voice_name or voice_id

    with SessionLocal() as db:
        record = db.scalar(
            select(VoiceCloneRecord)
            .where(VoiceCloneRecord.status == "可用", VoiceCloneRecord.external_voice_id != "")
            .order_by(VoiceCloneRecord.completed_at.desc(), VoiceCloneRecord.created_at.desc())
        )
        if record and record.external_voice_id:
            return record.external_voice_id, record.cloned_voice_name or record.external_voice_id
    raise RuntimeError("没有可用于实时电话 TTS 的复刻 voice_id，请先在声音档案训练可用音色或设置 REALTIME_TTS_VOICE_ID。")


def serve(config: BridgeConfig, stop_event: threading.Event) -> None:
    logger = JsonlEventLogger(config.log_path)
    logger.emit(
        "bridge_start",
        bind=f"{config.bind_host}:{config.port}",
        asrModel=config.asr_model,
        ttsModel=config.tts_model,
        voice=config.tts_voice_name,
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
