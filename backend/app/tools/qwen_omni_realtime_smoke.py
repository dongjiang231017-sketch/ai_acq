from __future__ import annotations

import argparse
import base64
import json
import queue
import shutil
import subprocess
import tempfile
import time
import wave
from collections import Counter
from pathlib import Path
from typing import Any

import dashscope
from dashscope.audio.qwen_omni import MultiModality, OmniRealtimeCallback, OmniRealtimeConversation

from app.core.config import settings
from app.services.realtime_sales_playbook import build_video_group_buying_sales_instructions


DEFAULT_QUESTION = "你是谁？这个视频号团购要不要付费？效果能不能保证？"


def build_sales_instructions() -> str:
    return build_video_group_buying_sales_instructions()


class SmokeCallback(OmniRealtimeCallback):
    def __init__(self) -> None:
        self.items: queue.Queue[dict[str, Any]] = queue.Queue()
        self.events: list[dict[str, Any]] = []
        self.event_counts: Counter[str] = Counter()
        self.input_transcript = ""
        self.output_transcript = ""
        self.output_audio = bytearray()
        self.error: str | None = None
        self.opened = False
        self.closed = False

    def on_open(self) -> None:
        self.opened = True
        self.items.put({"type": "client.opened"})

    def on_close(self, close_status_code: object, close_msg: object) -> None:
        self.closed = True
        self.items.put(
            {
                "type": "client.closed",
                "code": close_status_code,
                "message": str(close_msg),
            },
        )

    def on_event(self, response: dict[str, Any]) -> None:
        event_type = str(response.get("type") or "")
        self.event_counts[event_type] += 1
        self.events.append(response)
        if event_type == "conversation.item.input_audio_transcription.completed":
            self.input_transcript = str(response.get("transcript") or self.input_transcript)
        elif event_type == "conversation.item.input_audio_transcription.delta":
            text = str(response.get("text") or "")
            stash = str(response.get("stash") or "")
            if text or stash:
                self.input_transcript = text + stash
        elif event_type in {"response.audio_transcript.delta", "response.text.delta"}:
            self.output_transcript += str(response.get("delta") or "")
        elif event_type in {"response.audio_transcript.done", "response.text.done"}:
            self.output_transcript = str(response.get("transcript") or response.get("text") or self.output_transcript)
        elif event_type == "response.audio.delta":
            try:
                self.output_audio.extend(base64.b64decode(str(response.get("delta") or "")))
            except Exception as exc:  # noqa: BLE001
                self.error = f"audio decode failed: {exc}"
        elif event_type == "error" or response.get("error"):
            self.error = json.dumps(response, ensure_ascii=False)[:800]
        self.items.put(response)


