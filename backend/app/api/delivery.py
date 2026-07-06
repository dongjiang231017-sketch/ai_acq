from __future__ import annotations

import re
from datetime import datetime
from secrets import token_hex
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.security import hash_password
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.delivery import VoiceGatewayDeviceDiscovery, VoiceGatewayLine, VoiceGatewayLineEvent
from app.models.user import User
from app.schemas.delivery import (
    VoiceGatewayBulkLineCreate,
    VoiceGatewayBulkLineCreated,
    VoiceGatewayConfigCard,
    VoiceGatewayCredentialRotation,
    VoiceGatewayDeviceDiscoveryCreate,
    VoiceGatewayDeviceDiscoveryRead,
    VoiceGatewayDeviceDiscoveryUpdate,
    VoiceGatewayLineCreate,
    VoiceGatewayLineCreated,
    VoiceGatewayLineEventCreate,
    VoiceGatewayLineEventRead,
    VoiceGatewayLineRead,
    VoiceGatewayLineRedelivery,
    VoiceGatewayLineRedeliveryRequest,
    VoiceGatewayLineUpdate,
)
from app.services.voice_gateway_delivery import (
    INACTIVE_LINE_STATUSES,
    ONE_TIME_WARNING,
    VoiceGatewayRedeliveryError,
    find_assigned_line_for_device,
    find_redelivery_discovery_for_line,
    generate_sip_password,
    redeliver_voice_gateway_line,
)
from app.services.voice_gateway_profiles import PROFILE_DEFAULTS

router = APIRouter()

DEFAULT_SIP_SERVER_HOST = "101.132.63.159"
DEFAULT_CODEC_PRIMARY = "PCMA/alaw"
DEFAULT_CODEC_SECONDARY = "PCMU/ulaw"
DEFAULT_DTMF_MODE = "RFC2833/RFC4733"
DEFAULT_RTP_RANGE = "10000-20000/UDP"
DEFAULT_ROUTE_DIRECTION = "SIP中继/SIP -> VoLTE/GSM/SIM"
PROFILE_CHANNEL_DEFAULTS = {
    "dinstar_8t_server": 8,
    "multi_sim_lte_gateway": 8,
    "uc100_sip_volte": 1,
    "sip_volte_gateway": 1,
    "sip_trunk": 1,
}
AUTO_BIND_LINE_STATUSES = {"", "待配置", "待设备发现", "设备未发现", "待设备注册", "待下发"}


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
        statement = statement.where(
            VoiceGatewayLine.owner_user_id == current_user.id,
            VoiceGatewayLine.status.notin_(INACTIVE_LINE_STATUSES),
        )
    lines = db.scalars(statement.order_by(VoiceGatewayLine.created_at.desc())).all()
    return [_read_line(line) for line in lines]


