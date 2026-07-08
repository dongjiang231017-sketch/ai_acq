from __future__ import annotations

import argparse
import json
from argparse import Namespace
from typing import Any

from app.core.config import settings
from app.services.realtime_outbound import build_realtime_pipeline
from app.services.runtime_ai_config import get_runtime_ai_config
from app.services.telephony_runtime_config import telephony_bool, telephony_str
from app.tools.realtime_audio_bridge import build_config, config_summary


DEFAULT_SMOKE_QUESTION = "你是谁？这个视频号团购怎么收费？"


def build_readiness(args: argparse.Namespace) -> dict[str, Any]:
    runtime_config = get_runtime_ai_config()
    bridge_config = build_config(_bridge_args(args))
    bridge_summary = config_summary(bridge_config)
    pipeline = build_realtime_pipeline()
    telephony = {
        "gatewayMode": telephony_str("TELEPHONY_GATEWAY_MODE", fallback=settings.telephony_gateway_mode),
        "liveCallEnabled": telephony_bool("ASTERISK_LIVE_CALL_ENABLED", fallback=settings.asterisk_live_call_enabled),
        "bulkCallEnabled": telephony_bool("ASTERISK_BULK_CALL_ENABLED", fallback=settings.asterisk_bulk_call_enabled),
        "audioSocketHost": settings.asterisk_audio_socket_host,
        "audioSocketPort": settings.asterisk_audio_socket_port,
    }
    checks = {
        "dashscopeKeyConfigured": bool(runtime_config.dashscope_api_key.strip()),
        "bridgeModeIsOmni": bridge_summary["conversationMode"] == "omni",
        "runtimeRouteIsOmni": str(pipeline.get("configuredRoute") or "") == "omni",
        "bridgeRouteMatchesRuntime": bool(pipeline.get("routeMatched")),
        "bulkCallStillDisabled": not bool(telephony["bulkCallEnabled"]),
        "singleCallSwitchEnabled": bool(telephony["liveCallEnabled"]),
        "audioSocketListening": pipeline.get("bridgeMode") == "asterisk_audiosocket",
        "readyForAsteriskMedia": bool(pipeline.get("readyForAsteriskMedia")),
    }
    result: dict[str, Any] = {
        "okForOfflineOmniSmoke": checks["dashscopeKeyConfigured"] and checks["bridgeModeIsOmni"],
        "okForSinglePhoneTrial": checks["readyForAsteriskMedia"] and checks["singleCallSwitchEnabled"],
        "checks": checks,
        "telephony": telephony,
        "bridge": bridge_summary,
        "pipeline": {
            "mode": pipeline.get("mode"),
            "bridgeMode": pipeline.get("bridgeMode"),
            "configuredRoute": pipeline.get("configuredRoute"),
            "actualBridgeRoute": pipeline.get("actualBridgeRoute"),
            "routeMatched": pipeline.get("routeMatched"),
            "estimatedLatencyMs": pipeline.get("estimatedLatencyMs"),
            "readyForAsteriskMedia": pipeline.get("readyForAsteriskMedia"),
            "nextStep": pipeline.get("nextStep"),
        },
        "nextCommands": _next_commands(checks),
    }
    if args.model_smoke:
        from app.tools.qwen_omni_realtime_smoke import run_smoke

        smoke_args = Namespace(
            model="",
            url="",
            voice="",
            question=args.question,
            audio_pcm="",
            say_voice=args.say_voice,
            chunk_bytes=args.chunk_bytes,
            chunk_sleep=args.chunk_sleep,
            timeout=args.timeout,
            output_wav=args.output_wav,
        )
        result["modelSmoke"] = run_smoke(smoke_args)
    return result


def _bridge_args(args: argparse.Namespace) -> argparse.Namespace:
    return Namespace(
        host=args.host,
        port=args.port,
        voice_id=args.voice_id,
        voice_name=args.voice_name,
        asr_model="",
        tts_model="",
        conversation_mode=args.conversation_mode,
        omni_model="",
        omni_url="",
        omni_voice=args.omni_voice,
        omni_input_transcription_model="",
        opening_text="",
        log_path=args.log_path,
    )


def _next_commands(checks: dict[str, bool]) -> list[str]:
    commands = [
        "cd backend && source .venv/bin/activate",
        "python -m app.tools.realtime_omni_readiness --model-smoke",
    ]
    if not checks["audioSocketListening"]:
        commands.append("python -m app.tools.realtime_audio_bridge --conversation-mode omni")
    if checks["audioSocketListening"] and checks["singleCallSwitchEnabled"]:
        commands.append('curl "http://localhost:8001/api/outbound/telephony/preflight?phone=<测试手机号>"')
        commands.append(
            "curl -X POST http://localhost:8001/api/outbound/telephony/test-call "
            "-H 'Content-Type: application/json' "
            "-d '{\"phone\":\"<测试手机号>\",\"conversationRoute\":\"omni\"}'"
        )
    return commands


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Omni realtime outbound readiness without placing a phone call.")
    parser.add_argument("--host", default="", help="Optional AudioSocket bind host override for the bridge summary.")
    parser.add_argument("--port", type=int, default=0, help="Optional AudioSocket port override for the bridge summary.")
    parser.add_argument("--voice-id", default="", help="Optional realtime TTS voice id override.")
    parser.add_argument("--voice-name", default="", help="Optional realtime TTS voice label override.")
    parser.add_argument("--omni-voice", default="", help="Optional Omni realtime voice override.")
    parser.add_argument("--conversation-mode", choices=["pipeline", "omni"], default="omni")
    parser.add_argument("--log-path", default="", help="Optional bridge event log path override.")
    parser.add_argument("--model-smoke", action="store_true", help="Run a DashScope Omni smoke test. This uses the model but never places a phone call.")
    parser.add_argument("--question", default=DEFAULT_SMOKE_QUESTION)
    parser.add_argument("--say-voice", default="Tingting")
    parser.add_argument("--chunk-bytes", type=int, default=3200)
    parser.add_argument("--chunk-sleep", type=float, default=0.08)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output-wav", default="/tmp/ai-acq-qwen-omni-smoke-response.wav")
    return parser.parse_args()


def main() -> None:
    print(json.dumps(build_readiness(parse_args()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
