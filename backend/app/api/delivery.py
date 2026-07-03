from __future__ import annotations

import re
from datetime import datetime
from secrets import choice, token_hex

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.security import hash_password
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.delivery import VoiceGatewayLine, VoiceGatewayLineEvent
from app.models.user import User
from app.schemas.delivery import (
    VoiceGatewayConfigCard,
    VoiceGatewayCredentialRotation,
    VoiceGatewayLineCreate,
    VoiceGatewayLineCreated,
    VoiceGatewayLineEventCreate,
    VoiceGatewayLineEventRead,
    VoiceGatewayLineRead,
    VoiceGatewayLineUpdate,
)
from app.services.voice_gateway_profiles import PROFILE_DEFAULTS

router = APIRouter()

ONE_TIME_WARNING = "SIP 密码只在本次响应展示；交付后请写入受控密钥库，丢失后只能重新轮换。"
DEFAULT_CODEC_PRIMARY = "PCMA/alaw"
DEFAULT_CODEC_SECONDARY = "PCMU/ulaw"
DEFAULT_DTMF_MODE = "RFC2833/RFC4733"
DEFAULT_RTP_RANGE = "10000-20000/UDP"
DEFAULT_ROUTE_DIRECTION = "SIP中继/SIP -> VoLTE/GSM/SIM"
SECRET_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


@router.get("/voice-gateway-profiles")
def list_voice_gateway_profiles() -> list[dict[str, object]]:
    return [
        {
            "key": key,
            "label": defaults["label"],
            "vendor": defaults["vendor"],
            "model": defaults["model"],
            "category": defaults["category"],
            "lineType": defaults["line_type"],
            "tested": defaults["tested"],
            "capabilities": defaults["capabilities"],
            "notes": defaults["notes"],
        }
        for key, defaults in PROFILE_DEFAULTS.items()
    ]


@router.get("/voice-gateway-lines", response_model=list[VoiceGatewayLineRead])
def list_voice_gateway_lines(
    include_all: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, object]]:
    statement = select(VoiceGatewayLine)
    if not (include_all and current_user.is_superuser):
        statement = statement.where(VoiceGatewayLine.owner_user_id == current_user.id)
    lines = db.scalars(statement.order_by(VoiceGatewayLine.created_at.desc())).all()
    return [_read_line(line) for line in lines]