def generate_question_pcm(question: str, out_path: Path, voice: str) -> None:
    if not shutil.which("say"):
        raise RuntimeError("本机没有 macOS say，无法自动生成测试语音；请用 --audio-pcm 指定 16k PCM 文件。")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("本机没有 ffmpeg，无法转换测试语音；请用 --audio-pcm 指定 16k PCM 文件。")
    with tempfile.TemporaryDirectory() as tmp_dir:
        aiff_path = Path(tmp_dir) / "question.aiff"
        say_cmd = ["say", "-v", voice, "-o", str(aiff_path), "--", question]
        result = subprocess.run(say_cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            fallback_cmd = ["say", "-o", str(aiff_path), "--", question]
            result = subprocess.run(fallback_cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"生成测试语音失败：{result.stderr.strip() or result.stdout.strip()}")
        ffmpeg_cmd = [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(aiff_path),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(out_path),
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"转换 16k PCM 失败：{result.stderr.strip() or result.stdout.strip()}")


def write_pcm_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def stream_pcm(conversation: OmniRealtimeConversation, pcm_path: Path, chunk_bytes: int, chunk_sleep: float) -> int:
    sent = 0
    with pcm_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            conversation.append_audio(base64.b64encode(chunk).decode("ascii"))
            sent += len(chunk)
            if chunk_sleep > 0:
                time.sleep(chunk_sleep)
    return sent


def drain_queue(items: queue.Queue[dict[str, Any]]) -> None:
    while True:
        try:
            items.get_nowait()
        except queue.Empty:
            return


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    if not settings.dashscope_api_key.strip():
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，不能测试 Qwen Omni Realtime。")

    model = args.model or settings.dashscope_omni_realtime_model
    url = args.url or settings.dashscope_omni_realtime_url
    voice = args.voice or settings.dashscope_omni_realtime_voice
    output_wav = Path(args.output_wav).expanduser() if args.output_wav else None

    with tempfile.TemporaryDirectory() as tmp_dir:
        pcm_path = Path(args.audio_pcm).expanduser() if args.audio_pcm else Path(tmp_dir) / "question.pcm"
        if not args.audio_pcm:
            generate_question_pcm(args.question, pcm_path, args.say_voice)

        callback = SmokeCallback()
        dashscope.api_key = settings.dashscope_api_key
        conversation = OmniRealtimeConversation(
            model=model,
            callback=callback,
            url=url,
            workspace=settings.dashscope_workspace.strip() or None,
        )
        started = time.perf_counter()
        try:
            conversation.connect()
            conversation.update_session(
                output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],
                voice=voice,
                enable_input_audio_transcription=True,
                input_audio_transcription_model=settings.dashscope_omni_input_transcription_model,
                enable_turn_detection=False,
                instructions=build_sales_instructions(),
            )
            sent_bytes = stream_pcm(conversation, pcm_path, args.chunk_bytes, args.chunk_sleep)
            drain_queue(callback.items)
            callback.input_transcript = ""
            callback.output_transcript = ""
            conversation.commit()
            transcription_deadline = time.monotonic() + args.timeout
            while time.monotonic() < transcription_deadline:
                try:
                    item = callback.items.get(timeout=0.2)
                except queue.Empty:
                    if callback.error:
                        break
                    continue
                if item.get("type") == "conversation.item.input_audio_transcription.completed":
                    break
                if callback.error:
                    break
            response_started = time.perf_counter()
            conversation.create_response(output_modalities=[MultiModality.AUDIO, MultiModality.TEXT])
            response_deadline = time.monotonic() + args.timeout
            while time.monotonic() < response_deadline:
                try:
                    item = callback.items.get(timeout=0.2)
                except queue.Empty:
                    if callback.error:
                        break
                    continue
                if item.get("type") == "response.done":
                    break
                if callback.error:
                    break
            if output_wav and callback.output_audio:
                write_pcm_wav(output_wav, bytes(callback.output_audio), sample_rate=24000)
            return {
                "ok": callback.error is None and bool(callback.output_transcript.strip()) and bool(callback.output_audio),
                "model": model,
                "voice": voice,
                "url": url,
                "question": args.question,
                "sentPcmBytes": sent_bytes,
                "inputTranscript": callback.input_transcript,
                "assistantTranscript": callback.output_transcript,
                "outputAudioBytes": len(callback.output_audio),
                "firstTextMs": conversation.get_last_first_text_delay(),
                "firstAudioMs": conversation.get_last_first_audio_delay(),
                "responseWaitMs": int((time.perf_counter() - response_started) * 1000),
                "totalMs": int((time.perf_counter() - started) * 1000),
                "eventCounts": dict(sorted(callback.event_counts.items())),
                "error": callback.error,
                "outputWav": str(output_wav) if output_wav and callback.output_audio else None,
            }
        finally:
            try:
                conversation.close()
            except Exception:
                pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test DashScope Qwen Omni Realtime without placing a phone call.")
    parser.add_argument("--model", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--voice", default="")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--audio-pcm", default="", help="Optional raw 16 kHz mono PCM16 input file.")
    parser.add_argument("--say-voice", default="Tingting", help="macOS say voice used to synthesize the customer test question.")
    parser.add_argument("--chunk-bytes", type=int, default=3200)
    parser.add_argument("--chunk-sleep", type=float, default=0.08)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--output-wav", default="/tmp/ai-acq-qwen-omni-smoke-response.wav")
    return parser.parse_args()


def main() -> None:
    result = run_smoke(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
