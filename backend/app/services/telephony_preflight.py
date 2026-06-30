from dataclasses import dataclass
from datetime import datetime

from app.core.config import settings
from app.services.asterisk_ami import AsteriskAmiError, check_asterisk_health, render_originate_channel


@dataclass(frozen=True)
class TelephonyPreflightStep:
    key: str
    label: str
    status: str
    detail: str
    action: str

    def as_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "action": self.action,
        }


def _step(key: str, label: str, status: str, detail: str, action: str = "") -> TelephonyPreflightStep:
    return TelephonyPreflightStep(key=key, label=label, status=status, detail=detail, action=action)


def build_telephony_preflight(test_phone: str | None = None) -> dict[str, object]:
    health = check_asterisk_health()
    steps: list[TelephonyPreflightStep] = []

    if settings.telephony_gateway_mode == "asterisk":
        steps.append(_step("gateway_mode", "网关模式", "pass", "当前已切到 Asterisk/UC100 真实线路模式。"))
    else:
        steps.append(
            _step(
                "gateway_mode",
                "网关模式",
                "warn",
                "当前仍是模拟线路，代码不会访问 UC100。",
                "实机联调时设置 TELEPHONY_GATEWAY_MODE=asterisk。",
            )
        )

    if health.configured:
        steps.append(_step("ami_credentials", "AMI 账号", "pass", "AMI 用户名和密码已配置。"))
    else:
        steps.append(
            _step(
                "ami_credentials",
                "AMI 账号",
                "fail",
                "AMI 用户名或密码未配置。",
                "在 backend/.env 配置 ASTERISK_AMI_USERNAME 和 ASTERISK_AMI_PASSWORD。",
            )
        )

    if health.ami_reachable:
        steps.append(_step("ami_reachable", "AMI 连接", "pass", f"后端能连接 {settings.asterisk_host}:{settings.asterisk_ami_port}。"))
    elif health.configured:
        steps.append(
            _step(
                "ami_reachable",
                "AMI 连接",
                "fail",
                "后端连不上 Asterisk AMI。",
                "检查 ASTERISK_HOST、ASTERISK_AMI_PORT、Asterisk manager.conf bindaddr/permit、防火墙。",
            )
        )
    else:
        steps.append(_step("ami_reachable", "AMI 连接", "warn", "等待 AMI 账号配置后再检测连接。"))

    if health.authenticated and health.ping_ok:
        steps.append(_step("ami_auth", "AMI 登录", "pass", "AMI 登录和 Ping 均通过。"))
    elif health.ami_reachable:
        steps.append(_step("ami_auth", "AMI 登录", "fail", "AMI 已连接，但登录或 Ping 未通过。", "检查 AMI 用户权限和 secret。"))
    else:
        steps.append(_step("ami_auth", "AMI 登录", "warn", "AMI 未连接，暂不能验证登录。"))

    if health.trunk_configured:
        steps.append(_step("trunk_name", "Trunk 名称", "pass", f"当前 trunk 名称：{settings.asterisk_trunk_name}。"))
    else:
        steps.append(_step("trunk_name", "Trunk 名称", "fail", "Asterisk trunk 名称未配置。", "设置 ASTERISK_TRUNK_NAME，例如 uc100。"))

    if health.trunk_reachable is True:
        steps.append(_step("trunk_reachable", "Trunk 可达", "pass", health.trunk_status))
    elif health.trunk_reachable is False:
        steps.append(_step("trunk_reachable", "Trunk 可达", "fail", health.trunk_status, "检查 UC100 SIP 注册、PJSIP endpoint 名称和网络。"))
    elif health.authenticated:
        steps.append(
            _step(
                "trunk_reachable",
                "Trunk 可达",
                "warn",
                health.trunk_status,
                "在 Asterisk CLI 执行 pjsip show endpoint <trunk>，确认显示 Reachable/Contact。",
            )
        )
    else:
        steps.append(_step("trunk_reachable", "Trunk 可达", "warn", "等待 AMI 登录后再检测 trunk。"))

    if test_phone:
        try:
            channel = render_originate_channel(test_phone)
            steps.append(_step("dial_channel", "拨号通道", "pass", channel))
        except AsteriskAmiError as exc:
            steps.append(_step("dial_channel", "拨号通道", "fail", str(exc), "检查测试号码格式和 ASTERISK_ORIGINATE_CHANNEL_TEMPLATE。"))
    else:
        steps.append(
            _step(
                "dial_channel",
                "拨号通道",
                "warn",
                f"当前模板：{settings.asterisk_originate_channel_template}",
                "传入 --phone 或在页面输入测试号码后可看到实际 Channel。",
            )
        )

    if settings.asterisk_live_call_enabled:
        steps.append(_step("live_switch", "单号试拨开关", "pass", "ASTERISK_LIVE_CALL_ENABLED 已开启。"))
    else:
        steps.append(
            _step(
                "live_switch",
                "单号试拨开关",
                "warn",
                "真实拨号开关仍关闭，系统不会发起真实单号拨号。",
                "AMI/trunk 通过后，再设置 ASTERISK_LIVE_CALL_ENABLED=true 做单号试拨。",
            )
        )

    if settings.asterisk_bulk_call_enabled:
        steps.append(_step("bulk_switch", "批量拨号开关", "pass", "ASTERISK_BULK_CALL_ENABLED 已开启。"))
    else:
        steps.append(
            _step(
                "bulk_switch",
                "批量拨号开关",
                "warn",
                "批量真实外呼仍锁定。",
                "单号试拨稳定后，才设置 ASTERISK_BULK_CALL_ENABLED=true。",
            )
        )

    ready_for_device_test = settings.telephony_gateway_mode == "asterisk" and health.ready_for_test_call
    ready_for_single_number_test = ready_for_device_test and settings.asterisk_live_call_enabled
    ready_for_bulk_tasks = ready_for_single_number_test and settings.asterisk_bulk_call_enabled
    next_step = _next_step(ready_for_device_test, ready_for_single_number_test, ready_for_bulk_tasks, steps)

    return {
        "checkedAt": datetime.utcnow(),
        "readyForDeviceTest": ready_for_device_test,
        "readyForSingleNumberTest": ready_for_single_number_test,
        "readyForBulkTasks": ready_for_bulk_tasks,
        "nextStep": next_step,
        "health": health.as_dict(),
        "steps": [step.as_dict() for step in steps],
    }


def _next_step(
    ready_for_device_test: bool,
    ready_for_single_number_test: bool,
    ready_for_bulk_tasks: bool,
    steps: list[TelephonyPreflightStep],
) -> str:
    first_fail = next((step for step in steps if step.status == "fail"), None)
    if first_fail:
        return first_fail.action or first_fail.detail
    if not ready_for_device_test:
        return "先把网关切到 Asterisk，并确认 AMI 登录、Ping、trunk 可达。"
    if not ready_for_single_number_test:
        return "设备链路已基本可测；打开 ASTERISK_LIVE_CALL_ENABLED=true 后做单号试拨。"
    if not ready_for_bulk_tasks:
        return "可以做单号试拨；确认稳定后再打开 ASTERISK_BULK_CALL_ENABLED=true。"
    return "真实线路和批量拨号开关均已开启，开始前请确认线索授权、频控、黑名单和安静时段。"
