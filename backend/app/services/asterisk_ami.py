import json
import socket
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from app.core.config import settings


class AsteriskAmiError(RuntimeError):
    pass


@dataclass(frozen=True)
class AmiResponse:
    response: str
    message: str
    fields: dict[str, str | list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.response.lower() in {"success", "follows", "pong"}

    def field_text(self, key: str) -> str:
        value = self.fields.get(key, "")
        if isinstance(value, list):
            return "\n".join(value)
        return str(value)


@dataclass(frozen=True)
class AsteriskHealth:
    checked_at: datetime
    gateway_mode: str
    configured: bool
    live_call_enabled: bool
    bulk_call_enabled: bool
    ami_reachable: bool
    authenticated: bool
    ping_ok: bool
    trunk_configured: bool
    trunk_reachable: bool | None
    trunk_status: str
    max_channels: int
    errors: list[str]

    @property
    def ready_for_test_call(self) -> bool:
        return self.configured and self.authenticated and self.ping_ok and self.trunk_configured and self.trunk_reachable is not False

    def as_dict(self) -> dict[str, object]:
        return {
            "checkedAt": self.checked_at,
            "gatewayMode": self.gateway_mode,
            "configured": self.configured,
            "liveCallEnabled": self.live_call_enabled,
            "bulkCallEnabled": self.bulk_call_enabled,
            "amiReachable": self.ami_reachable,
            "authenticated": self.authenticated,
            "pingOk": self.ping_ok,
            "trunkConfigured": self.trunk_configured,
            "trunkReachable": self.trunk_reachable,
            "trunkStatus": self.trunk_status,
            "maxChannels": self.max_channels,
            "readyForTestCall": self.ready_for_test_call,
            "errors": self.errors,
        }


@dataclass(frozen=True)
class AsteriskOriginateResult:
    accepted: bool
    action_id: str
    channel: str
    status: str
    message: str
    raw_payload: str


def _append_field(fields: dict[str, str | list[str]], key: str, value: str) -> None:
    existing = fields.get(key)
    if existing is None:
        fields[key] = value
    elif isinstance(existing, list):
        existing.append(value)
    else:
        fields[key] = [existing, value]


def parse_ami_message(raw: str) -> AmiResponse:
    fields: dict[str, str | list[str]] = {}
    for line in raw.replace("\r\n", "\n").split("\n"):
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        _append_field(fields, key.strip(), value.strip())
    return AmiResponse(
        response=str(fields.get("Response", "")),
        message=str(fields.get("Message", "")),
        fields=fields,
    )


class AsteriskAmiClient:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.host = host or settings.asterisk_host
        self.port = port or settings.asterisk_ami_port
        self.username = username if username is not None else settings.asterisk_ami_username
        self.password = password if password is not None else settings.asterisk_ami_password
        self.timeout_seconds = timeout_seconds or settings.asterisk_ami_timeout_seconds
        self._socket: socket.socket | None = None

    def __enter__(self) -> "AsteriskAmiClient":
        self.connect()
        self.login()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def connect(self) -> None:
        try:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout_seconds)
            self._socket.settimeout(self.timeout_seconds)
            self._read_banner()
        except OSError as exc:
            raise AsteriskAmiError(f"无法连接 Asterisk AMI：{self.host}:{self.port}") from exc

    def close(self) -> None:
        if self._socket is None:
            return
        try:
            self.send_action({"Action": "Logoff"})
        except AsteriskAmiError:
            pass
        try:
            self._socket.close()
        finally:
            self._socket = None

    def login(self) -> None:
        if not self.username or not self.password:
            raise AsteriskAmiError("Asterisk AMI 账号或密码未配置")
        response = self.send_action(
            {
                "Action": "Login",
                "Username": self.username,
                "Secret": self.password,
                "Events": "off",
            }
        )
        if not response.ok:
            raise AsteriskAmiError(response.message or "Asterisk AMI 登录失败")

    def ping(self) -> AmiResponse:
        return self.send_action({"Action": "Ping"})

    def command(self, command: str) -> AmiResponse:
        return self.send_action({"Action": "Command", "Command": command})

    def originate(self, phone: str, caller_id: str | None = None, variables: dict[str, str] | None = None) -> AsteriskOriginateResult:
        action_id = f"ai-acq-{uuid4().hex}"
        channel = render_originate_channel(phone)
        payload = {
            "Action": "Originate",
            "ActionID": action_id,
            "Channel": channel,
            "Context": settings.asterisk_originate_context,
            "Exten": settings.asterisk_originate_extension,
            "Priority": "1",
            "CallerID": caller_id or settings.asterisk_caller_id,
            "Timeout": str(settings.asterisk_originate_timeout_ms),
            "Async": "true",
        }
        if variables:
            payload["Variable"] = "|".join(f"{key}={value}" for key, value in variables.items())
        response = self.send_action(payload)
        accepted = response.ok
        return AsteriskOriginateResult(
            accepted=accepted,
            action_id=action_id,
            channel=channel,
            status="dialing" if accepted else "failed",
            message=response.message or ("已提交拨号请求" if accepted else "拨号请求失败"),
            raw_payload=json.dumps(
                {
                    "provider": "asterisk",
                    "actionId": action_id,
                    "channel": channel,
                    "response": response.response,
                    "message": response.message,
                },
                ensure_ascii=False,
            ),
        )

    def send_action(self, fields: dict[str, str]) -> AmiResponse:
        if self._socket is None:
            raise AsteriskAmiError("Asterisk AMI 尚未连接")
        lines = [f"{key}: {value}" for key, value in fields.items()]
        payload = "\r\n".join(lines) + "\r\n\r\n"
        try:
            self._socket.sendall(payload.encode("utf-8"))
            return parse_ami_message(self._read_message())
        except OSError as exc:
            raise AsteriskAmiError("Asterisk AMI 通信失败") from exc

    def _read_banner(self) -> None:
        if self._socket is None:
            raise AsteriskAmiError("Asterisk AMI 尚未连接")
        try:
            self._socket.recv(4096)
        except TimeoutError:
            return

    def _read_message(self) -> str:
        if self._socket is None:
            raise AsteriskAmiError("Asterisk AMI 尚未连接")
        chunks: list[bytes] = []
        while True:
            try:
                chunk = self._socket.recv(4096)
            except TimeoutError:
                if chunks:
                    break
                raise
            if not chunk:
                break
            chunks.append(chunk)
            data = b"".join(chunks)
            if b"\r\n\r\n" in data or b"\n\n" in data:
                break
        return b"".join(chunks).decode("utf-8", errors="replace")


