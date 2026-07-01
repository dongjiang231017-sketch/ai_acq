from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class VoiceGatewayProfile:
    key: str
    label: str
    vendor: str
    model: str
    category: str
    transport: str
    host: str
    sip_port: int
    trunk_name: str
    max_channels: int
    line_type: str
    admin_url: str
    discovery_mode: str
    tested: bool
    capabilities: list[str]
    notes: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "vendor": self.vendor,
            "model": self.model,
            "category": self.category,
            "transport": self.transport,
            "host": self.host,
            "sipPort": self.sip_port,
            "trunkName": self.trunk_name,
            "maxChannels": self.max_channels,
            "lineType": self.line_type,
            "adminUrl": self.admin_url,
            "discoveryMode": self.discovery_mode,
            "tested": self.tested,
            "capabilities": self.capabilities,
            "notes": self.notes,
        }


PROFILE_DEFAULTS: dict[str, dict[str, object]] = {
    "uc100_sip_volte": {
        "label": "语音网关（UC100 测试档案）",
        "vendor": "ZHY",
        "model": "UC100",
        "category": "sip_volte_gateway",
        "transport": "sip_udp",
        "line_type": "sim_volte",
        "tested": True,
        "capabilities": ["sip_registration", "sip_to_volte", "single_sim", "asterisk_audiosocket"],
        "notes": [
            "UC100 只是当前实测型号；客户交付可以替换为其他 SIP/VoLTE/GSM 语音网关。",
            "设备后台 IP 会随客户网络变化，客户端应按设备身份和当前局域网重新发现。",
        ],
    },
    "sip_volte_gateway": {
        "label": "通用 SIP/VoLTE 语音网关",
        "vendor": "Generic",
        "model": "SIP/VoLTE Gateway",
        "category": "sip_volte_gateway",
        "transport": "sip_udp",
        "line_type": "sim_volte",
        "tested": False,
        "capabilities": ["sip_registration", "sip_to_volte", "asterisk_audiosocket"],
        "notes": ["按现场设备手册配置 SIP 分机/中继、外呼路由和线路通道。"],
    },
    "multi_sim_lte_gateway": {
        "label": "多卡 LTE/GSM 语音网关",
        "vendor": "Generic",
        "model": "Multi-SIM LTE/GSM Gateway",
        "category": "multi_sim_lte_gateway",
        "transport": "sip_udp",
        "line_type": "multi_sim_cellular",
        "tested": False,
        "capabilities": ["sip_trunk", "multi_sim", "channel_pool", "asterisk_audiosocket"],
        "notes": ["并发能力按物理 SIM/蜂窝通道数计算，不按后台页面宣传值直接放大。"],
    },
    "sip_trunk": {
        "label": "运营商 SIP 中继",
        "vendor": "Carrier",
        "model": "SIP Trunk",
        "category": "sip_trunk",
        "transport": "sip_udp",
        "line_type": "carrier_sip",
        "tested": False,
        "capabilities": ["sip_trunk", "channel_pool", "asterisk_audiosocket"],
        "notes": ["适合客户已有合规企业线路；需按运营商账号、鉴权和白名单配置。"],
    },
}


def current_voice_gateway_profile() -> VoiceGatewayProfile:
    key = _env("VOICE_GATEWAY_PROFILE", "AI_ACQ_VOICE_GATEWAY_PROFILE", default=settings.voice_gateway_profile).strip() or "uc100_sip_volte"
    defaults = PROFILE_DEFAULTS.get(key, PROFILE_DEFAULTS["sip_volte_gateway"])
    host = _env("VOICE_GATEWAY_HOST", "AI_ACQ_VOICE_GATEWAY_HOST", "AI_ACQ_UC100_HOST", default=settings.voice_gateway_host)
    sip_port = _int_env("VOICE_GATEWAY_SIP_PORT", "AI_ACQ_VOICE_GATEWAY_SIP_PORT", "AI_ACQ_UC100_SIP_PORT", default=settings.voice_gateway_sip_port)
    trunk_name = _env("VOICE_GATEWAY_TRUNK_NAME", "AI_ACQ_VOICE_GATEWAY_TRUNK_NAME", default=settings.voice_gateway_trunk_name or settings.asterisk_trunk_name)
    max_channels = _int_env(
        "VOICE_GATEWAY_MAX_CHANNELS",
        "AI_ACQ_VOICE_GATEWAY_MAX_CHANNELS",
        default=settings.voice_gateway_max_channels or settings.asterisk_max_channels,
    )
    admin_url = _env("VOICE_GATEWAY_ADMIN_URL", "AI_ACQ_VOICE_GATEWAY_ADMIN_URL", default=settings.voice_gateway_admin_url)
    label = _env("VOICE_GATEWAY_LABEL", "AI_ACQ_VOICE_GATEWAY_LABEL", default=settings.voice_gateway_label or str(defaults["label"]))
    vendor = _env("VOICE_GATEWAY_VENDOR", "AI_ACQ_VOICE_GATEWAY_VENDOR", default=settings.voice_gateway_vendor or str(defaults["vendor"]))
    model = _env("VOICE_GATEWAY_MODEL", "AI_ACQ_VOICE_GATEWAY_MODEL", default=settings.voice_gateway_model or str(defaults["model"]))
    category = _env("VOICE_GATEWAY_CATEGORY", "AI_ACQ_VOICE_GATEWAY_CATEGORY", default=settings.voice_gateway_category or str(defaults["category"]))
    transport = _env("VOICE_GATEWAY_TRANSPORT", "AI_ACQ_VOICE_GATEWAY_TRANSPORT", default=settings.voice_gateway_transport or str(defaults["transport"]))
    line_type = _env("VOICE_GATEWAY_LINE_TYPE", "AI_ACQ_VOICE_GATEWAY_LINE_TYPE", default=settings.voice_gateway_line_type or str(defaults["line_type"]))
    discovery_mode = _env("VOICE_GATEWAY_DISCOVERY_MODE", "AI_ACQ_VOICE_GATEWAY_DISCOVERY_MODE", default=settings.voice_gateway_discovery_mode)
    return VoiceGatewayProfile(
        key=key,
        label=label,
        vendor=vendor,
        model=model,
        category=category,
        transport=transport,
        host=host,
        sip_port=sip_port,
        trunk_name=trunk_name,
        max_channels=max_channels,
        line_type=line_type,
        admin_url=admin_url or _default_admin_url(host),
        discovery_mode=discovery_mode,
        tested=bool(defaults["tested"]),
        capabilities=list(defaults["capabilities"]),
        notes=list(defaults["notes"]),
    )


def voice_gateway_label() -> str:
    return current_voice_gateway_profile().label


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


def _int_env(*names: str, default: int = 0) -> int:
    for name in names:
        value = os.getenv(name)
        if value is None or value == "":
            continue
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _default_admin_url(host: str) -> str:
    return f"http://{host}/" if host else ""
