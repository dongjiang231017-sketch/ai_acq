from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from app.services.asterisk_ami import AsteriskAmiClient, AsteriskAmiError, AsteriskOriginateResult, check_asterisk_health
from app.services.voice_gateway_profiles import current_voice_gateway_profile, voice_gateway_label

logger = logging.getLogger(__name__)


def build_cellular_diagnostic(
    result: AsteriskOriginateResult | None = None,
    *,
    media_loop_confirmed: bool = False,
    human_speech_confirmed: bool = False,
    ai_speech_confirmed: bool = False,
    call_screening_detected: bool = False,
    bridge_error: str = "",
) -> dict[str, object]:
    profile = current_voice_gateway_profile()
    events = _events_from_raw_payload(result.raw_payload if result else "")
    compact_chain = _compact_event_chain(events)
    diagnostic_text = _diagnostic_text(events, result.message if result else "")
    gateway_status = result.status if result else "unknown"
    cellular_confirmed = bool(result and result.cellular_confirmed)

    if human_speech_confirmed and ai_speech_confirmed:
        return _diagnostic(
            status="pass",
            stage="realtime_conversation_confirmed",
            title="真人实时通话已确认",
            summary="已确认手机侧真人语音和 AI 音频回放，可以作为本轮实时通话验收证据。",
            detail="AudioSocket、ASR、TTS 和真人响应都已进入同一通电话。",
            action_items=["保存本轮通话录音和评分结果。", "继续用单号小批量复测稳定性，批量外呼仍需单独打开开关。"],
            technical_detail=compact_chain,
            can_retry=True,
            customer_action_required=False,
        )

    if bridge_error:
        return _diagnostic(
            status="fail",
            stage="realtime_bridge_error",
            title="实时语音桥连接失败",
            summary="电话已经接入 AudioSocket，但实时语音模型/媒体桥在本通电话内报错，导致接通后很快断开或没有 AI 回复。",
            detail=bridge_error[:300],
            action_items=[
                "先不要连续重拨同一个号码，等待系统自动降级或恢复实时模型连接。",
                "如果再次试拨，接通后保持 10 秒以上，观察实时监听是否出现 AI 首句。",
                "若连续出现该错误，需要检查实时模型 WebSocket 网络、供应商状态或切换到 pipeline 路线。",
            ],
            technical_detail=compact_chain,
            can_retry=True,
            customer_action_required=False,
        )

    if media_loop_confirmed:
        return _diagnostic(
            status="warn",
            stage="realtime_media_confirmed",
            title="媒体桥已接通，真人对话未完成",
            summary="线路已经接入 AudioSocket，但还没有同时确认真人语音和 AI 首句。",
            detail="这通常是电话助理、语音信箱、客户未说话或测试未继续导致。",
            action_items=["接通后请对着手机说一句“你好”。", "观察实时监听是否出现真人语音确认和 AI 首句播出。"],
            technical_detail=compact_chain,
            can_retry=True,
            customer_action_required=True,
        )

    if cellular_confirmed:
        return _diagnostic(
            status="warn",
            stage="gateway_answered_waiting_for_human",
            title="网关已呼出，等待真人接听验收",
            summary=f"{voice_gateway_label()} 已接管本次 SIP 外呼；手机侧可能已响铃，但还没有真人语音和实时 AI 媒体证据。",
            detail="部分语音网关会先应答 Asterisk 再拨蜂窝线路，所以这里不能等同于客户已经接听。需要接听后保持通话 10 秒以上，并确认实时监听出现真人语音和 AI 首句。",
            action_items=[
                "重新做单号试拨，并在手机响铃后接听。",
                "接听后对着手机说一句“你好”，保持通话 10 秒以上。",
                "观察实时监听是否出现真人语音、AI 首句和媒体桥事件。",
            ],
            technical_detail=compact_chain,
            can_retry=True,
            customer_action_required=True,
        )

    if _has_any(diagnostic_text, ["no_route_destination", "404", "not found"]) or (result and result.verification_stage == "not_connected" and "找不到可用外呼路由" in result.message):
        return _diagnostic(
            status="fail",
            stage="gateway_route_failed",
            title="语音网关没有可用外呼路由",
            summary="Asterisk 已把号码交给语音网关，但网关没有把 SIP 呼叫路由到 SIM/VoLTE 线路。",
            detail="这不是 AI 模型问题。需要在网关后台检查 SIP 分机到蜂窝线路的呼叫控制/路由规则。",
            action_items=[
                "打开语音网关后台，检查 SIP 分机/中继到 VoLTE/SIM 的外呼路由。",
                "确认号码匹配规则允许当前手机号段。",
                "确认线路选择指向在线 SIM，而不是空线路或错误分组。",
            ],
            technical_detail=compact_chain,
            can_retry=False,
            customer_action_required=True,
        )

    if _has_any(diagnostic_text, ["503", "congestion", "normal circuit/channel congestion", "cause=34", "cause 34"]):
        return _diagnostic(
            status="fail",
            stage="cellular_temporarily_unavailable",
            title="蜂窝线路临时不可用",
            summary="SIP 注册正常，但网关/运营商没有给本次外呼分配可用蜂窝通道。",
            detail="常见原因是 SIM/VoLTE 模块卡住、运营商临时拒绝、信号波动、单卡通道被占用或风控。",
            action_items=[
                "在语音网关后台查看当前呼叫/话单里的失败原因。",
                "确认 SIM 余额、VoLTE、信号和运营商外呼权限正常。",
                "断开并重新连接 VoLTE 数据，必要时重启语音网关后再试。",
            ],
            technical_detail=compact_chain,
            can_retry=True,
            customer_action_required=True,
        )

    if gateway_status == "ringing":
        return _diagnostic(
            status="warn",
            stage="gateway_signaling_only",
            title="只到网关振铃证据",
            summary="Asterisk/语音网关 SIP 侧有响应，但还没有证明手机真实响铃或接听。",
            detail="昨天能通说明 AI 媒体链路曾经正常；现在需要确认网关是否真的把本次呼叫打到 SIM/运营商。若网关话单显示“通道不可用”，优先恢复 VoLTE/SIM 通道。",
            action_items=[
                "前端再次试拨时，同时打开语音网关后台的当前呼叫或话单页面。",
                "如果网关话单没有蜂窝呼出记录，检查 SIP 到 VoLTE 路由。",
                "如果话单显示通道不可用，重连 VoLTE、重启语音网关或换 SIM/通道验证。",
                "如果话单有呼出但手机不响，检查 SIM/运营商/号码拦截。",
            ],
            technical_detail=compact_chain,
            can_retry=True,
            customer_action_required=True,
        )

    if gateway_status in {"busy", "no_answer", "cancelled"}:
        return _diagnostic(
            status="warn",
            stage=f"cellular_{gateway_status}",
            title="蜂窝侧未形成有效接听",
            summary="线路没有进入可验收的真人实时通话。",
            detail="如果手机没有响铃，请优先看语音网关话单；如果手机响了但未接，请接听后保持通话。",
            action_items=["确认手机侧是否实际响铃。", "接听后说一句“你好”，等待实时监听出现真人确认。"],
            technical_detail=compact_chain,
            can_retry=True,
            customer_action_required=True,
        )

    if result and not result.accepted:
        return _diagnostic(
            status="fail",
            stage="originate_failed",
            title="Asterisk 外呼提交失败",
            summary=result.message or "Asterisk 没有接受本次外呼请求。",
            detail="先恢复 Asterisk/网关注册，再重新做单号试拨。",
            action_items=["点击自动恢复线路。", "确认 trunk 注册后再试拨。"],
            technical_detail=compact_chain,
            can_retry=True,
            customer_action_required=False,
        )

    return _diagnostic(
        status="warn",
        stage="cellular_not_verified",
        title="蜂窝线路待验收",
        summary="当前只完成基础注册检查，还没有真实蜂窝接通和媒体桥证据。",
        detail=f"{profile.label} 已作为语音网关档案，但必须通过单号试拨确认 SIM/运营商侧真实可用。",
        action_items=["先做单号试拨。", "接听后说话，确认实时监听出现真人语音和 AI 首句。"],
        technical_detail=compact_chain,
        can_retry=True,
        customer_action_required=True,
    )