def render_originate_channel(phone: str) -> str:
    return settings.asterisk_originate_channel_template.format(
        phone=phone,
        trunk=settings.asterisk_trunk_name,
    )


def _trunk_status_from_output(output: str) -> tuple[bool | None, str]:
    text = output.strip()
    if not text:
        return None, "未返回 trunk 状态"
    lower = text.lower()
    if any(marker in lower for marker in ["not found", "unable to find", "not a known", "no such"]):
        return False, "trunk 未找到"
    if any(marker in lower for marker in ["unreachable", "unavailable", "rejected", "failed"]):
        return False, "trunk 未注册或不可达"
    if any(marker in lower for marker in ["reachable", "available", "ok", "in use", "not in use", "registered", "contact:"]):
        return True, "trunk 已注册或可达"
    return None, "已连接 AMI，但无法自动判断 trunk 状态"


def check_asterisk_health() -> AsteriskHealth:
    errors: list[str] = []
    configured = bool(settings.asterisk_ami_username and settings.asterisk_ami_password)
    trunk_configured = bool(settings.asterisk_trunk_name)
    health = {
        "checked_at": datetime.utcnow(),
        "gateway_mode": settings.telephony_gateway_mode,
        "configured": configured,
        "live_call_enabled": settings.asterisk_live_call_enabled,
        "bulk_call_enabled": settings.asterisk_bulk_call_enabled,
        "ami_reachable": False,
        "authenticated": False,
        "ping_ok": False,
        "trunk_configured": trunk_configured,
        "trunk_reachable": None,
        "trunk_status": "待检测",
        "max_channels": settings.asterisk_max_channels,
        "errors": errors,
    }
    if not configured:
        errors.append("Asterisk AMI 账号或密码未配置")
        return AsteriskHealth(**health)
    if not trunk_configured:
        errors.append("Asterisk trunk 名称未配置")

    try:
        with AsteriskAmiClient() as client:
            health["ami_reachable"] = True
            health["authenticated"] = True
            ping = client.ping()
            health["ping_ok"] = ping.ok
            if not ping.ok:
                errors.append(ping.message or "AMI Ping 未通过")
            if trunk_configured:
                commands = [
                    f"pjsip show endpoint {settings.asterisk_trunk_name}",
                    f"sip show peer {settings.asterisk_trunk_name}",
                ]
                for command in commands:
                    response = client.command(command)
                    output = response.field_text("Output") or response.message
                    trunk_reachable, trunk_status = _trunk_status_from_output(output)
                    if trunk_reachable is not False:
                        health["trunk_reachable"] = trunk_reachable
                        health["trunk_status"] = trunk_status
                        break
                    health["trunk_reachable"] = trunk_reachable
                    health["trunk_status"] = trunk_status
    except AsteriskAmiError as exc:
        errors.append(str(exc))
    return AsteriskHealth(**health)


def originate_test_call(phone: str, caller_id: str | None = None) -> AsteriskOriginateResult:
    if not settings.asterisk_live_call_enabled:
        raise AsteriskAmiError("真实线路拨号开关未启用，请先设置 ASTERISK_LIVE_CALL_ENABLED=true")
    with AsteriskAmiClient() as client:
        return client.originate(phone, caller_id=caller_id, variables={"AI_ACQ_TEST_CALL": "1"})


def normalize_ami_call_event(event: dict[str, str]) -> dict[str, str]:
    event_name = event.get("Event", "")
    dial_status = event.get("DialStatus", "")
    channel_state = event.get("ChannelStateDesc", "")
    response = event.get("Response", "")
    reason = event.get("Reason", "")
    cause = event.get("Cause", "")

    status = "unknown"
    if event_name == "DialBegin":
        status = "dialing"
    elif event_name == "Newstate" and channel_state in {"Ringing", "Ring"}:
        status = "ringing"
    elif event_name in {"BridgeEnter", "BridgeCreate"} or channel_state == "Up":
        status = "answered"
    elif event_name == "DialEnd":
        status = {
            "ANSWER": "answered",
            "BUSY": "busy",
            "NOANSWER": "no_answer",
            "CANCEL": "cancelled",
            "CONGESTION": "failed",
            "CHANUNAVAIL": "failed",
        }.get(dial_status.upper(), "ended")
    elif event_name == "Hangup":
        status = {"16": "hangup", "17": "busy", "18": "no_answer", "19": "no_answer", "21": "failed"}.get(cause, "hangup")
    elif event_name == "OriginateResponse":
        if response.lower() == "success":
            status = "dialing"
        else:
            status = {"0": "failed", "1": "no_answer", "4": "answered", "5": "busy", "8": "failed"}.get(reason, "failed")

    return {
        "status": status,
        "event": event_name,
        "dialStatus": dial_status,
        "cause": cause,
    }
