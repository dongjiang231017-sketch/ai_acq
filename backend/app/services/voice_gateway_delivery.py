from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from secrets import choice, token_hex
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.delivery import VoiceGatewayDeviceDiscovery, VoiceGatewayLine, VoiceGatewayLineEvent
from app.models.user import User
from app.services.voice_gateway_profiles import PROFILE_DEFAULTS


ONE_TIME_WARNING = "SIP 密码只在本次响应展示；交付后请写入受控密钥库，丢失后只能重新轮换。"
DEFAULT_SIP_SERVER_HOST = "101.132.63.159"
DEFAULT_CODEC_PRIMARY = "PCMA/alaw"
DEFAULT_CODEC_SECONDARY = "PCMU/ulaw"
DEFAULT_DTMF_MODE = "RFC2833/RFC4733"
DEFAULT_RTP_RANGE = "10000-20000/UDP"
DEFAULT_ROUTE_DIRECTION = "SIP中继/SIP -> VoLTE/GSM/SIM"
DEFAULT_ASTERISK_DYNAMIC_PJSIP_PATH = Path("/etc/asterisk/pjsip_ai_acq_delivery_dynamic.conf")
SECRET_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
PROFILE_CHANNEL_DEFAULTS = {
    "dinstar_8t_server": 8,
    "multi_sim_lte_gateway": 8,
    "uc100_sip_volte": 1,
    "sip_volte_gateway": 1,
    "sip_trunk": 1,
}
MERGEABLE_DUPLICATE_LINE_STATUSES = {
    "",
    "待配置",
    "待设备发现",
    "设备未发现",
    "待设备注册",
    "待重新下发",
    "待重新交付",
    "待下发",
}
INACTIVE_LINE_STATUSES = {"已合并停用"}


class VoiceGatewayRedeliveryError(ValueError):
    """Raised when a gateway cannot be safely re-delivered to another customer."""


@dataclass(frozen=True)
class VoiceGatewayRedeliveryResult:
    line: VoiceGatewayLine
    discovery: VoiceGatewayDeviceDiscovery
    previous_owner_user_id: str
    previous_customer_name: str
    previous_sip_username: str
    previous_trunk_name: str
    sip_password_one_time: str
    asterisk_sync_message: str


def generate_sip_password(length: int = 24) -> str:
    return "".join(choice(SECRET_ALPHABET) for _ in range(length))


def normalise_mac(value: str | None) -> str:
    return re.sub(r"[^0-9a-f]", "", (value or "").lower())


def normalise_serial(value: str | None) -> str:
    return (value or "").strip().lower()


