from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class FlightEvalResult:
    call_id: str
    trace_path: str
    passed: bool
    issues: list[str]
    metrics: dict[str, int | None]

    def as_dict(self) -> dict[str, Any]:
        return {
            "callId": self.call_id,
            "tracePath": self.trace_path,
            "passed": self.passed,
            "issues": self.issues,
            "metrics": self.metrics,
        }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _event_ms(event: dict[str, Any]) -> int | None:
    value = event.get("monotonicMs")
    return value if isinstance(value, int) else None


def _first_ms(events: list[dict[str, Any]], *event_types: str) -> int | None:
    wanted = set(event_types)
    for event in events:
        if event.get("type") in wanted:
            return _event_ms(event)
    return None


def _latency_after(events: list[dict[str, Any]], start_type: str, end_type: str) -> int | None:
    start_ms: int | None = None
    for event in events:
        event_type = str(event.get("type") or "")
        event_ms = _event_ms(event)
        if event_ms is None:
            continue
        if event_type == start_type:
            start_ms = event_ms
        elif event_type == end_type and start_ms is not None:
            return max(0, event_ms - start_ms)
    return None


def evaluate_trace(
    trace_path: Path,
    *,
    max_opening_ms: int,
    max_turn_ms: int,
    max_barge_clear_ms: int,
) -> FlightEvalResult:
    events = _read_jsonl(trace_path)
    call_id = str(events[-1].get("callId") if events else trace_path.parent.name)
    opening_ms = _latency_after(events, "call_connected", "tts_start")
    turn_ms = _latency_after(events, "turn_committed", "tts_start")
    barge_clear_ms = _latency_after(events, "barge_in", "playback_cleared")
    first_in_ms = _first_ms(events, "audio_in_first_frame")
    first_out_ms = _first_ms(events, "audio_out_first_frame")
    issues: list[str] = []
    if opening_ms is None:
        issues.append("missing_opening_tts_start")
    elif opening_ms > max_opening_ms:
        issues.append(f"opening_latency:{opening_ms}ms>{max_opening_ms}ms")
    if turn_ms is None:
        issues.append("missing_turn_to_tts")
    elif turn_ms > max_turn_ms:
        issues.append(f"turn_latency:{turn_ms}ms>{max_turn_ms}ms")
    if any(event.get("type") == "barge_in" for event in events):
        if barge_clear_ms is None:
            issues.append("missing_barge_playback_clear")
        elif barge_clear_ms > max_barge_clear_ms:
            issues.append(f"barge_clear:{barge_clear_ms}ms>{max_barge_clear_ms}ms")
    if first_in_ms is None:
        issues.append("missing_inbound_audio")
    if first_out_ms is None:
        issues.append("missing_outbound_audio")
    return FlightEvalResult(
        call_id=call_id,
        trace_path=str(trace_path),
        passed=not issues,
        issues=issues,
        metrics={
            "openingMs": opening_ms,
            "turnToTtsMs": turn_ms,
            "bargeClearMs": barge_clear_ms,
            "firstInboundAudioMs": first_in_ms,
            "firstOutboundAudioMs": first_out_ms,
        },
    )


def find_trace_files(root: Path, call_id: str | None = None) -> list[Path]:
    if call_id:
        return [root / call_id / "trace.jsonl"]
    return sorted(path for path in root.glob("*/trace.jsonl") if path.is_file())


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate recorded realtime phone-call flight traces.")
    parser.add_argument("--root", default=settings.realtime_flight_recorder_dir)
    parser.add_argument("--call-id", default="")
    parser.add_argument("--max-opening-ms", type=int, default=800)
    parser.add_argument("--max-turn-ms", type=int, default=1200)
    parser.add_argument("--max-barge-clear-ms", type=int, default=400)
    args = parser.parse_args()

    root = Path(args.root).expanduser()
    results: list[FlightEvalResult] = []
    for trace_path in find_trace_files(root, args.call_id or None):
        if trace_path.exists():
            results.append(
                evaluate_trace(
                    trace_path,
                    max_opening_ms=args.max_opening_ms,
                    max_turn_ms=args.max_turn_ms,
                    max_barge_clear_ms=args.max_barge_clear_ms,
                )
            )
    payload = {
        "ok": bool(results) and all(result.passed for result in results),
        "traceCount": len(results),
        "results": [result.as_dict() for result in results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
