from __future__ import annotations

import json
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _safe_call_id(call_id: str) -> str:
    return "".join(char for char in call_id if char.isalnum() or char in {"-", "_"}) or "unknown"


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


@dataclass
class FlightRecorderManifest:
    call_id: str
    root: str
    trace_path: str
    inbound_path: str | None = None
    outbound_path: str | None = None
    outbound_raw_path: str | None = None
    event_count: int = 0
    inbound_bytes: int = 0
    outbound_bytes: int = 0
    outbound_raw_bytes: int = 0
    first_inbound_audio_at: str | None = None
    first_outbound_audio_at: str | None = None
    opened_at: str = field(default_factory=_utc_now)
    closed_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "callId": self.call_id,
            "root": self.root,
            "tracePath": self.trace_path,
            "inboundPath": self.inbound_path,
            "outboundPath": self.outbound_path,
            "outboundRawPath": self.outbound_raw_path,
            "eventCount": self.event_count,
            "inboundBytes": self.inbound_bytes,
            "outboundBytes": self.outbound_bytes,
            "outboundRawBytes": self.outbound_raw_bytes,
            "firstInboundAudioAt": self.first_inbound_audio_at,
            "firstOutboundAudioAt": self.first_outbound_audio_at,
            "openedAt": self.opened_at,
            "closedAt": self.closed_at,
        }


class RealtimeFlightRecorder:
    """Single-call evidence recorder for phone naturalness debugging.

    The global realtime event log shows what the bridge thought happened. This
    recorder stores one call's trace plus optional inbound/outbound audio so a
    reviewer can line up actual phone sound with turn decisions and playback.
    """

    def __init__(
        self,
        call_id: str,
        root: Path,
        *,
        capture_audio: bool,
        sample_rate: int = 8000,
    ) -> None:
        self.call_id = call_id
        self.safe_call_id = _safe_call_id(call_id)
        self.call_root = root.expanduser() / self.safe_call_id
        self.call_root.mkdir(parents=True, exist_ok=True)
        self.trace_path = self.call_root / "trace.jsonl"
        self.manifest_path = self.call_root / "manifest.json"
        self.capture_audio = capture_audio
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._closed = False
        self._inbound: wave.Wave_write | None = None
        self._outbound: wave.Wave_write | None = None
        self._outbound_raw: wave.Wave_write | None = None

        self.manifest = FlightRecorderManifest(
            call_id=call_id,
            root=str(self.call_root),
            trace_path=str(self.trace_path),
        )
        if capture_audio:
            self.manifest.inbound_path = str(self.call_root / "customer.in.wav")
            self.manifest.outbound_path = str(self.call_root / "ai.out.wav")
            self.manifest.outbound_raw_path = str(self.call_root / "ai.raw.wav")
            self._inbound = self._open_wave(Path(self.manifest.inbound_path))
            self._outbound = self._open_wave(Path(self.manifest.outbound_path))
            self._outbound_raw = self._open_wave(Path(self.manifest.outbound_raw_path))
        self.event("flight_recorder_opened", captureAudio=capture_audio, sampleRate=sample_rate)

    def _open_wave(self, path: Path) -> wave.Wave_write:
        handle = wave.open(str(path), "wb")
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(self.sample_rate)
        return handle

    def event(self, event_type: str, **fields: Any) -> None:
        if self._closed:
            return
        payload = {
            "at": _utc_now(),
            "monotonicMs": int(time.monotonic() * 1000),
            "callId": self.call_id,
            "type": event_type,
            **fields,
        }
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            if self._closed:
                return
            with self.trace_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self.manifest.event_count += 1

    def write_inbound(self, payload: bytes) -> None:
        self._write_audio("inbound", self._inbound, payload)

    def write_outbound(self, payload: bytes) -> None:
        self._write_audio("outbound", self._outbound, payload)

    def write_outbound_raw(self, payload: bytes) -> None:
        self._write_audio("outbound_raw", self._outbound_raw, payload)

    def _write_audio(self, direction: str, handle: wave.Wave_write | None, payload: bytes) -> None:
        if not payload:
            return
        with self._lock:
            if self._closed:
                return
            if direction == "inbound":
                self.manifest.inbound_bytes += len(payload)
                if not self.manifest.first_inbound_audio_at:
                    self.manifest.first_inbound_audio_at = _utc_now()
                    self._write_event_locked("audio_in_first_frame", bytes=len(payload))
            elif direction == "outbound":
                self.manifest.outbound_bytes += len(payload)
                if not self.manifest.first_outbound_audio_at:
                    self.manifest.first_outbound_audio_at = _utc_now()
                    self._write_event_locked("audio_out_first_frame", bytes=len(payload))
            elif direction == "outbound_raw":
                self.manifest.outbound_raw_bytes += len(payload)
            if handle is not None:
                handle.writeframesraw(payload)

    def _write_event_locked(self, event_type: str, **fields: Any) -> None:
        payload = {
            "at": _utc_now(),
            "monotonicMs": int(time.monotonic() * 1000),
            "callId": self.call_id,
            "type": event_type,
            **fields,
        }
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.manifest.event_count += 1

    def close(self) -> dict[str, str | None]:
        with self._lock:
            if self._closed:
                return self._close_payload()
            self._closed = True
            for handle in (self._inbound, self._outbound, self._outbound_raw):
                if handle is not None:
                    handle.close()
            self.manifest.closed_at = _utc_now()
            self.manifest_path.write_text(
                json.dumps(self.manifest.as_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return self._close_payload()

    def _close_payload(self) -> dict[str, str | None]:
        return {
            "flightRoot": str(self.call_root),
            "flightTracePath": str(self.trace_path),
            "flightManifestPath": str(self.manifest_path),
            "inboundPath": self.manifest.inbound_path,
            "outboundRawPath": self.manifest.outbound_raw_path,
            "outboundPath": self.manifest.outbound_path,
        }