def ip_from_admin_url(admin_url: str | None) -> str:
    if not admin_url:
        return ""
    match = re.match(r"^https?://([^/:]+)", admin_url, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def device_discovery_can_bind(discovery: VoiceGatewayDeviceDiscovery) -> bool:
    status_value = (discovery.status or "").strip()
    if status_value.lower() in {"not_found", "missing", "none", "unavailable"} or status_value in {"未发现", "无设备"}:
        return False
    if discovery.device_admin_url or discovery.device_ip or discovery.device_mac or discovery.device_serial:
        return True
    if _is_fail_status(status_value):
        return False
    return status_value.lower() in {"found", "current", "updated", "pass", "passed", "ready", "ok"} or status_value in {
        "已发现",
        "已绑定",
        "通过",
        "正常",
    }


def discovery_matches_line(line: VoiceGatewayLine, discovery: VoiceGatewayDeviceDiscovery) -> bool:
    discovery_mac = normalise_mac(discovery.device_mac)
    if discovery_mac and normalise_mac(line.device_mac) == discovery_mac:
        return True

    discovery_serial = normalise_serial(discovery.device_serial)
    if discovery_serial and normalise_serial(line.device_serial) == discovery_serial:
        return True

    discovery_admin_url = (discovery.device_admin_url or "").strip().rstrip("/")
    line_admin_url = (line.device_admin_url or "").strip().rstrip("/")
    if discovery_admin_url and line_admin_url and discovery_admin_url == line_admin_url:
        return True

    discovery_host = discovery.device_ip or ip_from_admin_url(discovery.device_admin_url)
    if discovery_host and ip_from_admin_url(line.device_admin_url) == discovery_host:
        return True

    return False


def find_assigned_line_for_device(
    db: Session,
    discovery: VoiceGatewayDeviceDiscovery,
    *,
    exclude_owner_user_id: str | None = None,
) -> VoiceGatewayLine | None:
    if not device_discovery_can_bind(discovery):
        return None

    statement = select(VoiceGatewayLine).order_by(VoiceGatewayLine.updated_at.desc(), VoiceGatewayLine.created_at.desc())
    if exclude_owner_user_id:
        statement = statement.where(VoiceGatewayLine.owner_user_id != exclude_owner_user_id)
    statement = statement.where(VoiceGatewayLine.status.notin_(INACTIVE_LINE_STATUSES))
    lines = list(db.scalars(statement).all())
    for line in lines:
        if discovery_matches_line(line, discovery):
            return line
    return None


def find_redelivery_discovery_for_line(
    db: Session,
    line: VoiceGatewayLine,
    *,
    target_owner_user_id: str | None = None,
) -> VoiceGatewayDeviceDiscovery | None:
    statement = select(VoiceGatewayDeviceDiscovery).where(VoiceGatewayDeviceDiscovery.owner_user_id != line.owner_user_id)
    if target_owner_user_id:
        statement = statement.where(VoiceGatewayDeviceDiscovery.owner_user_id == target_owner_user_id)
    discoveries = list(
        db.scalars(
            statement.order_by(
                VoiceGatewayDeviceDiscovery.updated_at.desc(),
                VoiceGatewayDeviceDiscovery.created_at.desc(),
            )
        ).all()
    )
    for prefer_unmatched in (True, False):
        for discovery in discoveries:
            if prefer_unmatched and discovery.matched_line_id is not None:
                continue
            if not prefer_unmatched and discovery.matched_line_id is None:
                continue
            if device_discovery_can_bind(discovery) and discovery_matches_line(line, discovery):
                return discovery
    return None


def redeliver_voice_gateway_line(
    db: Session,
    line: VoiceGatewayLine,
    discovery: VoiceGatewayDeviceDiscovery,
    target_owner: User,
    *,
    actor_user_id: str | None,
    password: str | None = None,
    sync_asterisk: bool = True,
    asterisk_path: Path | None = None,
    reload_callback: Callable[[], str] | None = None,
) -> VoiceGatewayRedeliveryResult:
    if not device_discovery_can_bind(discovery):
        raise VoiceGatewayRedeliveryError("客户客户端还没有发现可用语音网关，不能转移设备")
    if line.owner_user_id == target_owner.id:
        raise VoiceGatewayRedeliveryError("目标客户已经是当前线路归属，无需重新交付")
    if discovery.owner_user_id != target_owner.id:
        raise VoiceGatewayRedeliveryError("设备发现记录不属于目标客户账号，不能用于本次重新交付")
    if not discovery_matches_line(line, discovery):
        raise VoiceGatewayRedeliveryError("待转移设备发现记录与当前线路的 MAC、序列号或后台地址不一致")

    previous_owner_user_id = line.owner_user_id
    previous_customer_name = line.customer_name
    previous_sip_username = line.sip_username
    previous_trunk_name = line.trunk_name
    password = password or generate_sip_password()
    sip_username, trunk_name = generate_line_identity(db, target_owner)
    customer_name = customer_name_for_user(target_owner)
    now = datetime.utcnow()

    _mark_previous_discoveries_transferred(db, line, previous_owner_user_id)

    line.owner_user_id = target_owner.id
    line.line_name = unique_line_name(
        db,
        target_owner.id,
        f"{customer_name or '客户'} 语音网关 {now.strftime('%m%d-%H%M')}",
    )
    line.customer_name = customer_name
    if discovery.gateway_profile_key in PROFILE_DEFAULTS:
        line.gateway_profile_key = discovery.gateway_profile_key
    profile = PROFILE_DEFAULTS.get(line.gateway_profile_key, PROFILE_DEFAULTS["dinstar_8t_server"])
    line.gateway_label = discovery.gateway_label or line.gateway_label or str(profile["label"])
    line.gateway_vendor = line.gateway_vendor or str(profile["vendor"])
    line.gateway_model = line.gateway_model or str(profile["model"])
    line.gateway_category = line.gateway_category or str(profile["category"])
    line.deployment_mode = line.deployment_mode or "server"
    line.sip_server_host = line.sip_server_host or DEFAULT_SIP_SERVER_HOST
    line.sip_server_port = line.sip_server_port or 5060
    line.sip_transport = line.sip_transport or "UDP"
    line.sip_username = sip_username
    line.sip_auth_username = sip_username
    line.sip_password_hash = hash_password(password)
    line.trunk_name = trunk_name
    line.sip_password_secret_alias = f"voice-gateway/{target_owner.id}/{trunk_name}/sip-password"
    line.channel_count = line.channel_count or PROFILE_CHANNEL_DEFAULTS.get(line.gateway_profile_key, 1)
    line.codec_primary = line.codec_primary or DEFAULT_CODEC_PRIMARY
    line.codec_secondary = line.codec_secondary or DEFAULT_CODEC_SECONDARY
    line.dtmf_mode = line.dtmf_mode or DEFAULT_DTMF_MODE
    line.rtp_port_range = line.rtp_port_range or DEFAULT_RTP_RANGE
    line.route_direction = line.route_direction or DEFAULT_ROUTE_DIRECTION
    apply_device_discovery_to_line(line, discovery, overwrite_device_address=True)
    line.status = "待重新交付"
    line.registration_status = "待重新注册"
    line.route_status = "待检查"
    line.sim_status = "待检查"
    line.rtp_status = "待检查"
    line.acceptance_status = "待单号验收"
    line.last_registered_at = None
    line.last_preflight_at = None
    line.notes = append_note(
        line.notes,
        f"重新交付：从客户账号 {previous_owner_user_id} 转移到 {target_owner.id}；"
        "旧 SIP/trunk 已失效，现场设备后台只需覆盖 SIP/端口组/路由配置，不要恢复出厂设置。",
    )
    line.updated_at = now
    _retire_mergeable_target_duplicates(db, line, target_owner.id)

    discovery.owner_user_id = target_owner.id
    discovery.matched_line_id = line.id
    discovery.status = "matched"
    discovery.updated_at = now
    db.flush()

    sync_message = "未同步 Asterisk"
    if sync_asterisk:
        sync_message = upsert_asterisk_dynamic_pjsip(
            line,
            password,
            path=asterisk_path or DEFAULT_ASTERISK_DYNAMIC_PJSIP_PATH,
            reload_callback=reload_callback,
        )

    db.add(
        VoiceGatewayLineEvent(
            line_id=line.id,
            owner_user_id=line.owner_user_id,
            actor_user_id=actor_user_id,
            event_type="redelivered",
            status="pending_device_update",
            summary="重新交付/转移语音网关设备",
            detail=(
                f"原客户账号={previous_owner_user_id}；新客户账号={target_owner.id}；"
                f"原SIP={previous_sip_username}；新SIP={line.sip_username}；{device_discovery_note(discovery)}"
            ),
            evidence_json=discovery.evidence_json,
        )
    )
    db.flush()

    return VoiceGatewayRedeliveryResult(
        line=line,
        discovery=discovery,
        previous_owner_user_id=previous_owner_user_id,
        previous_customer_name=previous_customer_name,
        previous_sip_username=previous_sip_username,
        previous_trunk_name=previous_trunk_name,
        sip_password_one_time=password,
        asterisk_sync_message=sync_message,
    )


def generate_line_identity(db: Session, owner: User) -> tuple[str, str]:
    owner_slug = slug(owner.username or owner.id)
    for _ in range(30):
        suffix = token_hex(4)
        sip_username = f"sip_{owner_slug}_{suffix}"
        trunk_name = f"tg_{owner_slug}_{suffix}"
        exists = db.scalar(
            select(VoiceGatewayLine.id).where(
                (VoiceGatewayLine.sip_username == sip_username) | (VoiceGatewayLine.trunk_name == trunk_name)
            )
        )
        if not exists:
            return sip_username, trunk_name
    suffix = token_hex(8)
    return f"sip_{owner_slug}_{suffix}", f"tg_{owner_slug}_{suffix}"


def unique_line_name(db: Session, owner_user_id: str, base_name: str) -> str:
    base = base_name.strip()[:104] or "客户语音网关"
    for index in range(30):
        candidate = base if index == 0 else f"{base}-{index + 1}"
        exists = db.scalar(
            select(VoiceGatewayLine.id).where(
                VoiceGatewayLine.owner_user_id == owner_user_id,
                VoiceGatewayLine.line_name == candidate,
            )
        )
        if not exists:
            return candidate
    return f"{base}-{token_hex(3)}"[:120]


def customer_name_for_user(owner: User) -> str:
    return (owner.display_name or owner.username or owner.id).strip()


def apply_device_discovery_to_line(
    line: VoiceGatewayLine,
    discovery: VoiceGatewayDeviceDiscovery,
    *,
    overwrite_device_address: bool = False,
) -> None:
    if discovery.device_admin_url and (overwrite_device_address or not line.device_admin_url):
        line.device_admin_url = discovery.device_admin_url
    if discovery.device_mac and (overwrite_device_address or not line.device_mac):
        line.device_mac = discovery.device_mac
    if discovery.device_serial and (overwrite_device_address or not line.device_serial):
        line.device_serial = discovery.device_serial
    note = device_discovery_note(discovery)
    if note:
        line.network_note = append_note(line.network_note, note)


def append_note(current: str | None, note: str) -> str:
    if not note:
        return (current or "").strip()
    line = f"{datetime.utcnow().isoformat(timespec='seconds')} {note}"
    return f"{(current or '').strip()}\n{line}".strip() if (current or "").strip() else line


def device_discovery_note(discovery: VoiceGatewayDeviceDiscovery) -> str:
    parts = [f"source={discovery.source}", f"status={discovery.status}"]
    if discovery.device_admin_url:
        parts.append(f"admin={discovery.device_admin_url}")
    if discovery.device_ip:
        parts.append(f"ip={discovery.device_ip}")
    if discovery.device_mac:
        parts.append(f"mac={discovery.device_mac}")
    if discovery.device_serial:
        parts.append(f"serial={discovery.device_serial}")
    if discovery.summary:
        parts.append(discovery.summary)
    return "；".join(part for part in parts if part)


def render_asterisk_dynamic_pjsip(line: VoiceGatewayLine, password: str) -> str:
    trunk_name = safe_pjsip_token(line.trunk_name, "云端 Trunk")
    sip_username = safe_pjsip_token(line.sip_username, "SIP 账号")
    sip_auth_username = safe_pjsip_token(line.sip_auth_username or line.sip_username, "鉴权账号")
    max_contacts = max(1, int(line.channel_count or 1))
    context = "from-dinstar8t" if line.gateway_profile_key != "uc100_sip_volte" else "from-uc100"
    auth_name = f"{sip_username}-auth"
    aor_name = sip_username
    endpoint_names = [sip_username]
    if trunk_name != sip_username:
        endpoint_names.append(trunk_name)

    endpoint_blocks = "\n".join(
        f"""[{endpoint_name}]
type = endpoint
transport = transport-udp
context = {context}
disallow = all
allow = alaw
allow = ulaw
direct_media = no
force_rport = yes
rewrite_contact = yes
rtp_symmetric = yes
timers = no
auth = {auth_name}
aors = {aor_name}
from_user = {sip_username}
callerid = AI获客 <{sip_username}>
"""
        for endpoint_name in endpoint_names
    )
    return f"""; BEGIN AI_ACQ_LINE {line.id}
{endpoint_blocks}
[{auth_name}]
type = auth
auth_type = userpass
username = {sip_auth_username}
password = {password}

[{aor_name}]
type = aor
max_contacts = {max_contacts}
remove_existing = no
qualify_frequency = 30
; END AI_ACQ_LINE {line.id}
"""


def upsert_asterisk_dynamic_pjsip(
    line: VoiceGatewayLine,
    password: str,
    *,
    path: Path = DEFAULT_ASTERISK_DYNAMIC_PJSIP_PATH,
    reload_callback: Callable[[], str] | None = None,
) -> str:
    marker_start = f"; BEGIN AI_ACQ_LINE {line.id}"
    marker_end = f"; END AI_ACQ_LINE {line.id}"
    next_block = render_asterisk_dynamic_pjsip(line, password)
    existed_before = path.exists()
    current = path.read_text(encoding="utf-8") if existed_before else ""
    pattern = re.compile(
        rf"^; BEGIN AI_ACQ_LINE {re.escape(line.id)}\n.*?^; END AI_ACQ_LINE {re.escape(line.id)}\n?",
        flags=re.MULTILINE | re.DOTALL,
    )
    if marker_start in current and marker_end in current:
        updated = pattern.sub(next_block, current).strip() + "\n"
    else:
        updated = (current.rstrip() + "\n\n" + next_block).lstrip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    try:
        return reload_callback() if reload_callback is not None else reload_asterisk_pjsip()
    except Exception:
        if existed_before:
            path.write_text(current, encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        raise


def reload_asterisk_pjsip() -> str:
    commands = [
        ["asterisk", "-rx", "pjsip reload"],
        ["asterisk", "-rx", "dialplan reload"],
    ]
    outputs: list[str] = []
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=12)
        output = (result.stdout or result.stderr or "").strip()
        outputs.append(output)
        if result.returncode != 0:
            raise RuntimeError(output or f"{' '.join(command)} 执行失败")
    return "；".join(item for item in outputs if item) or "Asterisk 已重新加载"


def safe_pjsip_token(value: str, label: str) -> str:
    token = (value or "").strip()
    if not token or not re.fullmatch(r"[0-9A-Za-z_.@-]+", token):
        raise ValueError(f"{label} 只能包含字母、数字、下划线、点、@ 或短横线")
    return token


def slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").lower()
    return cleaned[:40] or token_hex(4)


def _mark_previous_discoveries_transferred(db: Session, line: VoiceGatewayLine, previous_owner_user_id: str) -> None:
    discoveries = db.scalars(
        select(VoiceGatewayDeviceDiscovery).where(
            VoiceGatewayDeviceDiscovery.owner_user_id == previous_owner_user_id,
            VoiceGatewayDeviceDiscovery.matched_line_id == line.id,
        )
    ).all()
    for discovery in discoveries:
        discovery.status = "transferred"
        discovery.updated_at = datetime.utcnow()


def _retire_mergeable_target_duplicates(db: Session, canonical_line: VoiceGatewayLine, target_owner_user_id: str) -> None:
    duplicates = db.scalars(
        select(VoiceGatewayLine)
        .where(
            VoiceGatewayLine.owner_user_id == target_owner_user_id,
            VoiceGatewayLine.id != canonical_line.id,
        )
        .order_by(VoiceGatewayLine.updated_at.desc(), VoiceGatewayLine.created_at.desc())
    ).all()
    for duplicate in duplicates:
        if not discovery_matches_line(duplicate, _line_as_discovery(canonical_line)):
            continue
        if (duplicate.status or "") not in MERGEABLE_DUPLICATE_LINE_STATUSES:
            raise VoiceGatewayRedeliveryError(
                f"目标客户已有同一设备的非占位线路 {duplicate.line_name}，请先人工确认后再转移"
            )
        duplicate.status = "已合并停用"
        duplicate.registration_status = "已停用"
        duplicate.route_status = "已停用"
        duplicate.sim_status = "已停用"
        duplicate.rtp_status = "已停用"
        duplicate.acceptance_status = "已停用"
        duplicate.device_admin_url = ""
        duplicate.device_mac = ""
        duplicate.device_serial = ""
        duplicate.notes = append_note(
            duplicate.notes,
            f"重新交付时合并停用：同一设备已转入线路 {canonical_line.id} / {canonical_line.line_name}",
        )
        duplicate.updated_at = datetime.utcnow()
        _mark_duplicate_discoveries_merged(db, duplicate)


def _mark_duplicate_discoveries_merged(db: Session, duplicate: VoiceGatewayLine) -> None:
    discoveries = db.scalars(
        select(VoiceGatewayDeviceDiscovery).where(VoiceGatewayDeviceDiscovery.matched_line_id == duplicate.id)
    ).all()
    for discovery in discoveries:
        discovery.status = "merged"
        discovery.matched_line_id = None
        discovery.updated_at = datetime.utcnow()


def _line_as_discovery(line: VoiceGatewayLine) -> VoiceGatewayDeviceDiscovery:
    return VoiceGatewayDeviceDiscovery(
        owner_user_id=line.owner_user_id,
        status="found",
        device_admin_url=line.device_admin_url,
        device_mac=line.device_mac,
        device_serial=line.device_serial,
    )


def _is_pass_status(value: str) -> bool:
    return value.lower() in {"pass", "passed", "ok", "ready", "success"} or value in {"通过", "已通过", "正常", "已注册", "可达", "接通", "验收通过"}


def _is_fail_status(value: str) -> bool:
    return value.lower() in {"fail", "failed", "error", "blocked"} or value in {"失败", "故障", "不可用", "未注册", "阻塞"}