@router.post(
    "/voice-gateway-lines",
    response_model=VoiceGatewayLineCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_voice_gateway_line(
    payload: VoiceGatewayLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    owner = _resolve_owner(payload.owner_user_id, db, current_user)
    profile = _profile_defaults(payload.gateway_profile_key)
    password = _generate_sip_password()
    suffix = token_hex(4)
    owner_slug = _slug(owner.username or owner.id)
    sip_username = f"sip_{owner_slug}_{suffix}"
    trunk_name = f"tg_{owner_slug}_{suffix}"
    line = VoiceGatewayLine(
        owner_user_id=owner.id,
        created_by_user_id=current_user.id,
        line_name=payload.line_name.strip(),
        customer_name=(payload.customer_name or owner.display_name or owner.username).strip(),
        gateway_profile_key=payload.gateway_profile_key,
        gateway_label=(payload.gateway_label or str(profile["label"])).strip(),
        gateway_vendor=(payload.gateway_vendor or str(profile["vendor"])).strip(),
        gateway_model=(payload.gateway_model or str(profile["model"])).strip(),
        gateway_category=(payload.gateway_category or str(profile["category"])).strip(),
        deployment_mode="server",
        sip_server_host=payload.sip_server_host.strip(),
        sip_server_port=payload.sip_server_port,
        sip_transport=payload.sip_transport,
        sip_username=sip_username,
        sip_auth_username=sip_username,
        sip_password_hash=hash_password(password),
        sip_password_secret_alias=f"voice-gateway/{owner.id}/{trunk_name}/sip-password",
        trunk_name=trunk_name,
        channel_count=payload.channel_count,
        codec_primary=DEFAULT_CODEC_PRIMARY,
        codec_secondary=DEFAULT_CODEC_SECONDARY,
        dtmf_mode=DEFAULT_DTMF_MODE,
        rtp_port_range=DEFAULT_RTP_RANGE,
        route_direction=DEFAULT_ROUTE_DIRECTION,
        device_admin_url=(payload.device_admin_url or "").strip(),
        device_serial=(payload.device_serial or "").strip(),
        device_mac=(payload.device_mac or "").strip(),
        network_note=(payload.network_note or "").strip(),
        notes=(payload.notes or "").strip(),
    )
    db.add(line)
    db.flush()
    _add_event(
        db,
        line,
        current_user,
        event_type="line_created",
        status="created",
        summary="生成客户语音网关配置卡",
        detail=f"{line.gateway_label} / {line.sip_server_host}:{line.sip_server_port}/{line.sip_transport}",
    )
    _add_audit(db, current_user, "voice_gateway_line.create", line.id, f"生成语音网关线路：{line.line_name}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该客户线路名称、SIP账号或 trunk 名称已存在") from exc
    db.refresh(line)
    data = _read_line(line)
    data["sipPasswordOneTime"] = password
    data["oneTimeWarning"] = ONE_TIME_WARNING
    return data


@router.get("/voice-gateway-lines/{line_id}", response_model=VoiceGatewayLineRead)
def get_voice_gateway_line(
    line_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    return _read_line(_get_line(line_id, db, current_user))


@router.patch("/voice-gateway-lines/{line_id}", response_model=VoiceGatewayLineRead)
def update_voice_gateway_line(
    line_id: str,
    payload: VoiceGatewayLineUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    line = _get_line(line_id, db, current_user)
    updates = payload.model_dump(exclude_unset=True, by_alias=False)
    for field, value in updates.items():
        if value is None:
            value = ""
        if isinstance(value, str):
            value = value.strip()
        setattr(line, field, value)
    line.updated_at = datetime.utcnow()
    _add_audit(db, current_user, "voice_gateway_line.update", line.id, f"更新语音网关线路：{line.line_name}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="线路名称或配置与已有线路冲突") from exc
    db.refresh(line)
    return _read_line(line)


@router.get("/voice-gateway-lines/{line_id}/config-card", response_model=VoiceGatewayConfigCard)
def get_voice_gateway_config_card(
    line_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    return _config_card(_get_line(line_id, db, current_user))


@router.post("/voice-gateway-lines/{line_id}/rotate-credential", response_model=VoiceGatewayCredentialRotation)
def rotate_voice_gateway_credential(
    line_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    line = _get_line(line_id, db, current_user)
    password = _generate_sip_password()
    line.sip_password_hash = hash_password(password)
    line.status = "待重新下发"
    line.registration_status = "待重新注册"
    line.updated_at = datetime.utcnow()
    _add_event(
        db,
        line,
        current_user,
        event_type="credential_rotated",
        status="rotated",
        summary="轮换语音网关 SIP 密码",
        detail="旧密码失效后，需要同步更新云端 Asterisk 和现场语音网关后台。",
    )
    _add_audit(db, current_user, "voice_gateway_line.rotate_credential", line.id, f"轮换语音网关密码：{line.line_name}")
    db.commit()
    db.refresh(line)
    return {
        "line": _read_line(line),
        "sipPasswordOneTime": password,
        "oneTimeWarning": ONE_TIME_WARNING,
    }


@router.get("/voice-gateway-lines/{line_id}/events", response_model=list[VoiceGatewayLineEventRead])
def list_voice_gateway_line_events(
    line_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[VoiceGatewayLineEvent]:
    line = _get_line(line_id, db, current_user)
    return list(
        db.scalars(
            select(VoiceGatewayLineEvent)
            .where(VoiceGatewayLineEvent.line_id == line.id)
            .order_by(VoiceGatewayLineEvent.created_at.desc())
        ).all()
    )


@router.post(
    "/voice-gateway-lines/{line_id}/events",
    response_model=VoiceGatewayLineEventRead,
    status_code=status.HTTP_201_CREATED,
)
def create_voice_gateway_line_event(
    line_id: str,
    payload: VoiceGatewayLineEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VoiceGatewayLineEvent:
    line = _get_line(line_id, db, current_user)
    event = _add_event(
        db,
        line,
        current_user,
        event_type=payload.event_type,
        status=payload.status,
        summary=payload.summary,
        detail=payload.detail,
        evidence_json=payload.evidence_json,
    )
    _apply_event_to_line(line, payload)
    _add_audit(db, current_user, "voice_gateway_line.event", line.id, f"{line.line_name} 验收事件：{payload.event_type}")
    db.commit()
    db.refresh(event)
    return event


def _resolve_owner(owner_user_id: str | None, db: Session, current_user: User) -> User:
    if owner_user_id and owner_user_id != current_user.id:
        if not current_user.is_superuser:
            raise HTTPException(status_code=403, detail="只有超级用户可以为其他客户生成线路")
        owner = db.get(User, owner_user_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="客户账号不存在")
        return owner
    return current_user


def _get_line(line_id: str, db: Session, current_user: User) -> VoiceGatewayLine:
    line = db.get(VoiceGatewayLine, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="语音网关线路不存在")
    if line.owner_user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=404, detail="语音网关线路不存在")
    return line


def _profile_defaults(key: str) -> dict[str, object]:
    return PROFILE_DEFAULTS.get(key, PROFILE_DEFAULTS["sip_volte_gateway"])


def _read_line(line: VoiceGatewayLine) -> dict[str, object]:
    return {
        "id": line.id,
        "ownerUserId": line.owner_user_id,
        "createdByUserId": line.created_by_user_id,
        "lineName": line.line_name,
        "customerName": line.customer_name,
        "status": line.status,
        "gatewayProfileKey": line.gateway_profile_key,
        "gatewayLabel": line.gateway_label,
        "gatewayVendor": line.gateway_vendor,
        "gatewayModel": line.gateway_model,
        "gatewayCategory": line.gateway_category,
        "deploymentMode": line.deployment_mode,
        "sipServerHost": line.sip_server_host,
        "sipServerPort": line.sip_server_port,
        "sipTransport": line.sip_transport,
        "sipUsername": line.sip_username,
        "sipAuthUsername": line.sip_auth_username,
        "sipPasswordSecretAlias": line.sip_password_secret_alias,
        "sipPasswordDisplay": "********",
        "trunkName": line.trunk_name,
        "channelCount": line.channel_count,
        "codecPrimary": line.codec_primary,
        "codecSecondary": line.codec_secondary,
        "dtmfMode": line.dtmf_mode,
        "rtpPortRange": line.rtp_port_range,
        "routeDirection": line.route_direction,
        "deviceAdminUrl": line.device_admin_url,
        "deviceSerial": line.device_serial,
        "deviceMac": line.device_mac,
        "networkNote": line.network_note,
        "registrationStatus": line.registration_status,
        "routeStatus": line.route_status,
        "simStatus": line.sim_status,
        "rtpStatus": line.rtp_status,
        "acceptanceStatus": line.acceptance_status,
        "lastRegisteredAt": line.last_registered_at,
        "lastPreflightAt": line.last_preflight_at,
        "notes": line.notes,
        "configCard": _config_card(line),
        "createdAt": line.created_at,
        "updatedAt": line.updated_at,
    }


def _config_card(line: VoiceGatewayLine) -> dict[str, object]:
    field_mapping = [
        _field("Registrar / SIP Server", line.sip_server_host, "设备后台 SIP 注册页", "填云端公网域名或 IP，不填客户本地 192.168 地址。"),
        _field("Port / Transport", f"{line.sip_server_port}/{line.sip_transport}", "设备后台 SIP 注册页", "协议必须和云端 Asterisk 监听一致。"),
        _field("Account / SIP User", line.sip_username, "设备后台 SIP 注册页", "每个客户独立账号，不能复用测试 trunk。"),
        _field("Auth User", line.sip_auth_username, "设备后台 SIP 注册页", "多数设备可与 SIP User 相同。"),
        _field("Password", "一次性密码 / 受控密钥别名", "设备后台 SIP 注册页", "只在生成或轮换时显示明文。"),
        _field("Codec", f"{line.codec_primary}, {line.codec_secondary}", "设备后台媒体/编码页", "优先 PCMA/alaw，兼容 PCMU/ulaw。"),
        _field("DTMF", line.dtmf_mode, "设备后台媒体/DTMF 页", "用于按键识别和部分运营商线路兼容。"),
        _field("Route", line.route_direction, "设备后台呼叫路由页", "UC100 当前应为 SIP中继/SIP 到 VoLTE。"),
        _field("RTP", line.rtp_port_range, "云端安全组和 Asterisk RTP", "云端必须放行 RTP UDP 端口范围，否则接通后听不到/说不出。"),
    ]
    return {
        "lineId": line.id,
        "customerName": line.customer_name,
        "lineName": line.line_name,
        "gatewayProfileKey": line.gateway_profile_key,
        "gatewayLabel": line.gateway_label,
        "sipServer": line.sip_server_host,
        "sipPort": line.sip_server_port,
        "sipTransport": line.sip_transport,
        "sipUsername": line.sip_username,
        "sipAuthUsername": line.sip_auth_username,
        "sipPasswordSecretAlias": line.sip_password_secret_alias,
        "sipPasswordDisplay": "********",
        "trunkName": line.trunk_name,
        "channelCount": line.channel_count,
        "codecPrimary": line.codec_primary,
        "codecSecondary": line.codec_secondary,
        "dtmfMode": line.dtmf_mode,
        "rtpPortRange": line.rtp_port_range,
        "routeDirection": line.route_direction,
        "fieldMapping": field_mapping,
        "deliverySteps": [
            _step("cloud_trunk", "云端生成 trunk", f"Asterisk endpoint/trunk 使用 {line.trunk_name}", "云端可看到 endpoint 和鉴权账号。"),
            _step("device_sip", "设备 SIP 注册", "按配置卡填写 SIP Server、账号、鉴权和密码。", "Asterisk contacts 显示已注册/可达。"),
            _step("device_route", "设备外呼路由", f"设置 {line.route_direction}。", "设备话单来源为 SIP中继/SIP，目的地为 VoLTE/GSM/SIM。"),
            _step("sim_voice", "SIM/VoLTE 语音", "在设备诊断页确认 SIM 语音正常。", "语音通道注册且不是仅上网正常。"),
            _step("rtp_media", "RTP 媒体", f"云端放行 {line.rtp_port_range}。", "接通后双方有语音帧，实时监听出现事件。"),
            _step("single_call", "单号试拨验收", "从客户前端发起单号试拨。", "手机接听、AI 能说话、能听到客户说话。"),
        ],
    }


def _field(label: str, value: str, target: str, note: str = "") -> dict[str, str]:
    return {"label": label, "value": value, "target": target, "note": note}


def _step(key: str, label: str, detail: str, expected_result: str) -> dict[str, str]:
    return {"key": key, "label": label, "detail": detail, "expectedResult": expected_result}


def _add_event(
    db: Session,
    line: VoiceGatewayLine,
    actor: User,
    *,
    event_type: str,
    status: str,
    summary: str = "",
    detail: str = "",
    evidence_json: str = "",
) -> VoiceGatewayLineEvent:
    event = VoiceGatewayLineEvent(
        line_id=line.id,
        owner_user_id=line.owner_user_id,
        actor_user_id=actor.id,
        event_type=event_type,
        status=status,
        summary=summary,
        detail=detail,
        evidence_json=evidence_json,
    )
    db.add(event)
    return event


def _apply_event_to_line(line: VoiceGatewayLine, payload: VoiceGatewayLineEventCreate) -> None:
    status = payload.status.strip()
    if payload.event_type == "sip_registration":
        line.registration_status = status
        if _is_pass_status(status):
            line.last_registered_at = datetime.utcnow()
    elif payload.event_type == "gateway_route":
        line.route_status = status
    elif payload.event_type == "sim_voice":
        line.sim_status = status
    elif payload.event_type == "rtp_media":
        line.rtp_status = status
    elif payload.event_type in {"single_call", "asr_tts", "live_monitor"}:
        line.acceptance_status = status
    line.last_preflight_at = datetime.utcnow()
    line.status = _line_status(line)
    line.updated_at = datetime.utcnow()


def _line_status(line: VoiceGatewayLine) -> str:
    statuses = [line.registration_status, line.route_status, line.sim_status, line.rtp_status, line.acceptance_status]
    if any(_is_fail_status(value) for value in statuses):
        return "验收失败"
    if _is_pass_status(line.acceptance_status):
        return "验收通过"
    if _is_pass_status(line.registration_status):
        return "交付中"
    return "待配置"


def _is_pass_status(value: str) -> bool:
    return value.lower() in {"pass", "passed", "ok", "ready", "success"} or value in {"通过", "已通过", "正常", "已注册", "可达", "接通", "验收通过"}


def _is_fail_status(value: str) -> bool:
    return value.lower() in {"fail", "failed", "error", "blocked"} or value in {"失败", "故障", "不可用", "未注册", "阻塞"}


def _add_audit(db: Session, actor: User, action: str, resource_id: str, summary: str) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            actor_username=actor.username,
            action=action,
            resource_type="voice_gateway_line",
            resource_id=resource_id,
            summary=summary,
        )
    )


def _generate_sip_password(length: int = 24) -> str:
    return "".join(choice(SECRET_ALPHABET) for _ in range(length))


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").lower()
    return cleaned[:40] or token_hex(4)
