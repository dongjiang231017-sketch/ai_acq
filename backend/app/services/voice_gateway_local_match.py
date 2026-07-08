from __future__ import annotations

import concurrent.futures
import http.client
import json
import os
import re
import shutil
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.delivery import VoiceGatewayDeviceDiscovery, VoiceGatewayLine, VoiceGatewayLineEvent
from app.services.voice_gateway_delivery import (
    PROFILE_CHANNEL_DEFAULTS,
    apply_device_discovery_to_line,
    append_note,
    generate_sip_password,
    reload_asterisk_pjsip,
    resolve_asterisk_dynamic_pjsip_path,
    upsert_asterisk_dynamic_pjsip,
)
from app.services.voice_gateway_profiles import PROFILE_DEFAULTS


LOCAL_BACKEND_ASTERISK_ENV_PATH = Path(__file__).resolve().parents[2] / ".runtime" / "asterisk" / "backend-asterisk.env"
LOCAL_ASTERISK_MANAGER_SNIPPET_PATH = Path(__file__).resolve().parents[2] / ".runtime" / "asterisk" / "manager_ai_acq_local.conf"
LOCAL_SIDECAR_STATE_PATH = Path.home() / ".ai-acq-client" / "asterisk-sidecar" / "state" / "sidecar.json"
DEFAULT_GATEWAY_HTTP_PORT = 80
DEFAULT_GATEWAY_SIP_PORT = 5060
DEFAULT_SCAN_TIMEOUT_SECONDS = 0.6
DEFAULT_SCAN_CONCURRENCY = 64
PASS_REGISTRATION_STATUSES = {"已注册", "已通过", "通过", "正常", "reachable", "registered", "ok"}
DEFAULT_LOCAL_AMI_USERNAME = "ai_acq_local"


@dataclass(frozen=True)
class LocalVoiceGatewayDiscovery:
    host: str
    admin_url: str
    source: str
    profile_key: str
    label: str
    sip_port: int
    max_channels: int


@dataclass(frozen=True)
class LocalVoiceGatewayMatchResult:
    line_id: str
    local_host: str
    gateway_host: str
    gateway_admin_url: str
    runtime_env_path: Path
    manager_conf_path: Path
    sidecar_state_path: Path
    dynamic_pjsip_path: Path
    asterisk_sync_message: str
    warnings: tuple[str, ...]


