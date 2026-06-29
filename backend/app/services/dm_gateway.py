from dataclasses import dataclass
from hashlib import sha1
from json import dumps
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus

from app.core.config import settings
from app.models.lead import MerchantLead
from app.models.task import (
    DirectMessageAccount,
    DirectMessagePlatformConfig,
    DirectMessageTemplate,
    OutreachTask,
)
from app.services.dm_browser_profile import profile_path_for_account


@dataclass(frozen=True)
class DmAttempt:
    task: OutreachTask
    lead: MerchantLead
    account: DirectMessageAccount
    template: DirectMessageTemplate
    sequence: int
    platform_config: DirectMessagePlatformConfig | None = None


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


@dataclass(frozen=True)
class BrowserPreflightResult:
    account_status: str
    session_status: str
    risk_status: str
    last_error: str | None


@dataclass(frozen=True)
class BrowserReply:
    merchant_name: str
    content: str
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


def render_url_template(url: str, lead: MerchantLead) -> str:
    tokens = {
        "{商家名称}": quote_plus(lead.name),
        "{城市}": quote_plus(lead.city),
        "{品类}": quote_plus(lead.category),
        "{平台}": quote_plus(lead.platform),
    }
    rendered = url
    for token, value in tokens.items():
        rendered = rendered.replace(token, value)
    return rendered


