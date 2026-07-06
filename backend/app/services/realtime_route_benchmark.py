from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.realtime_call_state import summarize_realtime_call_state
from app.services.realtime_sales_brain import score_realtime_events
from app.services.runtime_ai_config import get_runtime_ai_config


def build_realtime_route_benchmark(
    *,
    current_route: str,
    bridge_ready: bool,
    route_options: list[dict[str, object]],
) -> dict[str, object]:
    runtime_config = get_runtime_ai_config()
    latest_events = _load_recent_live_events()
    latest_score = score_realtime_events(latest_events) if latest_events else None
    latest_state = summarize_realtime_call_state(latest_events) if latest_events else None
    latest_score_value = _optional_int((latest_score or {}).get("score"))
    latest_turn_ms = _optional_int((latest_state or {}).get("latestTurnResponseMs"))
    cost_rank = _cost_rank(route_options)
    benchmarks = [
        _benchmark_route(
            option,
            current_route=current_route,
            bridge_ready=bridge_ready,
            dashscope_ready=bool(runtime_config.dashscope_api_key.strip()),
            deepseek_ready=bool(runtime_config.deepseek_api_key.strip()),
            latest_score=latest_score_value,
            latest_turn_ms=latest_turn_ms,
            cost_rank=cost_rank.get(str(option.get("key") or ""), 9),
        )
        for option in route_options
    ]
    recommended = _recommend_route(benchmarks, current_route, latest_score_value, latest_turn_ms)
    recommended_route = str(recommended.get("key") or "pipeline")
    status = str(recommended.get("status") or "warn")
    return {
        "recommendedRoute": recommended_route,
        "status": status,
        "summary": _recommendation_summary(recommended_route, current_route, latest_score_value, latest_turn_ms, benchmarks),
        "lowCostFirst": recommended_route == "pipeline",
        "latestScore": latest_score_value,
        "latestTurnResponseMs": latest_turn_ms,
        "benchmarks": benchmarks,
    }


def _benchmark_route(
    option: dict[str, object],
    *,
    current_route: str,
    bridge_ready: bool,
    dashscope_ready: bool,
    deepseek_ready: bool,
    latest_score: int | None,
    latest_turn_ms: int | None,
    cost_rank: int,
) -> dict[str, object]:
    key = str(option.get("key") or "")
    readiness = _readiness_score(key, bridge_ready=bridge_ready, dashscope_ready=dashscope_ready, deepseek_ready=deepseek_ready)
    quality = _quality_score(key, current_route=current_route, latest_score=latest_score, latest_turn_ms=latest_turn_ms)
    risks = _route_risks(
        key,
        bridge_ready=bridge_ready,
        dashscope_ready=dashscope_ready,
        deepseek_ready=deepseek_ready,
        latest_turn_ms=latest_turn_ms if current_route == key else None,
        latest_score=latest_score if current_route == key else None,
    )
    strengths = _route_strengths(key, deepseek_ready=deepseek_ready)
    status = _route_status(readiness, quality)
    return {
        "key": key,
        "label": str(option.get("label") or key),
        "status": status,
        "qualityScore": quality,
        "readinessScore": readiness,
        "estimatedLatencyMs": int(option.get("estimatedLatencyMs") or 0),
        "estimatedAiCostPerMinute": float(option.get("estimatedAiCostPerMinute") or 0),
        "costRank": cost_rank,
        "riskLevel": "high" if status == "fail" else "medium" if status == "warn" else "low",
        "strengths": strengths,
        "risks": risks,
        "nextAction": _next_action(key, status, risks, latest_turn_ms if current_route == key else None),
    }


def _readiness_score(key: str, *, bridge_ready: bool, dashscope_ready: bool, deepseek_ready: bool) -> int:
    if key == "omni":
        score = 45
        if dashscope_ready:
            score += 28
        if bridge_ready:
            score += 17
        return min(100, score)
    score = 72
    if dashscope_ready:
        score += 14
    if bridge_ready:
        score += 8
    if deepseek_ready:
        score += 6
    return min(100, score)


