from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.models.lead import MerchantLead
from app.models.task import DirectMessageAccount, DirectMessageTemplate, OutreachTask


@dataclass(frozen=True)
class DmAttempt:
    task: OutreachTask
    lead: MerchantLead
    account: DirectMessageAccount
    template: DirectMessageTemplate
    sequence: int


@dataclass(frozen=True)
class DmResult:
    outgoing_content: str
    status: str
    intent_level: str
    reply_content: str | None
    need_handoff: bool
    lead_status: str
    external_message_id: str | None
    raw_payload: str | None


class DirectMessageGateway(Protocol):
    def send_message(self, attempt: DmAttempt) -> DmResult:
        """Send a platform direct message and return the normalized result."""


def render_template(content: str, lead: MerchantLead) -> str:
    return (
        content.replace("{商家名称}", lead.name)
        .replace("{城市}", lead.city)
        .replace("{品类}", lead.category)
        .replace("{平台}", lead.platform)
    )


class SimulatorDmGateway:
    def send_message(self, attempt: DmAttempt) -> DmResult:
        outgoing = render_template(attempt.template.content, attempt.lead)
        external_id = f"sim-dm-{attempt.task.id}-{attempt.lead.id}-{attempt.sequence}"
        score = attempt.lead.intent_score

        if score >= 80:
            return DmResult(
                outgoing_content=outgoing,
                status="已回复",
                intent_level="A",
                reply_content="可以，发我入驻资料看看。",
                need_handoff=True,
                lead_status="高意向",
                external_message_id=external_id,
                raw_payload='{"provider":"simulator","disposition":"interested_reply"}',
            )
        if score >= 65:
            return DmResult(
                outgoing_content=outgoing,
                status="已回复",
                intent_level="B",
                reply_content="费用怎么收？需要准备哪些资料？",
                need_handoff=True,
                lead_status="需跟进",
                external_message_id=external_id,
                raw_payload='{"provider":"simulator","disposition":"question_reply"}',
            )
        if score >= 50:
            return DmResult(
                outgoing_content=outgoing,
                status="已发送",
                intent_level="C",
                reply_content=None,
                need_handoff=False,
                lead_status="已私信",
                external_message_id=external_id,
                raw_payload='{"provider":"simulator","disposition":"sent"}',
            )
        return DmResult(
            outgoing_content=outgoing,
            status="已发送",
            intent_level="D",
            reply_content=None,
            need_handoff=False,
            lead_status="低意向",
            external_message_id=external_id,
            raw_payload='{"provider":"simulator","disposition":"low_intent_sent"}',
        )


class BrowserAutomationDmGateway:
    def send_message(self, attempt: DmAttempt) -> DmResult:
        raise RuntimeError(
            "Platform DM live automation is not enabled yet; keep DM_GATEWAY_MODE=simulator "
            "until platform accounts, login sessions, and compliance throttles are configured."
        )


def get_dm_gateway() -> DirectMessageGateway:
    if settings.dm_gateway_mode == "browser":
        return BrowserAutomationDmGateway()
    return SimulatorDmGateway()