def backend_runtime_env_path() -> Path:
    explicit = os.getenv("AI_ACQ_BACKEND_ASTERISK_ENV_PATH", "").strip() or os.getenv("BACKEND_ASTERISK_ENV_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return LOCAL_BACKEND_ASTERISK_ENV_PATH


def match_local_voice_gateway_line(
    db: Session,
    line: VoiceGatewayLine,
    *,
    actor_user_id: str | None = None,
) -> LocalVoiceGatewayMatchResult:
    local_host = detect_primary_local_ipv4()
    discovery = discover_local_voice_gateway(preferred_host=_host_from_admin_url(line.device_admin_url), local_host=local_host)
    if discovery is None:
        raise ValueError("当前局域网没有发现可识别的语音网关后台，请确认设备和本机在同一网段，并且设备后台可通过浏览器访问。")

    if not (line.sip_password_plaintext or "").strip():
        password = generate_sip_password()
        line.sip_password_plaintext = password
        line.sip_password_hash = hash_password(password)
    else:
        password = line.sip_password_plaintext.strip()

    if discovery.profile_key:
        line.gateway_profile_key = discovery.profile_key
    profile_defaults = PROFILE_DEFAULTS.get(line.gateway_profile_key, {})
    if discovery.label:
        line.gateway_label = discovery.label
    if profile_defaults:
        if not (line.gateway_vendor or "").strip():
            line.gateway_vendor = str(profile_defaults.get("vendor", "") or "")
        if not (line.gateway_model or "").strip():
            line.gateway_model = str(profile_defaults.get("model", "") or "")
        if not (line.gateway_category or "").strip():
            line.gateway_category = str(profile_defaults.get("category", "") or "")
    if discovery.max_channels:
        line.channel_count = max(int(line.channel_count or 0), int(discovery.max_channels), 1)
    elif not line.channel_count:
        line.channel_count = PROFILE_CHANNEL_DEFAULTS.get(line.gateway_profile_key, 1)

    line.sip_server_host = local_host
    line.sip_server_port = int(line.sip_server_port or DEFAULT_GATEWAY_SIP_PORT)
    line.sip_transport = (line.sip_transport or "UDP").strip() or "UDP"

    record = _upsert_discovery_record(db, line, discovery)
    apply_device_discovery_to_line(line, record, overwrite_device_address=True)
    line.network_note = append_note(line.network_note, f"SQLAdmin 一键匹配本地网关：admin={discovery.admin_url}；local_sip_server={local_host}:{line.sip_server_port}/{line.sip_transport}")
    line.status = "待设备注册" if (line.registration_status or "").strip() not in PASS_REGISTRATION_STATUSES else line.status
    line.updated_at = datetime.utcnow()

    dynamic_pjsip_path = resolve_asterisk_dynamic_pjsip_path()
    sync_message = upsert_asterisk_dynamic_pjsip(
        line,
        password,
        path=dynamic_pjsip_path,
        reload_callback=_safe_asterisk_reload_message,
    )
    runtime_env_path = write_local_backend_runtime_env(line, discovery, local_host=local_host)
    sidecar_state_path = write_local_sidecar_state(
        line,
        discovery,
        local_host=local_host,
        runtime_env_path=runtime_env_path,
    )

    warnings: list[str] = []
    if shutil.which("asterisk") is None:
        warnings.append("本机未检测到 asterisk 命令，已写入本地运行配置，但还不能真实外呼。")
    runtime_values = _parse_env_file(runtime_env_path)
    if not runtime_values.get("ASTERISK_AMI_USERNAME") or not runtime_values.get("ASTERISK_AMI_PASSWORD"):
        warnings.append("本地运行配置里的 AMI 账号/密码仍为空；Asterisk 启动后还要补上 AMI 凭据。")

    db.add(
        VoiceGatewayLineEvent(
            line_id=line.id,
            owner_user_id=line.owner_user_id,
            actor_user_id=actor_user_id,
            event_type="local_gateway_matched",
            status="updated",
            summary="SQLAdmin 一键匹配本地语音网关",
            detail=(
                f"网关后台={discovery.admin_url}；本机 SIP 服务地址={local_host}:{line.sip_server_port}/{line.sip_transport}；"
                f"运行配置={runtime_env_path}"
            ),
        )
    )

    return LocalVoiceGatewayMatchResult(
        line_id=line.id,
        local_host=local_host,
        gateway_host=discovery.host,
        gateway_admin_url=discovery.admin_url,
        runtime_env_path=runtime_env_path,
        manager_conf_path=LOCAL_ASTERISK_MANAGER_SNIPPET_PATH,
        sidecar_state_path=sidecar_state_path,
        dynamic_pjsip_path=dynamic_pjsip_path,
        asterisk_sync_message=sync_message,
        warnings=tuple(warnings),
    )


def discover_local_voice_gateway(
    *,
    preferred_host: str = "",
    local_host: str | None = None,
    timeout_seconds: float = DEFAULT_SCAN_TIMEOUT_SECONDS,
    concurrency: int = DEFAULT_SCAN_CONCURRENCY,
) -> LocalVoiceGatewayDiscovery | None:
    local_host = local_host or detect_primary_local_ipv4()
    candidates = list(_candidate_hosts(local_host, preferred_host=preferred_host))
    if not candidates:
        return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(4, min(concurrency, 96))) as executor:
        future_map = {executor.submit(_probe_host, host, timeout_seconds): host for host in candidates}
        for future in concurrent.futures.as_completed(future_map):
            discovery = future.result()
            if discovery is not None:
                executor.shutdown(wait=False, cancel_futures=True)
                return discovery
    return None


def detect_primary_local_ipv4() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            host = sock.getsockname()[0]
            if host and not host.startswith("127."):
                return host
    except OSError:
        pass

    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        host = info[4][0]
        if host and not host.startswith("127."):
            return host
    raise RuntimeError("无法识别当前机器的局域网 IPv4 地址")