def selector_text(value: str | None) -> str:
    return value or ""


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
    def _playwright(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright 未安装，请先运行 pip install -r requirements.txt") from exc
        return sync_playwright()

    def _launch_context(self, browser_type, account: DirectMessageAccount):
        profile_path = Path(profile_path_for_account(account))
        profile_path.mkdir(parents=True, exist_ok=True)
        options: dict[str, object] = {
            "headless": settings.dm_browser_headless,
            "timeout": settings.dm_browser_timeout_ms,
            "slow_mo": settings.dm_browser_slow_mo_ms,
        }
        if settings.dm_browser_channel:
            options["channel"] = settings.dm_browser_channel
        return browser_type.launch_persistent_context(str(profile_path), **options)

    def _visible(self, page, selector: str | None) -> bool:
        active_selector = selector_text(selector)
        if not active_selector.strip():
            return False
        try:
            page.locator(active_selector).first.wait_for(state="visible", timeout=1000)
            return True
        except Exception:
            return False

    def _click(self, page, selector: str | None, label: str) -> None:
        active_selector = selector_text(selector)
        if not active_selector.strip():
            raise RuntimeError(f"缺少{label}选择器")
        locator = page.locator(active_selector).first
        locator.wait_for(state="visible", timeout=settings.dm_browser_timeout_ms)
        locator.click(timeout=settings.dm_browser_timeout_ms)

    def _fill(self, page, selector: str | None, value: str, label: str) -> None:
        active_selector = selector_text(selector)
        if not active_selector.strip():
            raise RuntimeError(f"缺少{label}选择器")
        locator = page.locator(active_selector).first
        locator.wait_for(state="visible", timeout=settings.dm_browser_timeout_ms)
        locator.fill(value, timeout=settings.dm_browser_timeout_ms)

    def _goto(self, page, url: str | None, label: str) -> None:
        active_url = selector_text(url)
        if not active_url.strip():
            raise RuntimeError(f"缺少{label}地址")
        page.goto(active_url, wait_until="domcontentloaded", timeout=settings.dm_browser_timeout_ms)

    def _check_risk(self, page, config: DirectMessagePlatformConfig) -> None:
        if self._visible(page, config.risk_check_selector):
            raise RuntimeError("平台出现验证码、风控或人机校验，请人工处理后再继续")

    def _require_config(self, config: DirectMessagePlatformConfig | None) -> DirectMessagePlatformConfig:
        if not config:
            raise RuntimeError("缺少平台选择器配置")
        if not config.enabled:
            raise RuntimeError(f"{config.platform} 平台选择器未启用")
        return config

    def preflight_account(
        self,
        account: DirectMessageAccount,
        config: DirectMessagePlatformConfig | None,
    ) -> BrowserPreflightResult:
        try:
            active_config = self._require_config(config)
        except RuntimeError as exc:
            return BrowserPreflightResult("待配置", "未登录", "正常", str(exc))

        if not selector_text(active_config.login_check_selector).strip():
            return BrowserPreflightResult("待配置", "需配置", "正常", "缺少登录态选择器，无法确认账号是否已登录")

        target_url = active_config.inbox_url or active_config.home_url
        if not target_url:
            return BrowserPreflightResult("待配置", "需配置", "正常", "缺少首页或收件箱地址")

        with self._playwright() as playwright:
            context = self._launch_context(playwright.chromium, account)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                self._goto(page, target_url, "登录检测")
                if self._visible(page, active_config.risk_check_selector):
                    return BrowserPreflightResult("暂停", "需验证", "需验证", "检测到验证码、风控或人机校验")
                if self._visible(page, active_config.login_check_selector):
                    return BrowserPreflightResult("可用", "已登录", "正常", None)
                return BrowserPreflightResult("待登录", "未登录", "正常", "未检测到登录态，请在客户端完成扫码登录")
            finally:
                context.close()

    def send_message(self, attempt: DmAttempt) -> DmResult:
        if not settings.dm_browser_live_send_enabled:
            raise RuntimeError("真实平台发送安全闸门未开启，请确认后设置 DM_BROWSER_LIVE_SEND_ENABLED=true")

        config = self._require_config(attempt.platform_config)
        outgoing = render_template(attempt.template.content, attempt.lead)
        target_url = attempt.lead.platform_url or render_url_template(config.merchant_search_url, attempt.lead) or config.home_url

        with self._playwright() as playwright:
            context = self._launch_context(playwright.chromium, attempt.account)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                self._goto(page, target_url, "商家页或搜索页")
                self._check_risk(page, config)
                if selector_text(config.merchant_link_selector).strip():
                    self._click(page, config.merchant_link_selector, "商家结果")
                    self._check_risk(page, config)
                self._click(page, config.message_button_selector, "私信按钮")
                self._check_risk(page, config)
                self._fill(page, config.input_selector, outgoing, "私信输入框")
                self._click(page, config.send_button_selector, "发送按钮")
                if selector_text(config.sent_success_selector).strip():
                    page.locator(selector_text(config.sent_success_selector)).first.wait_for(
                        state="visible",
                        timeout=settings.dm_browser_timeout_ms,
                    )
            finally:
                context.close()

        external_id = f"browser-dm-{attempt.task.id}-{attempt.lead.id}-{attempt.sequence}"
        raw_payload = dumps(
            {
                "provider": "browser",
                "platform": attempt.account.platform,
                "profile": attempt.account.browser_profile_key,
                "targetUrl": target_url,
                "sent": True,
            },
            ensure_ascii=False,
        )
        return DmResult(
            outgoing_content=outgoing,
            status="已发送",
            intent_level="C",
            reply_content=None,
            need_handoff=False,
            lead_status="已私信",
            external_message_id=external_id,
            raw_payload=raw_payload,
        )

    def collect_replies(
        self,
        account: DirectMessageAccount,
        config: DirectMessagePlatformConfig | None,
        limit: int = 20,
    ) -> list[BrowserReply]:
        active_config = self._require_config(config)
        item_selector = selector_text(active_config.unread_selector) or selector_text(active_config.conversation_item_selector)
        if not item_selector.strip():
            raise RuntimeError("缺少未读消息或会话条目选择器")
        if not selector_text(active_config.message_text_selector).strip():
            raise RuntimeError("缺少消息文本选择器")

        with self._playwright() as playwright:
            context = self._launch_context(playwright.chromium, account)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                self._goto(page, active_config.inbox_url, "收件箱")
                self._check_risk(page, active_config)
                items = page.locator(item_selector)
                count = min(items.count(), limit)
                replies: list[BrowserReply] = []
                for index in range(count):
                    item = items.nth(index)
                    fallback_title = item.inner_text(timeout=settings.dm_browser_timeout_ms).strip().splitlines()[0]
                    item.click(timeout=settings.dm_browser_timeout_ms)
                    self._check_risk(page, active_config)
                    merchant_name = fallback_title
                    if selector_text(active_config.conversation_title_selector).strip():
                        merchant_name = (
                            page.locator(selector_text(active_config.conversation_title_selector))
                            .first.inner_text(timeout=settings.dm_browser_timeout_ms)
                            .strip()
                            or fallback_title
                        )
                    messages = page.locator(selector_text(active_config.message_text_selector))
                    message_count = messages.count()
                    if not message_count:
                        continue
                    content = messages.nth(message_count - 1).inner_text(timeout=settings.dm_browser_timeout_ms).strip()
                    if not content:
                        continue
                    content_hash = sha1(content.encode("utf-8")).hexdigest()[:16]
                    external_id = f"browser-reply-{account.id}-{index}-{content_hash}"
                    replies.append(
                        BrowserReply(
                            merchant_name=merchant_name,
                            content=content,
                            external_message_id=external_id,
                            raw_payload=dumps(
                                {
                                    "provider": "browser",
                                    "platform": account.platform,
                                    "profile": account.browser_profile_key,
                                    "inboxUrl": active_config.inbox_url,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
                return replies
            finally:
                context.close()


def get_dm_gateway() -> DirectMessageGateway:
    if settings.dm_gateway_mode == "browser":
        return BrowserAutomationDmGateway()
    return SimulatorDmGateway()
