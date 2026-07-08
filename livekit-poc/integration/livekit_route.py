"""LiveKit 线路适配层——放进现有后台 backend/app/services/ 即可用。

职责：
1. dial_livekit_call()      发起外呼（转调 PoC 的 dial_api）
2. fetch_livekit_events()   拉某通电话的事件/转写
3. livekit_route_available() 健康检查（给线路选项显示可用状态）
4. sync_livekit_intents()   把转写里的强意向写进现有意向池
   （复用 realtime_intent_capture.record_realtime_intent_signal，
    与 pipeline/omni 线路同一套判定与去重，意向池数据结构完全不变）

零新依赖：只用标准库 urllib，与后台现有风格一致（参考 realtime_llm.py）。
"""

from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 建议挪到 app.core.config 的 Settings 里（见 INTEGRATION.md 第4步）
LIVEKIT_DIAL_API_URL = "http://127.0.0.1:8100"
LIVEKIT_DIAL_TIMEOUT_SECONDS = 8.0


class LivekitRouteError(RuntimeError):
    """LiveKit 线路调用失败（网络/dial_api 未启动/参数错误）。"""


def dial_livekit_call(phone: str, merchant_name: str = "", base_url: str | None = None) -> dict[str, Any]:
    """发起一通 LiveKit 线路外呼。

    返回 {"call_id": "lk-xxx", "room": "call-lk-xxx"}。
    拨号是异步的：本函数返回只代表任务已受理，接通与否用 fetch_livekit_events 轮询。
    """
    payload = json.dumps(
        {"phone_number": phone.strip(), "merchant_name": merchant_name.strip()},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        _api(base_url, "/calls"),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=LIVEKIT_DIAL_TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode("utf-8", errors="ignore")
        raise LivekitRouteError(f"LiveKit dial api HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LivekitRouteError(f"LiveKit dial api 不可达：{exc}") from exc


def fetch_livekit_events(call_id: str, base_url: str | None = None) -> list[dict[str, Any]]:
    """拉取一通电话的全部事件。404 表示还没产生事件（拨号中），返回空列表。"""
    request = urllib.request.Request(_api(base_url, f"/calls/{call_id}"), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=LIVEKIT_DIAL_TIMEOUT_SECONDS) as response:  # noqa: S310
            data = json.loads(response.read().decode("utf-8"))
            return list(data.get("events") or [])
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise LivekitRouteError(f"LiveKit events HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LivekitRouteError(f"LiveKit dial api 不可达：{exc}") from exc


def summarize_livekit_call(events: list[dict[str, Any]]) -> dict[str, Any]:
    """把事件流折叠成现有 test-call 接口习惯的状态字段。"""
    connected = any(e.get("event") == "call_connected" for e in events)
    dial_failed = next((e for e in events if e.get("event") == "dial_failed"), None)
    human_speech = any(e.get("event") == "transcript" and e.get("role") == "user" for e in events)
    ai_speech = any(e.get("event") in ("opening_spoken",) for e in events) or any(
        e.get("event") == "transcript" and e.get("role") == "assistant" for e in events
    )
    ended = any(e.get("event") in ("call_ended", "callee_hangup", "call_timeout") for e in events)
    turn_latencies = [float(e.get("latency_ms") or 0) for e in events if e.get("event") == "turn_latency"]
    return {
        "cellularConfirmed": connected,
        "humanSpeechConfirmed": human_speech,
        "aiSpeechConfirmed": ai_speech,
        "conversationConfirmed": connected and human_speech and ai_speech,
        "callEnded": ended,
        "dialFailed": bool(dial_failed),
        "dialFailReason": str((dial_failed or {}).get("error") or ""),
        "turnLatenciesMs": turn_latencies,
    }


def livekit_route_available(base_url: str | None = None) -> bool:
    """线路健康检查：dial_api 端口是否可达。给 routeOptions 用，必须快（<1s）。"""
    parsed = urlparse(base_url or LIVEKIT_DIAL_API_URL)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8100
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def sync_livekit_intents(
    call_id: str,
    phone: str,
    merchant_name: str = "",
    base_url: str | None = None,
) -> int:
    """扫描转写，把客户的强意向话术写进现有意向池。

    幂等：record_realtime_intent_signal 内部按 source_record_id 去重，
    同一通电话重复调用不会写重。返回本次命中的条数。
    建议调用时机：通话结束后调一次；或后台任务每 10s 对进行中的通话调用。
    """
    from app.services.realtime_intent_capture import record_realtime_intent_signal

    events = fetch_livekit_events(call_id, base_url)
    context = {"phone": phone, "merchantName": merchant_name or "LiveKit线路外呼"}
    hits = 0
    for ev in events:
        if ev.get("event") != "transcript" or ev.get("role") != "user":
            continue
        text = str(ev.get("text") or "").strip()
        if not text:
            continue
        result = record_realtime_intent_signal(
            call_id=call_id,
            context=context,
            text=text,
            intent="加微信/发资料",  # 强意向判定在 _is_strong_realtime_intent 里做，此处只是提示值
            signal=text,
            source="livekit_route",
        )
        if result is not None:
            hits += 1
    if hits:
        logger.info("livekit intent sync call_id=%s hits=%d", call_id, hits)
    return hits


def _api(base_url: str | None, path: str) -> str:
    return (base_url or LIVEKIT_DIAL_API_URL).rstrip("/") + path