def write_local_backend_runtime_env(
    line: VoiceGatewayLine,
    discovery: LocalVoiceGatewayDiscovery,
    *,
    local_host: str,
    path: Path | None = None,
) -> Path:
    path = backend_runtime_env_path() if path is None else Path(path).expanduser()
    current = _parse_env_file(path)
    ami_username, ami_password = _ensure_local_ami_credentials(current)
    local_net = _normalize_local_net(current.get("AI_ACQ_ASTERISK_LOCAL_NET"), local_host)
    values = {
        "TELEPHONY_GATEWAY_MODE": "asterisk",
        "ASTERISK_DEPLOYMENT_MODE": "desktop",
        "VOICE_GATEWAY_PROFILE": line.gateway_profile_key or "dinstar_8t_server",
        "VOICE_GATEWAY_LABEL": line.gateway_label or discovery.label,
        "VOICE_GATEWAY_VENDOR": line.gateway_vendor or "",
        "VOICE_GATEWAY_MODEL": line.gateway_model or "",
        "VOICE_GATEWAY_CATEGORY": line.gateway_category or "",
        "VOICE_GATEWAY_TRANSPORT": "sip_udp_server_registered" if line.gateway_profile_key == "dinstar_8t_server" else "sip_udp",
        "VOICE_GATEWAY_HOST": discovery.host,
        "VOICE_GATEWAY_SIP_PORT": str(discovery.sip_port or DEFAULT_GATEWAY_SIP_PORT),
        "VOICE_GATEWAY_ADMIN_URL": discovery.admin_url,
        "VOICE_GATEWAY_TRUNK_NAME": line.trunk_name or "",
        "VOICE_GATEWAY_MAX_CHANNELS": str(max(1, int(line.channel_count or 1))),
        "VOICE_GATEWAY_DISCOVERY_MODE": "backend_admin_one_click",
        "ASTERISK_HOST": current.get("ASTERISK_HOST") or "127.0.0.1",
        "ASTERISK_AMI_PORT": current.get("ASTERISK_AMI_PORT") or "5038",
        "ASTERISK_AMI_USERNAME": ami_username,
        "ASTERISK_AMI_PASSWORD": ami_password,
        "ASTERISK_TRUNK_NAME": line.trunk_name or "",
        "ASTERISK_MAX_CHANNELS": str(max(1, int(line.channel_count or 1))),
        "ASTERISK_LIVE_CALL_ENABLED": current.get("ASTERISK_LIVE_CALL_ENABLED") or "false",
        "ASTERISK_BULK_CALL_ENABLED": current.get("ASTERISK_BULK_CALL_ENABLED") or "false",
        "AI_ACQ_ASTERISK_ADVERTISED_HOST": local_host,
        "AI_ACQ_ASTERISK_LOCAL_NET": local_net,
    }

    if current.get("ASTERISK_ORIGINATE_CHANNEL_TEMPLATE"):
        values["ASTERISK_ORIGINATE_CHANNEL_TEMPLATE"] = current["ASTERISK_ORIGINATE_CHANNEL_TEMPLATE"]
    if current.get("ASTERISK_CALLER_ID"):
        values["ASTERISK_CALLER_ID"] = current["ASTERISK_CALLER_ID"]

    lines = [
        "# SQLAdmin 一键匹配本地网关生成，请勿提交到 Git。",
        f"# updated_at={datetime.utcnow().isoformat(timespec='seconds')}Z",
    ]
    for key, value in values.items():
        lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_local_manager_snippet(username=ami_username, password=ami_password)
    return path


