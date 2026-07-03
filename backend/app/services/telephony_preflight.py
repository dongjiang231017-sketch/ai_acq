from dataclasses import dataclass
from datetime import datetime

from app.core.config import settings
from app.services.asterisk_ami import AsteriskAmiError, check_asterisk_health, render_originate_channel
from app.services.telephony_runtime_config import telephony_bool, telephony_int, telephony_str
from app.services.voice_gateway_profiles import current_voice_gateway_profile


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
    profile = current_voice_gateway_profile()
    health = check_asterisk_health()
    gateway_mode = telephony_str("TELEPHONY_GATEWAY_MODE", fallback=settings.telephony_gateway_mode)
    deployment_mode = telephony_str("ASTERISK_DEPLOYMENT_MODE", "AI_ACQ_ASTERISK_DEPLOYMENT_MODE", fallback=settings.asterisk_deployment_mode)
    live_call_enabled = telephony_bool("ASTERISK_LIVE_CALL_ENABLED", fallback=settings.asterisk_live_call_enabled)
    bulk_call_enabled = telephony_bool("ASTERISK_BULK_CALL_ENABLED", fallback=settings.asterisk_bulk_call_enabled)
    steps: list[TelephonyPreflightStep] = []

    if gateway_mode == "asterisk":
        steps.append(_step("gateway_mode", "网关模式", "pass", f"当前已切到 Asterisk/{profile.label} 真实线路模式。"))
    else:
        steps.append(
            _step(
                "gateway_mode",
                "网关模式",
                "warn",
                "当前仍是模拟线路，代码不会访问语音网关。",
                (
                    "实机联调时把服务器 Asterisk AMI/SIP 配好，并设置 TELEPHONY_GATEWAY_MODE=asterisk。"
                    if deployment_mode == "server"
                    else "实机联调时让后端读取客户端生成的 backend-asterisk.env，并设置 TELEPHONY_GATEWAY_MODE=asterisk。"
                ),
            )
        )

    steps.append(
        _step(
            "gateway_profile",
            "语音网关档案",
            "pass" if profile.host else "warn",
            f"{profile.label} · {profile.host}:{profile.sip_port} · trunk {profile.trunk_name} · {profile.max_channels} 路",
            (
                "服务器模式下让语音网关主动注册到云端 Asterisk；客户换网络不需要重新发现本机网关地址。"
                if deployment_mode == "server"
                else "设备 IP 变化时用客户端重新发现/重新绑定语音网关；UC100 只是当前已测试档案。"
            ),
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
                (
                    "在服务器 Asterisk 的 manager.conf 创建 AMI 用户，并写入后端环境。"
                    if deployment_mode == "server"
                    else "优先使用桌面客户端内置 Asterisk 生成的 backend-asterisk.env；开发调试才手工配置 ASTERISK_AMI_USERNAME 和 ASTERISK_AMI_PASSWORD。"
                ),
            )
        )

    if health.ami_reachable:
        ami_host = telephony_str("ASTERISK_HOST", "AI_ACQ_ASTERISK_HOST", fallback=settings.asterisk_host)
        ami_port = telephony_int("ASTERISK_AMI_PORT", "AI_ACQ_ASTERISK_AMI_PORT", fallback=settings.asterisk_ami_port)
        steps.append(_step("ami_reachable", "AMI 连接", "pass", f"后端能连接 {ami_host}:{ami_port}。"))
    elif health.configured:
        steps.append(
            _step(
                "ami_reachable",
                "AMI 连接",
                "fail",
                "后端连不上 Asterisk AMI。",
                (
                    "检查服务器 Asterisk 是否运行、manager.conf bindaddr/permit、本机防火墙，以及 ASTERISK_HOST/AMI 端口。"
                    if deployment_mode == "server"
                    else "检查客户端 sidecar 是否已启动、ASTERISK_HOST、ASTERISK_AMI_PORT、manager.conf bindaddr/permit、防火墙。"
                ),
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
        steps.append(_step("trunk_name", "Trunk 名称", "pass", f"当前 trunk 名称：{profile.trunk_name}。"))
    else:
        steps.append(_step("trunk_name", "Trunk 名称", "fail", "Asterisk trunk 名称未配置。", "设置 VOICE_GATEWAY_TRUNK_NAME 或 ASTERISK_TRUNK_NAME。"))

    if health.trunk_reachable is True:
        steps.append(_step("trunk_reachable", "Trunk 可达", "pass", health.trunk_status))
    elif health.trunk_reachable is False:
        steps.append(
            _step(
                "trunk_reachable",
                "Trunk 可达",
                "fail",
                health.trunk_status,
                f"检查{profile.label}是否已注册到服务器 Asterisk、PJSIP endpoint 名称和公网 SIP/RTP 防火墙。"
                if deployment_mode == "server"
                else "检查语音网关 SIP 注册、PJSIP endpoint 名称和现场网络。",
            )
        )
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
                f"当前模板：{telephony_str('ASTERISK_ORIGINATE_CHANNEL_TEMPLATE', fallback=settings.asterisk_originate_channel_template)}",
                "传入 --phone 或在页面输入测试号码后可看到实际 Channel。",
            )
        )

    if live_call_enabled:
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

    if bulk_call_enabled:
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

    ready_for_device_test = gateway_mode == "asterisk" and health.ready_for_test_call
    ready_for_single_number_test = ready_for_device_test and live_call_enabled
    ready_for_bulk_tasks = ready_for_single_number_test and bulk_call_enabled
    next_step = _next_step(ready_for_device_test, ready_for_single_number_test, ready_for_bulk_tasks, steps)

    return {
        "checkedAt": datetime.utcnow(),
        "voiceGatewayProfile": profile.as_dict(),
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
        return "先启动客户端内置 Asterisk，把线路切到 Asterisk，并确认 AMI 登录、Ping、语音网关 trunk 可达。"
    if not ready_for_single_number_test:
        return "设备链路已基本可测；打开 ASTERISK_LIVE_CALL_ENABLED=true 后做单号试拨。"
    if not ready_for_bulk_tasks:
        return "可以做单号试拨；确认稳定后再打开 ASTERISK_BULK_CALL_ENABLED=true。"
    return "真实线路和批量拨号开关均已开启，开始前请确认线索授权、频控、黑名单和安静时段。"
