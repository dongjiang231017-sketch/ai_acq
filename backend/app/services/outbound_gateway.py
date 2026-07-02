import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.core.config import settings
from app.models.lead import MerchantLead
from app.models.task import OutreachTask
from app.services.asterisk_ami import AsteriskAmiClient, AsteriskAmiError, render_originate_channel
from app.services.telephony_runtime_config import telephony_bool, telephony_str
from app.services.voice_gateway_profiles import voice_gateway_label


class OutboundGatewayConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CallAttempt:
    task: OutreachTask
    lead: MerchantLead
    ai_seat: str
    sequence: int


@dataclass(frozen=True)
class CallResult:
    duration_seconds: int
    intent_level: str
    current_node: str
    outcome: str
    transcript: str
    need_handoff: bool
    recall_at: datetime | None
    lead_status: str
    gateway_call_id: str | None = None
    gateway_status: str = "completed"
    raw_payload: str | None = None


class OutboundGateway(Protocol):
    def place_call(self, attempt: CallAttempt) -> CallResult:
        """Place a call and return the normalized call result."""


class SimulatorGateway:
    def place_call(self, attempt: CallAttempt) -> CallResult:
        score = attempt.lead.intent_score
        if not attempt.lead.phone:
            return CallResult(
                duration_seconds=0,
                intent_level="无效",
                current_node="号码缺失",
                outcome="失败",
                transcript="系统：该商家没有电话，跳过外呼。",
                need_handoff=False,
                recall_at=None,
                lead_status="号码缺失",
                gateway_call_id=None,
                gateway_status="skipped",
                raw_payload='{"provider":"simulator","reason":"missing_phone"}',
            )
        if score >= 80:
            return CallResult(
                duration_seconds=138 + attempt.sequence * 8,
                intent_level="A",
                current_node="加微信",
                outcome="有意向",
                transcript="商家：可以，先发资料看看。AI：我安排顾问给您发入驻资料。",
                need_handoff=True,
                recall_at=None,
                lead_status="高意向",
                gateway_call_id=f"sim-{attempt.task.id}-{attempt.lead.id}",
                raw_payload='{"provider":"simulator","disposition":"interested"}',
            )
        if score >= 65:
            return CallResult(
                duration_seconds=72 + attempt.sequence * 6,
                intent_level="B",
                current_node="价格异议",
                outcome="已接通",
                transcript="商家：费用怎么收？AI：可以先给您发基础方案。",
                need_handoff=False,
                recall_at=datetime.utcnow() + timedelta(hours=4),
                lead_status="需复拨",
                gateway_call_id=f"sim-{attempt.task.id}-{attempt.lead.id}",
                raw_payload='{"provider":"simulator","disposition":"connected"}',
            )
        if score >= 50:
            return CallResult(
                duration_seconds=35 + attempt.sequence * 4,
                intent_level="C",
                current_node="老板忙",
                outcome="稍后联系",
                transcript="商家：现在忙，下午再打。AI：好的，我稍后再联系您。",
                need_handoff=False,
                recall_at=datetime.utcnow() + timedelta(hours=2),
                lead_status="需复拨",
                gateway_call_id=f"sim-{attempt.task.id}-{attempt.lead.id}",
                raw_payload='{"provider":"simulator","disposition":"busy"}',
            )
        return CallResult(
            duration_seconds=0,
            intent_level="D",
            current_node="未接通",
            outcome="未接通",
            transcript="系统：无人接听，进入重拨队列。",
            need_handoff=False,
            recall_at=datetime.utcnow() + timedelta(hours=6),
            lead_status="未接通",
            gateway_call_id=f"sim-{attempt.task.id}-{attempt.lead.id}",
            gateway_status="no_answer",
            raw_payload='{"provider":"simulator","disposition":"no_answer"}',
        )


class AsteriskGateway:
    def place_call(self, attempt: CallAttempt) -> CallResult:
        gateway = voice_gateway_label()
        if not telephony_bool("ASTERISK_LIVE_CALL_ENABLED", fallback=settings.asterisk_live_call_enabled):
            raise OutboundGatewayConfigurationError("真实线路拨号开关未启用，请先完成语音网关单号试拨。")
        if not telephony_bool("ASTERISK_BULK_CALL_ENABLED", fallback=settings.asterisk_bulk_call_enabled):
            raise OutboundGatewayConfigurationError("批量真实外呼未启用，请确认单号试拨稳定后再开启。")
        if not attempt.lead.phone:
            return CallResult(
                duration_seconds=0,
                intent_level="无效",
                current_node="号码缺失",
                outcome="失败",
                transcript=f"系统：该商家没有电话，未提交到{gateway}线路。",
                need_handoff=False,
                recall_at=None,
                lead_status="号码缺失",
                gateway_call_id=None,
                gateway_status="skipped",
                raw_payload='{"provider":"asterisk","reason":"missing_phone"}',
            )

        try:
            render_originate_channel(attempt.lead.phone)
            with AsteriskAmiClient() as client:
                result = client.originate(
                    attempt.lead.phone,
                    variables={
                        "AI_ACQ_TASK_ID": attempt.task.id,
                        "AI_ACQ_LEAD_ID": attempt.lead.id,
                        "AI_ACQ_SEAT": attempt.ai_seat,
                    },
                )
        except AsteriskAmiError as exc:
            return CallResult(
                duration_seconds=0,
                intent_level="D",
                current_node="线路提交失败",
                outcome="失败",
                transcript=f"系统：语音网关/Asterisk 外呼提交失败：{exc}",
                need_handoff=False,
                recall_at=None,
                lead_status="外呼失败",
                gateway_call_id=None,
                gateway_status="failed",
                raw_payload=json.dumps({"provider": "asterisk", "error": str(exc)}, ensure_ascii=False),
            )

        return CallResult(
            duration_seconds=0,
            intent_level="待判定",
            current_node="已提交线路网关",
            outcome="拨号已提交" if result.accepted else "失败",
            transcript=f"系统：已通过语音网关/Asterisk 提交外呼请求。{result.message}",
            need_handoff=False,
            recall_at=None,
            lead_status="外呼中" if result.accepted else "外呼失败",
            gateway_call_id=result.action_id,
            gateway_status=result.status,
            raw_payload=result.raw_payload,
        )


def get_outbound_gateway() -> OutboundGateway:
    if telephony_str("TELEPHONY_GATEWAY_MODE", fallback=settings.telephony_gateway_mode) == "asterisk":
        return AsteriskGateway()
    return SimulatorGateway()