def write_local_sidecar_state(
    line: VoiceGatewayLine,
    discovery: LocalVoiceGatewayDiscovery,
    *,
    local_host: str,
    runtime_env_path: Path,
    path: Path | None = None,
) -> Path:
    path = LOCAL_SIDECAR_STATE_PATH if path is None else Path(path).expanduser()
    current = _parse_json_file(path)
    runtime_values = _parse_env_file(runtime_env_path)
    ami_username, ami_password = _ensure_local_ami_credentials(runtime_values)
    audio_socket_host = (runtime_values.get("ASTERISK_AUDIO_SOCKET_HOST") or current.get("audioSocketHost") or "127.0.0.1").strip() or "127.0.0.1"
    audio_socket_port = _safe_int(
        runtime_values.get("ASTERISK_AUDIO_SOCKET_PORT") or current.get("audioSocketPort"),
        fallback=9019,
    )
    ami_port = _safe_int(runtime_values.get("ASTERISK_AMI_PORT") or current.get("amiPort"), fallback=5038)
    sip_listen_port = max(1, int(line.sip_server_port or DEFAULT_GATEWAY_SIP_PORT))
    gateway_sip_port = max(1, int(discovery.sip_port or DEFAULT_GATEWAY_SIP_PORT))
    max_channels = max(1, int(line.channel_count or discovery.max_channels or 1))
    local_net = _normalize_local_net(current.get("asteriskLocalNet"), local_host)

    state = {
        "amiUsername": ami_username,
        "amiPassword": ami_password,
        "amiPort": ami_port,
        "sipPort": sip_listen_port,
        "rtpStart": _safe_int(current.get("rtpStart"), fallback=10000),
        "rtpEnd": _safe_int(current.get("rtpEnd"), fallback=10100),
        "trunkName": line.trunk_name or current.get("trunkName") or "",
        "voiceGatewayProfile": line.gateway_profile_key or discovery.profile_key or current.get("voiceGatewayProfile") or "dinstar_8t_server",
        "voiceGatewayLabel": line.gateway_label or discovery.label or current.get("voiceGatewayLabel") or "鼎信 8T 多卡网关",
        "voiceGatewayHost": discovery.host,
        "voiceGatewayAdminUrl": discovery.admin_url,
        "voiceGatewaySipPort": gateway_sip_port,
        "voiceGatewaySipUsername": line.sip_username or current.get("voiceGatewaySipUsername") or "",
        "voiceGatewaySipPassword": line.sip_password_plaintext or current.get("voiceGatewaySipPassword") or "",
        "asteriskAdvertisedHost": local_host,
        "asteriskLocalNet": local_net,
        "maxChannels": max_channels,
        "audioSocketHost": audio_socket_host,
        "audioSocketPort": audio_socket_port,
        "gatewayDiscoveryEnabled": True,
        "gatewayDiscoveryHttpPort": _safe_int(current.get("gatewayDiscoveryHttpPort"), fallback=DEFAULT_GATEWAY_HTTP_PORT),
        "gatewayDiscoveryTimeoutMs": _safe_int(current.get("gatewayDiscoveryTimeoutMs"), fallback=420),
        "gatewayDiscoveryConcurrency": _safe_int(current.get("gatewayDiscoveryConcurrency"), fallback=48),
        "audioSocketUuid": current.get("audioSocketUuid") or "",
        "createdAt": current.get("createdAt") or datetime.utcnow().isoformat() + "Z",
        "uc100Host": discovery.host,
        "uc100SipPort": gateway_sip_port,
        "uc100SipUsername": line.sip_username or current.get("uc100SipUsername") or "",
        "uc100SipPassword": line.sip_password_plaintext or current.get("uc100SipPassword") or "",
        "voiceGatewayDiscoveredAt": datetime.utcnow().isoformat() + "Z",
        "voiceGatewayDiscoverySource": "backend_admin_one_click",
        "voiceGatewayPreviousHost": current.get("voiceGatewayHost") or "",
        "voiceGatewayPreviousSipPort": _safe_int(current.get("voiceGatewaySipPort"), fallback=gateway_sip_port),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _candidate_hosts(local_host: str, *, preferred_host: str = "") -> Iterable[str]:
    seen: set[str] = set()
    for host in [preferred_host.strip(), *_subnet_hosts(local_host)]:
        if not host or host == local_host or host in seen:
            continue
        seen.add(host)
        yield host


def _subnet_hosts(local_host: str) -> list[str]:
    parts = local_host.split(".")
    if len(parts) != 4:
        return []
    prefix = ".".join(parts[:3])
    return [f"{prefix}.{index}" for index in range(1, 255)]


def _normalize_local_net(value: str | None, host: str) -> str:
    normalized = (value or "").strip()
    derived = _default_local_net(host)
    if not normalized:
        return derived
    if normalized == "172.16.0.0/12" and derived != normalized:
        return derived
    return normalized


def _default_local_net(host: str) -> str:
    parts = host.split(".")
    if len(parts) != 4:
        return "172.16.0.0/12"
    try:
        octets = [int(part) for part in parts]
    except ValueError:
        return "172.16.0.0/12"
    if any(octet < 0 or octet > 255 for octet in octets):
        return "172.16.0.0/12"
    return f"{octets[0]}.{octets[1]}.{octets[2]}.0/24"


def _probe_host(host: str, timeout_seconds: float) -> LocalVoiceGatewayDiscovery | None:
    connection: http.client.HTTPConnection | None = None
    title = ""
    server = ""
    authenticate = ""
    cookies = ""
    body = ""
    status_code = 0
    try:
        connection = http.client.HTTPConnection(host, DEFAULT_GATEWAY_HTTP_PORT, timeout=timeout_seconds)
        connection.request("GET", "/")
        response = connection.getresponse()
        status_code = int(response.status or 0)
        server = str(response.headers.get("server", ""))
        authenticate = str(response.headers.get("www-authenticate", ""))
        raw_cookies = response.headers.get_all("set-cookie", [])
        cookies = "\n".join(raw_cookies)
        payload = response.read(4096)
        body = payload.decode("utf-8", errors="ignore")
        title = _title_from_html(body)
    except OSError:
        return None
    finally:
        try:
            connection.close()
        except Exception:
            pass

    matched, profile_key, label, sip_port, max_channels, source = _classify_http_signature(
        title=title,
        server=server,
        authenticate=authenticate,
        cookies=cookies,
        body=body,
        status_code=status_code,
    )
    if not matched:
        return None

    return LocalVoiceGatewayDiscovery(
        host=host,
        admin_url=f"http://{host}/",
        source=source,
        profile_key=profile_key,
        label=label,
        sip_port=sip_port,
        max_channels=max_channels,
    )


def _classify_http_signature(
    *,
    title: str,
    server: str,
    authenticate: str,
    cookies: str,
    body: str,
    status_code: int,
) -> tuple[bool, str, str, int, int, str]:
    text = "\n".join(part for part in [title, server, authenticate, cookies, body] if part)
    if re.search(r"UC100|UC100-ZYH", text, flags=re.IGNORECASE):
        return True, "uc100_sip_volte", "语音网关（UC100 测试档案）", 5080, 1, f"http:{title or 'uc100'}"
    if re.search(r"Dinstar|DINSTAR|鼎信|DWG|UC2000|MTG|GSM Gateway|VoLTE", text, flags=re.IGNORECASE):
        return True, "dinstar_8t_server", "鼎信 8T 多卡网关", 5060, 8, f"http:{title or 'voice-gateway'}"
    looks_like_dinstar_digest = (
        status_code == 401
        and re.search(r"Web Server/2\.1\.0", server, flags=re.IGNORECASE)
        and re.search(r'Digest\s+realm="?Web Server"?', authenticate, flags=re.IGNORECASE)
    )
    if looks_like_dinstar_digest:
        return True, "dinstar_8t_server", "鼎信 8T 多卡网关", 5060, 8, "http:dinstar-digest-web-server"
    return False, "", "", 0, 0, ""


def _title_from_html(html: str) -> str:
    match = re.search(r"<title[^>]*>([^<]+)</title>", html, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _upsert_discovery_record(
    db: Session,
    line: VoiceGatewayLine,
    discovery: LocalVoiceGatewayDiscovery,
) -> VoiceGatewayDeviceDiscovery:
    record = db.scalar(
        select(VoiceGatewayDeviceDiscovery)
        .where(
            VoiceGatewayDeviceDiscovery.owner_user_id == line.owner_user_id,
            VoiceGatewayDeviceDiscovery.matched_line_id == line.id,
        )
        .order_by(VoiceGatewayDeviceDiscovery.updated_at.desc(), VoiceGatewayDeviceDiscovery.created_at.desc())
    )
    if record is None:
        record = VoiceGatewayDeviceDiscovery(owner_user_id=line.owner_user_id, matched_line_id=line.id)
        db.add(record)
    record.status = "matched"
    record.source = "sqladmin_local_gateway_match"
    record.gateway_profile_key = discovery.profile_key
    record.gateway_label = discovery.label
    record.device_admin_url = discovery.admin_url
    record.device_ip = discovery.host
    record.sip_port = discovery.sip_port
    record.summary = "SQLAdmin 一键匹配本地语音网关"
    record.detail = f"source={discovery.source}；admin={discovery.admin_url}；ip={discovery.host}"
    record.updated_at = datetime.utcnow()
    return record


def _host_from_admin_url(admin_url: str | None) -> str:
    match = re.match(r"^https?://([^/:]+)", (admin_url or "").strip(), flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _safe_asterisk_reload_message() -> str:
    if shutil.which("asterisk") is None:
        return "已写入本地 PJSIP 配置文件；本机尚未检测到 asterisk 命令。"
    try:
        return reload_asterisk_pjsip()
    except Exception as exc:  # pragma: no cover - depends on local runtime state
        return f"已写入本地 PJSIP 配置文件，但自动重载 Asterisk 失败：{exc}"


def _ensure_local_ami_credentials(current: dict[str, str]) -> tuple[str, str]:
    username = (current.get("ASTERISK_AMI_USERNAME") or "").strip() or DEFAULT_LOCAL_AMI_USERNAME
    password = (current.get("ASTERISK_AMI_PASSWORD") or "").strip() or generate_sip_password(20)
    return username, password


def _write_local_manager_snippet(*, username: str, password: str) -> None:
    lines = [
        "; SQLAdmin 一键匹配本地网关自动生成。",
        "; 如果你本机有 Asterisk，请把这段 include 到 manager.conf 或 manager.d 目录。",
        f"; updated_at={datetime.utcnow().isoformat(timespec='seconds')}Z",
        f"[{username}]",
        "secret = " + password,
        "read = all",
        "write = all",
        "writetimeout = 5000",
        "displayconnects = yes",
        "permit = 127.0.0.1/255.255.255.255",
    ]
    LOCAL_ASTERISK_MANAGER_SNIPPET_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_ASTERISK_MANAGER_SNIPPET_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def _parse_json_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _safe_int(value: object, *, fallback: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback
