from __future__ import annotations

import os
import re
import struct
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.config import settings


@dataclass(frozen=True)
class CallRecordingArtifact:
    relative_path: str
    mime_type: str
    size_bytes: int


def call_recording_root() -> Path:
    configured = Path(settings.livekit_call_recording_dir).expanduser()
    if configured.is_absolute():
        return configured.resolve()
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / configured).resolve()


def resolve_call_recording_path(relative_path: str) -> Path:
    root = call_recording_root()
    candidate = (root / str(relative_path or "")).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("录音路径越界")
    return candidate


class CallAudioRecorder:
    """Record customer and assistant PCM streams into one time-aligned WAV."""

    def __init__(
        self,
        action_id: str,
        *,
        root: Path | None = None,
        sample_rate: int = 24000,
    ) -> None:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(action_id or "call")).strip("-") or "call"
        self._root = (root or call_recording_root()).resolve()
        date_path = datetime.utcnow().strftime("%Y/%m/%d")
        self._directory = self._root / date_path
        self._directory.mkdir(parents=True, exist_ok=True)
        self._relative_path = f"{date_path}/{safe_id}.wav"
        self._final_path = self._root / self._relative_path
        self._temp_paths = {
            "customer": self._directory / f".{safe_id}.customer.pcm",
            "assistant": self._directory / f".{safe_id}.assistant.pcm",
        }
        self._sample_rate = max(8000, int(sample_rate))
        self._lock = threading.Lock()
        self._files: dict[str, object] = {}
        self._positions = {"customer": 0, "assistant": 0}
        self._started_at = 0.0
        self._active = False
        self._finalized = False
        self._artifact: CallRecordingArtifact | None = None

    def start(self) -> None:
        with self._lock:
            if self._active or self._finalized:
                return
            opened: dict[str, object] = {}
            try:
                for track, path in self._temp_paths.items():
                    opened[track] = path.open("wb")
            except Exception:
                for handle in opened.values():
                    handle.close()
                for path in self._temp_paths.values():
                    path.unlink(missing_ok=True)
                raise
            self._files = opened
            self._started_at = time.monotonic()
            self._active = True

    def write_customer(self, pcm: bytes, sample_rate: int, num_channels: int = 1) -> None:
        self._write("customer", pcm, sample_rate, num_channels)

    def write_assistant(self, pcm: bytes, sample_rate: int, num_channels: int = 1) -> None:
        self._write("assistant", pcm, sample_rate, num_channels)

    def _write(self, track: str, pcm: bytes, sample_rate: int, num_channels: int) -> None:
        if not pcm:
            return
        normalized = _normalize_pcm16_mono(
            bytes(pcm),
            source_rate=max(1, int(sample_rate)),
            target_rate=self._sample_rate,
            num_channels=max(1, int(num_channels)),
        )
        if not normalized:
            return
        with self._lock:
            if not self._active or self._finalized:
                return
            handle = self._files[track]
            current_position = self._positions[track]
            wall_position = int((time.monotonic() - self._started_at) * self._sample_rate)
            target_position = max(current_position, wall_position)
            gap_samples = target_position - current_position
            if gap_samples > 0:
                handle.write(b"\x00\x00" * gap_samples)
            handle.write(normalized)
            self._positions[track] = target_position + len(normalized) // 2

    def finalize(self) -> CallRecordingArtifact | None:
        with self._lock:
            if self._finalized:
                return self._artifact
            self._finalized = True
            self._active = False
            for handle in self._files.values():
                handle.flush()
                handle.close()
            self._files.clear()
            total_samples = max(self._positions.values())

        temp_wav = self._final_path.with_suffix(".wav.tmp")
        try:
            if total_samples <= 0:
                return None
            with (
                self._temp_paths["customer"].open("rb") as customer,
                self._temp_paths["assistant"].open("rb") as assistant,
                wave.open(str(temp_wav), "wb") as output,
            ):
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(self._sample_rate)
                remaining = total_samples
                while remaining > 0:
                    sample_count = min(4096, remaining)
                    customer_pcm = customer.read(sample_count * 2).ljust(sample_count * 2, b"\x00")
                    assistant_pcm = assistant.read(sample_count * 2).ljust(sample_count * 2, b"\x00")
                    output.writeframesraw(_mix_pcm16(customer_pcm, assistant_pcm))
                    remaining -= sample_count
            os.replace(temp_wav, self._final_path)
            self._artifact = CallRecordingArtifact(
                relative_path=self._relative_path,
                mime_type="audio/wav",
                size_bytes=self._final_path.stat().st_size,
            )
            return self._artifact
        finally:
            temp_wav.unlink(missing_ok=True)
            for path in self._temp_paths.values():
                path.unlink(missing_ok=True)


def _normalize_pcm16_mono(
    pcm: bytes,
    *,
    source_rate: int,
    target_rate: int,
    num_channels: int,
) -> bytes:
    usable = len(pcm) - (len(pcm) % (2 * num_channels))
    if usable <= 0:
        return b""
    frame_count = usable // (2 * num_channels)
    values = struct.unpack(f"<{frame_count * num_channels}h", pcm[:usable])
    if num_channels == 1:
        mono = values
    else:
        mono = tuple(
            int(sum(values[index : index + num_channels]) / num_channels)
            for index in range(0, len(values), num_channels)
        )
    if source_rate == target_rate:
        samples = mono
    else:
        output_count = max(1, int(len(mono) * target_rate / source_rate))
        ratio = source_rate / target_rate
        resampled: list[int] = []
        for output_index in range(output_count):
            source_position = output_index * ratio
            left_index = min(int(source_position), len(mono) - 1)
            right_index = min(left_index + 1, len(mono) - 1)
            fraction = source_position - left_index
            resampled.append(int(mono[left_index] * (1 - fraction) + mono[right_index] * fraction))
        samples = resampled
    return struct.pack(f"<{len(samples)}h", *samples)


def _mix_pcm16(customer_pcm: bytes, assistant_pcm: bytes) -> bytes:
    sample_count = min(len(customer_pcm), len(assistant_pcm)) // 2
    if sample_count <= 0:
        return b""
    customer = struct.unpack(f"<{sample_count}h", customer_pcm[: sample_count * 2])
    assistant = struct.unpack(f"<{sample_count}h", assistant_pcm[: sample_count * 2])
    mixed = [max(-32768, min(32767, left + right)) for left, right in zip(customer, assistant, strict=True)]
    return struct.pack(f"<{sample_count}h", *mixed)