def _quality_score(
    key: str,
    *,
    current_route: str,
    latest_score: int | None,
    latest_turn_ms: int | None,
) -> int:
    base = 84 if key == "omni" else 78
    if latest_score is None:
        return base
    if current_route == key:
        score = latest_score
        if latest_turn_ms is not None and latest_turn_ms > 1000:
            score -= min(22, (latest_turn_ms - 1000) // 80)
        return max(25, min(100, int(score)))
    if key == "omni" and latest_turn_ms is not None and latest_turn_ms > 1200:
        return min(94, base + 8)
    if key == "pipeline" and latest_score < 70:
        return max(58, base - 12)
    return base


def _route_risks(
    key: str,
    *,
    bridge_ready: bool,
    dashscope_ready: bool,
    deepseek_ready: bool,
    latest_turn_ms: int | None,
    latest_score: int | None,
) -> list[str]:
    risks: list[str] = []
    if not bridge_ready:
        risks.append("真实媒体桥未就绪，不能证明真实电话低延迟。")
    if not dashscope_ready:
        risks.append("DashScope 运行密钥未就绪，ASR/TTS/Omni 不能做真实服务拨测。")
    if key == "pipeline" and not deepseek_ready:
        risks.append("DeepSeek 未就绪，复杂追问会先走本地规则兜底。")
    if latest_turn_ms is not None and latest_turn_ms > 1000:
        risks.append(f"最近真实通话客户说完到首个AI声音约 {latest_turn_ms}ms，超过1秒目标。")
    if latest_score is not None and latest_score < 75:
        risks.append(f"最近真实通话评分 {latest_score}，还不能直接按可交付验收。")
    return risks[:4]


def _route_strengths(key: str, *, deepseek_ready: bool) -> list[str]:
    if key == "omni":
        return ["端到端实时语音，天然更利于打断和轮次衔接。", "适合单号 A/B 验证真人感和低延迟。"]
    strengths = ["分段链路可观测，适合在实时模型不可用时保持通话不断线。", "ASR、销售脑、TTS 分层可观测，便于定位问题。"]
    if deepseek_ready:
        strengths.append("复杂追问可用 DeepSeek 增强，慢时仍有本地规则兜底。")
    return strengths


def _route_status(readiness: int, quality: int) -> str:
    score = min(readiness, quality)
    if score >= 82:
        return "pass"
    if score >= 62:
        return "warn"
    return "fail"


def _next_action(key: str, status: str, risks: list[str], latest_turn_ms: int | None) -> str:
    if key == "omni" and status != "pass":
        return "先补齐 DashScope/媒体桥，再用同一号码和同一话术做单号 A/B。"
    if key == "pipeline" and latest_turn_ms is not None and latest_turn_ms > 1000:
        return "优先查 ASR 终点、TTS 首包和打断日志；保留备用路线但不能直接放量。"
    if risks:
        return "先处理风险项，再做真实单号回归。"
    return "可作为当前默认路线，继续用真实通话回放压测。"


def _recommend_route(
    benchmarks: list[dict[str, object]],
    current_route: str,
    latest_score: int | None,
    latest_turn_ms: int | None,
) -> dict[str, object]:
    by_key = {str(item.get("key") or ""): item for item in benchmarks}
    pipeline = by_key.get("pipeline")
    omni = by_key.get("omni")
    current_is_slow = latest_turn_ms is not None and latest_turn_ms > 1200
    current_is_weak = latest_score is not None and latest_score < 70
    if current_route == "pipeline" and (current_is_slow or current_is_weak) and omni and omni.get("status") == "pass":
        return omni
    if pipeline and pipeline.get("status") in {"pass", "warn"}:
        return pipeline
    if omni:
        return omni
    return benchmarks[0] if benchmarks else {"key": "pipeline", "status": "warn"}


def _recommendation_summary(
    recommended_route: str,
    current_route: str,
    latest_score: int | None,
    latest_turn_ms: int | None,
    benchmarks: list[dict[str, object]],
) -> str:
    if latest_score is None:
        return "暂无真实通话样本，先保持稳定备用路线，下一步用同一号码做 Pipeline/Omni 单号对照。"
    if recommended_route == "omni" and current_route == "pipeline":
        return "最近 Pipeline 真实通话延迟或质量偏弱，建议用 Omni 做同号 A/B，对比真人感和首音频延迟。"
    if recommended_route == "pipeline":
        detail = f"最近真实通话评分 {latest_score}"
        if latest_turn_ms is not None:
            detail += f"，首音频 {latest_turn_ms}ms"
        return detail + "；仍优先稳定备用路线，但低于阈值时必须先修 ASR/TTS/轮次。"
    active = next((item for item in benchmarks if item.get("key") == recommended_route), None)
    return str((active or {}).get("nextAction") or "按推荐路线继续拨测。")


def _cost_rank(route_options: list[dict[str, object]]) -> dict[str, int]:
    ordered = sorted(route_options, key=lambda item: float(item.get("estimatedAiCostPerMinute") or 0))
    return {str(item.get("key") or ""): index + 1 for index, item in enumerate(ordered)}


def _load_recent_live_events() -> list[dict[str, object]]:
    path = Path(settings.realtime_call_event_log_path).expanduser()
    if not path.exists():
        return []
    events: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-300:]
    except OSError:
        return []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
