from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dashscope
from dashscope.audio.qwen_omni import OmniRealtimeCallback, OmniRealtimeConversation

from app.services.runtime_ai_config import get_runtime_ai_config


DEFAULT_OMNI_CIRCUIT_BREAKER_PATH = "/tmp/ai_acq_omni_circuit_breaker.json"
DEFAULT_OMNI_CIRCUIT_BREAKER_SECONDS = 90


@dataclass(frozen=True)
class RealtimeRouteProbe:
    requested_route: str
    effective_route: str
    route_fallback_reason: str = ""


class _OmniProbeCallback(OmniRealtimeCallback):
    def __init__(self) -> None:
        self.error = ""

    def on_error(self, message: object) -> None:
        self.error = str(message)

    def on_event(self, response: dict[str, Any]) -> None:
        if response.get("error"):
            self.error = json.dumps(response.get("error"), ensure_ascii=False)[:500]


def omni_circuit_breaker_path() -> Path:
    return Path(os.getenv("AI_ACQ_OMNI_CIRCUIT_BREAKER_PATH", DEFAULT_OMNI_CIRCUIT_BREAKER_PATH))


def mark_omni_route_unavailable(reason: str, *, ttl_seconds: int = DEFAULT_OMNI_CIRCUIT_BREAKER_SECONDS) -> None:
    path = omni_circuit_breaker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "until": time.time() + max(1, ttl_seconds),
        "reason": reason[:500],
        "createdAt": time.time(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def clear_omni_route_unavailable() -> None:
    try:
        omni_circuit_breaker_path().unlink()
    except FileNotFoundError:
        return


def omni_route_unavailable_reason() -> str:
    path = omni_circuit_breaker_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ""
    until = float(payload.get("until") or 0)
    if until <= time.time():
        clear_omni_route_unavailable()
        return ""
    return str(payload.get("reason") or "Omni 实时语音路线暂时不可用")


def probe_omni_realtime_connect() -> tuple[bool, str]:
    runtime_config = get_runtime_ai_config()
    if not runtime_config.dashscope_api_key.strip():
        return False, "缺少 DashScope API Key，不能走 Omni 实时语音路线。"
    dashscope.api_key = runtime_config.dashscope_api_key
    callback = _OmniProbeCallback()
    conversation = OmniRealtimeConversation(
        model=runtime_config.dashscope_omni_realtime_model,
        callback=callback,
        url=runtime_config.dashscope_omni_realtime_url,
        workspace=runtime_config.dashscope_workspace.strip() or None,
    )
    try:
        conversation.connect()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    finally:
        try:
            conversation.close()
        except Exception:
            pass
    if callback.error:
        return False, callback.error
    return True, ""


def prepare_realtime_route_for_call(requested_route: str) -> RealtimeRouteProbe:
    if requested_route == "livekit":
        return RealtimeRouteProbe(requested_route=requested_route, effective_route="livekit")
    route = "omni" if requested_route == "omni" else "pipeline"
    if route != "omni":
        return RealtimeRouteProbe(requested_route=requested_route, effective_route=route)
    circuit_reason = omni_route_unavailable_reason()
    if circuit_reason:
        return RealtimeRouteProbe(
            requested_route=requested_route,
            effective_route="pipeline",
            route_fallback_reason=f"Omni 实时语音路线仍在熔断保护中：{circuit_reason}",
        )
    ok, reason = probe_omni_realtime_connect()
    if ok:
        clear_omni_route_unavailable()
        return RealtimeRouteProbe(requested_route=requested_route, effective_route="omni")
    mark_omni_route_unavailable(reason)
    return RealtimeRouteProbe(
        requested_route=requested_route,
        effective_route="pipeline",
        route_fallback_reason=f"拨号前检测到 Omni 实时语音连接失败，已临时降级到稳定 pipeline：{reason}",
    )