@router.get("/voice-gateway-device-discoveries", response_model=list[VoiceGatewayDeviceDiscoveryRead])
def list_voice_gateway_device_discoveries(
    include_all: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[VoiceGatewayDeviceDiscovery]:
    statement = select(VoiceGatewayDeviceDiscovery)
    if not (include_all and current_user.is_superuser):
        statement = statement.where(VoiceGatewayDeviceDiscovery.owner_user_id == current_user.id)
    return list(
        db.scalars(
            statement.order_by(VoiceGatewayDeviceDiscovery.updated_at.desc(), VoiceGatewayDeviceDiscovery.created_at.desc())
        ).all()
    )


@router.post(
    "/voice-gateway-device-discoveries",
    response_model=VoiceGatewayDeviceDiscoveryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_voice_gateway_device_discovery(
    payload: VoiceGatewayDeviceDiscoveryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VoiceGatewayDeviceDiscovery:
    discovery = _record_device_discovery(db, current_user.id, current_user, payload, matched_line_id=None)
    line, created_line = _auto_bind_device_discovery(db, current_user, current_user, discovery)
    if discovery.status == "待转移":
        audit_summary = "发现已被其他账号占用的语音网关，等待后台重新交付/转移"
    else:
        audit_summary = "自动生成语音网关线路并匹配设备" if line and created_line else "记录待匹配语音网关设备"
    _add_audit(
        db,
        current_user,
        "voice_gateway_device_discovery.create",
        discovery.id,
        f"{audit_summary}：{discovery.device_admin_url or discovery.device_ip or discovery.gateway_label}",
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="自动生成客户语音网关配置卡失败：线路名称、SIP账号或 trunk 名称已存在") from exc
    db.refresh(discovery)
    return discovery


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
    line, password = _build_line(payload, owner, current_user)
    discovery = _latest_unmatched_device_discovery(db, owner.id)
    if discovery is not None:
        _apply_device_discovery_to_line(line, discovery)
    db.add(line)
    db.flush()
    if discovery is not None:
        discovery.matched_line_id = line.id
        discovery.status = "matched"
        discovery.updated_at = datetime.utcnow()
    _add_event(
        db,
        line,
        current_user,
        event_type="note",
        status="created",
        summary="生成客户语音网关配置卡",
        detail=f"{line.gateway_label} / {line.sip_server_host}:{line.sip_server_port}/{line.sip_transport}",
    )
    if discovery is not None:
        _add_event(
            db,
            line,
            current_user,
            event_type="device_discovery",
            status="matched",
            summary="自动匹配客户客户端发现的语音网关",
            detail=_device_discovery_note_from_record(discovery),
            evidence_json=discovery.evidence_json,
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


@router.post(
    "/voice-gateway-lines/bulk-provision",
    response_model=VoiceGatewayBulkLineCreated,
    status_code=status.HTTP_201_CREATED,
)
def bulk_provision_voice_gateway_lines(
    payload: VoiceGatewayBulkLineCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    created: list[dict[str, object]] = []
    lines: list[tuple[VoiceGatewayLine, str]] = []
    for item in payload.items:
        owner = _resolve_owner(item.owner_user_id, db, current_user)
        line, password = _build_line(item, owner, current_user)
        discovery = _latest_unmatched_device_discovery(db, owner.id)
        if discovery is not None:
            _apply_device_discovery_to_line(line, discovery)
        db.add(line)
        db.flush()
        if discovery is not None:
            discovery.matched_line_id = line.id
            discovery.status = "matched"
            discovery.updated_at = datetime.utcnow()
        _add_event(
            db,
            line,
            current_user,
            event_type="note",
            status="created",
            summary="批量预生成客户语音网关配置卡",
            detail=f"{line.gateway_label} / {line.sip_server_host}:{line.sip_server_port}/{line.sip_transport}",
        )
        if discovery is not None:
            _add_event(
                db,
                line,
                current_user,
                event_type="device_discovery",
                status="matched",
                summary="自动匹配客户客户端发现的语音网关",
                detail=_device_discovery_note_from_record(discovery),
                evidence_json=discovery.evidence_json,
            )
        _add_audit(db, current_user, "voice_gateway_line.bulk_create", line.id, f"预生成语音网关线路：{line.line_name}")
        lines.append((line, password))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="批量预生成失败：客户线路名称、SIP账号或 trunk 名称与已有数据冲突") from exc
    for line, password in lines:
        db.refresh(line)
        data = _read_line(line)
        data["sipPasswordOneTime"] = password
        data["oneTimeWarning"] = ONE_TIME_WARNING
        created.append(data)
    return {"count": len(created), "created": created, "oneTimeWarning": ONE_TIME_WARNING}


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


@router.post("/voice-gateway-lines/{line_id}/device-discovery", response_model=VoiceGatewayLineRead)
def report_voice_gateway_device_discovery(
    line_id: str,
    payload: VoiceGatewayDeviceDiscoveryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    line = _get_line(line_id, db, current_user)
    admin_url = _normalise_device_admin_url(payload.device_admin_url, payload.device_ip)
    if admin_url:
        line.device_admin_url = admin_url
    if payload.device_mac:
        line.device_mac = payload.device_mac.strip()
    if payload.device_serial:
        line.device_serial = payload.device_serial.strip()
    discovery_note = _device_discovery_note(payload, admin_url)
    if discovery_note:
        line.network_note = _append_note(line.network_note, discovery_note)
    has_device_identity = _payload_has_device_identity(payload, admin_url)
    if _is_fail_status(payload.status) and not has_device_identity:
        line.status = "设备未发现"
    elif has_device_identity or _is_pass_status(payload.status) or payload.status in {"found", "current", "updated", "已发现", "已绑定"}:
        line.status = "待设备注册" if not _is_pass_status(line.registration_status) else _line_status(line)
    _record_device_discovery(db, line.owner_user_id, current_user, payload, matched_line_id=line.id)
    line.updated_at = datetime.utcnow()
    event = _add_event(
        db,
        line,
        current_user,
        event_type="device_discovery",
        status=payload.status,
        summary=payload.summary or ("已记录现场设备后台地址" if admin_url else "记录现场设备发现结果"),
        detail=payload.detail or discovery_note,
        evidence_json=payload.evidence_json,
    )
    _add_audit(db, current_user, "voice_gateway_line.device_discovery", line.id, f"记录设备发现结果：{line.line_name}")
    db.commit()
    db.refresh(event)
    db.refresh(line)
    return _read_line(line)


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


@router.post("/voice-gateway-lines/{line_id}/redeliver", response_model=VoiceGatewayLineRedelivery)
def redeliver_voice_gateway_line_to_customer(
    line_id: str,
    payload: VoiceGatewayLineRedeliveryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="只有超级用户可以重新交付/转移语音网关设备")
    line = _get_line(line_id, db, current_user)
    discovery = _resolve_redelivery_discovery(payload, line, db)
    target_owner_id = payload.target_owner_user_id or discovery.owner_user_id
    target_owner = db.get(User, target_owner_id)
    if target_owner is None:
        raise HTTPException(status_code=404, detail="目标客户账号不存在")
    try:
        result = redeliver_voice_gateway_line(
            db,
            line,
            discovery,
            target_owner,
            actor_user_id=current_user.id,
            sync_asterisk=payload.sync_asterisk,
        )
        _add_audit(
            db,
            current_user,
            "voice_gateway_line.redeliver",
            line.id,
            f"重新交付语音网关：{result.previous_customer_name or result.previous_owner_user_id} -> {line.customer_name}",
        )
        db.commit()
    except VoiceGatewayRedeliveryError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="重新交付失败：新客户线路名称、SIP账号或 trunk 与已有数据冲突") from exc
    db.refresh(line)
    db.refresh(discovery)
    return {
        "line": _read_line(line),
        "discovery": discovery,
        "previousOwnerUserId": result.previous_owner_user_id,
        "previousCustomerName": result.previous_customer_name,
        "previousSipUsername": result.previous_sip_username,
        "previousTrunkName": result.previous_trunk_name,
        "sipPasswordOneTime": result.sip_password_one_time,
        "oneTimeWarning": ONE_TIME_WARNING,
        "asteriskSyncMessage": result.asterisk_sync_message,
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


def _resolve_redelivery_discovery(
    payload: VoiceGatewayLineRedeliveryRequest,
    line: VoiceGatewayLine,
    db: Session,
) -> VoiceGatewayDeviceDiscovery:
    discovery: VoiceGatewayDeviceDiscovery | None = None
    if payload.discovery_id:
        discovery = db.get(VoiceGatewayDeviceDiscovery, payload.discovery_id)
    else:
        discovery = find_redelivery_discovery_for_line(
            db,
            line,
            target_owner_user_id=payload.target_owner_user_id,
        )
    if discovery is None:
        raise HTTPException(
            status_code=409,
            detail="没有找到可用于重新交付的客户设备发现记录：请让目标客户登录客户端并重新扫描现场语音网关。",
        )
    return discovery


def _profile_defaults(key: str) -> dict[str, object]:
    return PROFILE_DEFAULTS.get(key, PROFILE_DEFAULTS["sip_volte_gateway"])


def _build_line(payload: VoiceGatewayLineCreate, owner: User, current_user: User) -> tuple[VoiceGatewayLine, str]:
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
    return line, password


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
    device_admin_value = line.device_admin_url or "现场客户端自动发现后回写；也可查路由器 DHCP、设备屏幕或默认地址"
    field_mapping = [
        _field(
            "设备后台地址",
            device_admin_value,
            "交付电脑浏览器 / 客户现场局域网",
            "这是客户本地管理地址，通常是 192.168.x.x；云端不能直接访问，只能由现场客户端或交付人员发现后记录。",
        ),
        _field("Registrar / SIP Server", line.sip_server_host, "设备后台 SIP 注册页", "填云端公网域名或 IP，不填客户本地 192.168 地址。"),
        _field("Port / Transport", f"{line.sip_server_port}/{line.sip_transport}", "设备后台 SIP 注册页", "协议必须和云端 Asterisk 监听一致。"),
        _field("Account / SIP User", line.sip_username, "设备后台 SIP 注册页", "每个客户独立账号，不能复用测试 trunk。"),
        _field("Auth User", line.sip_auth_username, "设备后台 SIP 注册页", "多数设备可与 SIP User 相同。"),
        _field("Password", "一次性密码 / 受控密钥别名", "设备后台 SIP 注册页", "只在生成或轮换时显示明文。"),
        _field("Codec", f"{line.codec_primary}, {line.codec_secondary}", "设备后台媒体/编码页", "优先 PCMA/alaw，兼容 PCMU/ulaw。"),
        _field("DTMF", line.dtmf_mode, "设备后台媒体/DTMF 页", "用于按键识别和部分运营商线路兼容。"),
        _field("Route", line.route_direction, "设备后台呼叫路由页", "外呼方向应为 SIP 中继/云端 trunk 到 VoLTE/GSM/SIM 通道。"),
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
            _step(
                "device_discovery",
                "发现设备后台",
                "交付电脑和语音网关接同一局域网；客户端自动扫描 HTTP/80、常见网关指纹和 SIP 端口。未发现时查路由器 DHCP 列表、设备屏幕、设备标签或说明书默认地址。",
                "线路记录里出现当前设备后台地址、MAC 或序列号。",
            ),
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


def _normalise_device_admin_url(admin_url: str | None, device_ip: str | None) -> str:
    value = (admin_url or "").strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        value = f"http://{value}"
    value = _strip_sip_port_from_admin_url(value)
    return value.rstrip("/") + "/"


def _strip_sip_port_from_admin_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    try:
        port = parsed.port
    except ValueError:
        return value
    if port not in {5060, 5080, 15060} or not parsed.hostname:
        return value
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme or 'http'}://{host}{parsed.path or ''}"


def _latest_unmatched_device_discovery(db: Session, owner_user_id: str) -> VoiceGatewayDeviceDiscovery | None:
    return db.scalar(
        select(VoiceGatewayDeviceDiscovery)
        .where(
            VoiceGatewayDeviceDiscovery.owner_user_id == owner_user_id,
            VoiceGatewayDeviceDiscovery.matched_line_id.is_(None),
        )
        .order_by(VoiceGatewayDeviceDiscovery.updated_at.desc(), VoiceGatewayDeviceDiscovery.created_at.desc())
    )


def _auto_bind_device_discovery(
    db: Session,
    owner: User,
    actor: User,
    discovery: VoiceGatewayDeviceDiscovery,
) -> tuple[VoiceGatewayLine | None, bool]:
    if not _device_discovery_can_bind(discovery):
        return None, False

    assigned_line = find_assigned_line_for_device(db, discovery, exclude_owner_user_id=owner.id)
    if assigned_line is not None:
        discovery.status = "待转移"
        discovery.summary = discovery.summary or "发现同一台语音网关已绑定其他客户/测试账号，等待后台重新交付/转移"
        discovery.updated_at = datetime.utcnow()
        return None, False

    line = _matching_line_for_device_discovery(db, owner.id, discovery)
    created_line = False
    if line is None:
        payload = _line_payload_from_discovery(db, owner, discovery)
        line, _password = _build_line(payload, owner, actor)
        db.add(line)
        db.flush()
        created_line = True
        _add_event(
            db,
            line,
            actor,
            event_type="note",
            status="created",
            summary="客户客户端发现设备后自动生成语音网关配置卡",
            detail=f"{line.gateway_label} / {line.sip_server_host}:{line.sip_server_port}/{line.sip_transport}",
        )

    _apply_device_discovery_to_line(line, discovery, overwrite_device_address=True)
    discovery.matched_line_id = line.id
    discovery.status = "matched"
    discovery.updated_at = datetime.utcnow()
    line.updated_at = datetime.utcnow()
    _add_event(
        db,
        line,
        actor,
        event_type="device_discovery",
        status="matched",
        summary="自动匹配客户客户端发现的语音网关",
        detail=_device_discovery_note_from_record(discovery),
        evidence_json=discovery.evidence_json,
    )
    return line, created_line


def _device_discovery_can_bind(discovery: VoiceGatewayDeviceDiscovery) -> bool:
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


def _matching_line_for_device_discovery(
    db: Session,
    owner_user_id: str,
    discovery: VoiceGatewayDeviceDiscovery,
) -> VoiceGatewayLine | None:
    lines = list(
        db.scalars(
            select(VoiceGatewayLine)
            .where(VoiceGatewayLine.owner_user_id == owner_user_id)
            .order_by(VoiceGatewayLine.updated_at.desc(), VoiceGatewayLine.created_at.desc())
        ).all()
    )
    if not lines:
        return None

    discovery_mac = _normalise_mac(discovery.device_mac)
    if discovery_mac:
        for line in lines:
            if _normalise_mac(line.device_mac) == discovery_mac:
                return line

    discovery_serial = (discovery.device_serial or "").strip().lower()
    if discovery_serial:
        for line in lines:
            if (line.device_serial or "").strip().lower() == discovery_serial:
                return line

    discovery_host = discovery.device_ip or _ip_from_admin_url(discovery.device_admin_url)
    if discovery_host:
        for line in lines:
            if _ip_from_admin_url(line.device_admin_url) == discovery_host:
                return line

    for line in lines:
        if line.status in AUTO_BIND_LINE_STATUSES and not (line.device_admin_url or line.device_mac or line.device_serial):
            return line

    return lines[0] if len(lines) == 1 else None


def _line_payload_from_discovery(
    db: Session,
    owner: User,
    discovery: VoiceGatewayDeviceDiscovery,
) -> VoiceGatewayLineCreate:
    profile_key = discovery.gateway_profile_key if discovery.gateway_profile_key in PROFILE_DEFAULTS else "dinstar_8t_server"
    profile = _profile_defaults(profile_key)
    customer_name = (owner.display_name or owner.username or owner.id).strip()
    line_name = _unique_line_name(db, owner.id, f"{customer_name or '客户'} 语音网关 {datetime.utcnow().strftime('%m%d-%H%M')}")
    return VoiceGatewayLineCreate.model_validate(
        {
            "lineName": line_name,
            "ownerUserId": owner.id,
            "customerName": customer_name,
            "gatewayProfileKey": profile_key,
            "gatewayLabel": discovery.gateway_label or str(profile["label"]),
            "gatewayVendor": str(profile["vendor"]),
            "gatewayModel": str(profile["model"]),
            "gatewayCategory": str(profile["category"]),
            "sipServerHost": DEFAULT_SIP_SERVER_HOST,
            "sipServerPort": 5060,
            "sipTransport": "UDP",
            "channelCount": PROFILE_CHANNEL_DEFAULTS.get(profile_key, 1),
            "deviceAdminUrl": discovery.device_admin_url or None,
            "deviceSerial": discovery.device_serial or None,
            "deviceMac": discovery.device_mac or None,
            "networkNote": _device_discovery_note_from_record(discovery),
            "notes": "客户客户端发现现场语音网关后自动生成；SIP 明文密码需通过凭据轮换/一次性配置卡流程获取。",
        }
    )


def _unique_line_name(db: Session, owner_user_id: str, base_name: str) -> str:
    base = base_name.strip()[:104] or "客户语音网关"
    for index in range(20):
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


def _record_device_discovery(
    db: Session,
    owner_user_id: str,
    actor: User,
    payload: VoiceGatewayDeviceDiscoveryUpdate,
    *,
    matched_line_id: str | None,
) -> VoiceGatewayDeviceDiscovery:
    admin_url = _normalise_device_admin_url(payload.device_admin_url, payload.device_ip)
    device_ip = (payload.device_ip or _ip_from_admin_url(admin_url)).strip()
    statement = select(VoiceGatewayDeviceDiscovery).where(
        VoiceGatewayDeviceDiscovery.owner_user_id == owner_user_id,
        VoiceGatewayDeviceDiscovery.matched_line_id.is_(None) if matched_line_id is None else VoiceGatewayDeviceDiscovery.matched_line_id == matched_line_id,
    )
    if admin_url:
        statement = statement.where(VoiceGatewayDeviceDiscovery.device_admin_url == admin_url)
    elif device_ip:
        statement = statement.where(VoiceGatewayDeviceDiscovery.device_ip == device_ip)
    discovery = db.scalar(statement.order_by(VoiceGatewayDeviceDiscovery.updated_at.desc()))
    if discovery is None:
        discovery = VoiceGatewayDeviceDiscovery(owner_user_id=owner_user_id)
        db.add(discovery)
    discovery.reporter_user_id = actor.id
    discovery.matched_line_id = matched_line_id
    discovery.status = (payload.status or "found").strip()
    discovery.source = (payload.source or "desktop_client_discovery").strip()
    discovery.gateway_profile_key = (getattr(payload, "gateway_profile_key", None) or "").strip()
    discovery.gateway_label = (getattr(payload, "gateway_label", None) or "").strip()
    discovery.device_admin_url = admin_url
    discovery.device_ip = device_ip
    discovery.device_mac = (payload.device_mac or "").strip()
    discovery.device_serial = (payload.device_serial or "").strip()
    discovery.sip_port = int(getattr(payload, "sip_port", None) or 0)
    discovery.summary = (payload.summary or "").strip()
    discovery.detail = (payload.detail or "").strip()
    discovery.evidence_json = payload.evidence_json or ""
    discovery.updated_at = datetime.utcnow()
    return discovery


def _apply_device_discovery_to_line(
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
    note = _device_discovery_note_from_record(discovery)
    if note:
        line.network_note = _append_note(line.network_note, note)
    if line.status in AUTO_BIND_LINE_STATUSES:
        line.status = "待设备注册"


def _device_discovery_note_from_record(discovery: VoiceGatewayDeviceDiscovery) -> str:
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


def _ip_from_admin_url(admin_url: str) -> str:
    if not admin_url:
        return ""
    match = re.match(r"^https?://([^/:]+)", admin_url, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _normalise_mac(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", (value or "").lower())


def _device_discovery_note(payload: VoiceGatewayDeviceDiscoveryUpdate, admin_url: str) -> str:
    parts = [f"source={payload.source}", f"status={payload.status}"]
    if admin_url:
        parts.append(f"admin={admin_url}")
    if payload.device_ip:
        parts.append(f"ip={payload.device_ip.strip()}")
    if payload.device_mac:
        parts.append(f"mac={payload.device_mac.strip()}")
    if payload.device_serial:
        parts.append(f"serial={payload.device_serial.strip()}")
    if payload.summary:
        parts.append(payload.summary.strip())
    return "；".join(part for part in parts if part)


def _payload_has_device_identity(payload: VoiceGatewayDeviceDiscoveryUpdate, admin_url: str) -> bool:
    return bool(
        admin_url
        or (payload.device_ip or "").strip()
        or (payload.device_mac or "").strip()
        or (payload.device_serial or "").strip()
    )


def _append_note(current: str, note: str) -> str:
    if not note:
        return current
    line = f"{datetime.utcnow().isoformat(timespec='seconds')} {note}"
    return f"{current.strip()}\n{line}".strip() if current else line


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
    return generate_sip_password(length)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").lower()
    return cleaned[:40] or token_hex(4)
