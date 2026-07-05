from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.core.config import settings
from app.services.realtime_call_learning import (
    build_realtime_learning_instruction,
    record_realtime_call_learning,
    summarize_realtime_learning,
)
from app.services.realtime_route_benchmark import build_realtime_route_benchmark


def evaluate_learning_and_route_benchmark() -> dict[str, object]:
    old_learning_path = settings.realtime_call_learning_path
    old_event_path = settings.realtime_call_event_log_path
    old_dashscope_key = settings.dashscope_api_key
    old_deepseek_key = settings.deepseek_api_key
    old_gateway_mode = settings.telephony_gateway_mode
    old_live_call_enabled = settings.asterisk_live_call_enabled
    old_audio_host = settings.asterisk_audio_socket_host
    old_audio_port = settings.asterisk_audio_socket_port
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings.realtime_call_learning_path = str(root / "learning.jsonl")
        settings.realtime_call_event_log_path = str(root / "events.jsonl")
        settings.dashscope_api_key = "configured-for-eval"
        settings.deepseek_api_key = "configured-for-eval"
        settings.telephony_gateway_mode = "simulator"
        settings.asterisk_live_call_enabled = False
        settings.asterisk_audio_socket_host = "127.0.0.1"
        settings.asterisk_audio_socket_port = 1
        try:
            lesson = record_realtime_call_learning(
                call_id="eval-call-18100000000",
                conversation_history=[
                    {"role": "user", "content": "18107090349 你老是说明白，能不能直接说？"},
                    {"role": "assistant", "content": "明白。美团偏搜索下单，视频号偏微信同城推荐。"},
                    {"role": "assistant", "content": "明白。美团偏搜索下单，视频号偏微信同城推荐。"},
                    {"role": "user", "content": "你不要像机器人一样念稿。"},
                ],
                close_reason="customer_hangup",
            )
            instruction = build_realtime_learning_instruction(limit=3)
            summary = summarize_realtime_learning(limit=3)
            serialized = json.dumps(lesson, ensure_ascii=False)
            results.append(
                _result(
                    "learning_redacts_phone",
                    "18107090349" not in serialized and "[手机号已脱敏]" in serialized,
                    serialized,
                )
            )
            results.append(
                _result(
                    "learning_generates_quality_tags",
                    {"repeated_reply", "naturalness_repair"}.issubset(set(summary["qualityTags"])),
                    str(summary["qualityTags"]),
                )
            )
            results.append(
                _result(
                    "learning_instruction_guides_next_call",
                    "下一通必须改进" in instruction and "真人感" in instruction and "避免复读" in instruction,
                    instruction,
                )
            )
            route_options = [
                {
                    "key": "omni",
                    "label": "极速人声 Omni",
                    "estimatedLatencyMs": 720,
                    "estimatedAiCostPerMinute": 0.09,
                },
                {
                    "key": "pipeline",
                    "label": "低成本分段 Pipeline",
                    "estimatedLatencyMs": 1075,
                    "estimatedAiCostPerMinute": 0.04,
                },
            ]
            no_event_report = build_realtime_route_benchmark(
                current_route="pipeline",
                bridge_ready=False,
                route_options=route_options,
            )
            results.append(
                _result(
                    "route_benchmark_defaults_low_cost",
                    no_event_report["recommendedRoute"] == "pipeline" and no_event_report["lowCostFirst"] is True,
                    str(no_event_report),
                )
            )
            _write_slow_event_log(Path(settings.realtime_call_event_log_path))
            slow_report = build_realtime_route_benchmark(
                current_route="pipeline",
                bridge_ready=False,
                route_options=route_options,
            )
            results.append(
                _result(
                    "route_benchmark_surfaces_slow_turn",
                    slow_report["latestTurnResponseMs"] == 1800
                    and any(
                        "超过1秒目标" in " ".join(item["risks"])
                        for item in slow_report["benchmarks"]
                        if item["key"] == "pipeline"
                    ),
                    str(slow_report),
                )
            )
        finally:
            settings.realtime_call_learning_path = old_learning_path
            settings.realtime_call_event_log_path = old_event_path
            settings.dashscope_api_key = old_dashscope_key
            settings.deepseek_api_key = old_deepseek_key
            settings.telephony_gateway_mode = old_gateway_mode
            settings.asterisk_live_call_enabled = old_live_call_enabled
            settings.asterisk_audio_socket_host = old_audio_host
            settings.asterisk_audio_socket_port = old_audio_port
    passed = all(item["passed"] for item in results)
    return {"passed": passed, "results": results}


def _write_slow_event_log(path: Path) -> None:
    events = [
        {"type": "call_connected", "callId": "slow-eval", "at": "2026-07-05T00:00:00Z"},
        {"type": "human_speech_confirmed", "callId": "slow-eval", "text": "你是谁", "at": "2026-07-05T00:00:01Z"},
        {"type": "asr_final", "callId": "slow-eval", "text": "你是谁", "at": "2026-07-05T00:00:01.200Z"},
        {
            "type": "llm_reply",
            "callId": "slow-eval",
            "reply": "我是做视频号团购到店获客的。",
            "latencyMs": 900,
            "at": "2026-07-05T00:00:02.000Z",
        },
        {
            "type": "tts_start",
            "callId": "slow-eval",
            "raw": {"sentBytes": 320, "firstAudioMs": 1800},
            "at": "2026-07-05T00:00:03.000Z",
        },
    ]
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _result(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"name": name, "passed": passed, "detail": detail if not passed else ""}


def main() -> None:
    report = evaluate_learning_and_route_benchmark()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