def recover_telephony_line() -> dict[str, object]:
    profile = current_voice_gateway_profile()
    # 【审计B1】移除 module reload res_pjsip.so / res_pjsip_outbound_registration.so 与 pjsip send register：
    # reload 会波及在线通话；且本架构是语音网关注册进服务器 Asterisk（方向相反），
    # 服务器端"向外注册"类命令无法恢复注册。这里只保留无害的诊断/刷新动作。
    commands = [
        "dialplan reload",
        "pjsip show registrations",
        "pjsip show contacts",
        f"pjsip show endpoint {profile.trunk_name}" if profile.trunk_name else "pjsip show endpoints",
    ]
    logger.warning(
        "telephony_line_recovery_gateway_side_needed trunk=%s 服务器端只执行无害动作；若注册丢失需在语音网关侧重新发起 SIP 注册。",
        profile.trunk_name,
    )
    command_results: list[dict[str, object]] = []
    status = "pass"
    summary = "已执行服务器端无害恢复动作（不含 module reload）并重新检测线路状态；若注册丢失需在语音网关侧重新发起 SIP 注册。"
    try:
        with AsteriskAmiClient() as client:
            for command in commands:
                response = client.command(command)
                output = response.field_text("Output") or response.message
                command_results.append(
                    {
                        "command": command,
                        "ok": response.ok,
                        "message": response.message,
                        "output": output[-1200:],
                    }
                )
                if not response.ok:
                    status = "warn"
    except AsteriskAmiError as exc:
        status = "fail"
        summary = str(exc)
        command_results.append({"command": "AMI", "ok": False, "message": str(exc), "output": ""})
    health = check_asterisk_health().as_dict()
    if health.get("trunkReachable") is not True:
        status = "fail" if status == "pass" else status
    return {
        "checkedAt": datetime.utcnow(),
        "status": status,
        "summary": summary,
        "commands": command_results,
        "health": health,
        "nextStep": _line_recovery_next_step(status, bool(health.get("trunkReachable"))),
    }


