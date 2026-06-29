from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.core.config import settings
from app.models.lead import MerchantLead
from app.models.task import OutreachTask


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
        if not settings.asterisk_ami_username or not settings.asterisk_ami_password:
            raise RuntimeError("Asterisk AMI credentials are not configured")
        raise RuntimeError(
            "Asterisk gateway is configured but the live originate adapter is not enabled yet; "
            "keep TELEPHONY_GATEWAY_MODE=simulator until UC100 and Asterisk are reachable."
        )


def get_outbound_gateway() -> OutboundGateway:
    if settings.telephony_gateway_mode == "asterisk":
        return AsteriskGateway()
    return SimulatorGateway()