def _line_recovery_next_step(status: str, trunk_ok: bool) -> str:
    if not trunk_ok:
        # 【审计B1】掉注册需在网关侧重新发起注册，服务器端无法代替
        return "Asterisk 到语音网关仍未恢复，需在语音网关侧重新发起 SIP 注册；请检查网关电源、网络、SIP账号和当前LAN地址。"
    if status == "fail":
        return "Asterisk 可达但恢复动作失败，请查看命令输出或重启客户端内置 Asterisk。"
    return "Asterisk/网关注册已刷新；请马上做一次单号试拨，并同时查看语音网关当前呼叫/话单。"


def _diagnostic(
    *,
    status: str,
    stage: str,
    title: str,
    summary: str,
    detail: str,
    action_items: list[str],
    technical_detail: str = "",
    can_retry: bool,
    customer_action_required: bool,
) -> dict[str, object]:
    return {
        "status": status,
        "stage": stage,
        "title": title,
        "summary": summary,
        "detail": detail,
        "actionItems": action_items,
        "technicalDetail": technical_detail,
        "canRetry": can_retry,
        "customerActionRequired": customer_action_required,
    }


def _events_from_raw_payload(raw_payload: str) -> list[dict[str, Any]]:
    if not raw_payload:
        return []
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return []
    events = payload.get("events")
    return events if isinstance(events, list) else []


def _compact_event_chain(events: list[dict[str, Any]]) -> str:
    compact: list[str] = []
    for event in events[-8:]:
        if not isinstance(event, dict):
            continue
        compact.append(
            "/".join(
                str(event.get(key) or "")
                for key in ["Event", "ChannelStateDesc", "DialStatus", "Cause", "Cause-txt", "TechCause", "Reason"]
                if event.get(key)
            )
        )
    return " -> ".join(part for part in compact if part)


def _diagnostic_text(events: list[dict[str, Any]], message: str) -> str:
    parts = [message]
    for event in events:
        if isinstance(event, dict):
            parts.extend(str(event.get(key) or "") for key in ["Event", "DialStatus", "Cause", "Cause-txt", "TechCause", "Reason"])
    return " ".join(parts).lower()


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)
