import json
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from app.core.config import settings
from app.services.telephony_runtime_config import telephony_bool, telephony_int, telephony_str
from app.services.voice_gateway_profiles import current_voice_gateway_profile, voice_gateway_label


class AsteriskAmiError(RuntimeError):
    pass


class AsteriskAmiValidationError(AsteriskAmiError):
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
    voice_gateway_profile: dict[str, object]
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
        return self.configured and self.authenticated and self.ping_ok and self.trunk_configured and self.trunk_reachable is True

    def as_dict(self) -> dict[str, object]:
        return {
            "checkedAt": self.checked_at,
            "gatewayMode": self.gateway_mode,
            "voiceGatewayProfile": self.voice_gateway_profile,
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
    verification_stage: str
    cellular_confirmed: bool
    media_loop_confirmed: bool
    acceptance_ready: bool
    acceptance_note: str


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


def split_ami_messages(raw: str) -> list[str]:
    normalized = raw.replace("\r\n", "\n")
    return [chunk for chunk in normalized.split("\n\n") if chunk.strip()]


def safe_ami_event_log(events: list[dict[str, str | list[str]]]) -> list[dict[str, str]]:
    allowed = {"Event", "DialStatus", "Cause", "Cause-txt", "TechCause", "Response", "Reason", "ChannelStateDesc"}
    result: list[dict[str, str]] = []
    for event in events[-12:]:
        result.append({key: str(value) for key, value in event.items() if key in allowed})
    return result


def originate_verification(status: str) -> dict[str, str | bool]:
    if status == "ringing":
        return {
            "verification_stage": "gateway_signaling_only",
            "cellular_confirmed": False,
            "media_loop_confirmed": False,
            "acceptance_ready": False,
            "acceptance_note": f"只确认 Asterisk/{voice_gateway_label()} SIP 侧有响应；未确认运营商蜂窝侧真实振铃，也未进入实时媒体链路。",
        }
    if status == "answered":
        return {
            "verification_stage": "cellular_answered_no_media_proof",
            "cellular_confirmed": True,
            "media_loop_confirmed": False,
            "acceptance_ready": False,
            "acceptance_note": "Asterisk 收到接通事件；仍需 AudioSocket、ASR、TTS 和打断事件完成实时通话验收。",
        }
    if status == "dialing":
        return {
            "verification_stage": "originate_submitted",
            "cellular_confirmed": False,
            "media_loop_confirmed": False,
            "acceptance_ready": False,
            "acceptance_note": f"只确认 AMI 已提交拨号请求；还没有{voice_gateway_label()}蜂窝侧或通话媒体证据。",
        }
    return {
        "verification_stage": "not_connected",
        "cellular_confirmed": False,
        "media_loop_confirmed": False,
        "acceptance_ready": False,
        "acceptance_note": f"外呼未达到真实接通验收；请根据线路状态继续排查{voice_gateway_label()}、SIM/运营商和呼叫路由。",
    }


class AsteriskAmiClient:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: int | None = None,
        events: bool = False,
    ) -> None:
        self.host = host or telephony_str("ASTERISK_HOST", "AI_ACQ_ASTERISK_HOST", fallback=settings.asterisk_host)
        self.port = port or telephony_int("ASTERISK_AMI_PORT", "AI_ACQ_ASTERISK_AMI_PORT", fallback=settings.asterisk_ami_port)
        self.username = username if username is not None else telephony_str("ASTERISK_AMI_USERNAME", "AI_ACQ_ASTERISK_AMI_USERNAME", fallback=settings.asterisk_ami_username)
        self.password = password if password is not None else telephony_str("ASTERISK_AMI_PASSWORD", "AI_ACQ_ASTERISK_AMI_PASSWORD", fallback=settings.asterisk_ami_password)
        self.timeout_seconds = timeout_seconds or telephony_int("ASTERISK_AMI_TIMEOUT_SECONDS", fallback=settings.asterisk_ami_timeout_seconds)
        self.events = events
        self._socket: socket.socket | None = None
        self._incoming_messages: list[str] = []
        self._event_messages: list[str] = []

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
                "Events": "on" if self.events else "off",
            }
        )
        if not response.ok:
            raise AsteriskAmiError(response.message or "Asterisk AMI 登录失败")

    def ping(self) -> AmiResponse:
        return self.send_action({"Action": "Ping"})

    def command(self, command: str) -> AmiResponse:
        return self.send_action({"Action": "Command", "Command": command})

    def originate(
        self,
        phone: str,
        caller_id: str | None = None,
        variables: dict[str, str] | None = None,
        wait_for_result_seconds: float = 0,
    ) -> AsteriskOriginateResult:
        action_id = f"ai-acq-{uuid4().hex}"
        channel = render_originate_channel(phone)
        payload: dict[str, str | list[str]] = {
            "Action": "Originate",
            "ActionID": action_id,
            "Channel": channel,
            "Context": telephony_str("ASTERISK_ORIGINATE_CONTEXT", fallback=settings.asterisk_originate_context),
            "Exten": telephony_str("ASTERISK_ORIGINATE_EXTENSION", fallback=settings.asterisk_originate_extension),
            "Priority": "1",
            "CallerID": clean_ami_field_value(caller_id or settings.asterisk_caller_id, "AMI CallerID"),
            "Timeout": str(telephony_int("ASTERISK_ORIGINATE_TIMEOUT_MS", fallback=settings.asterisk_originate_timeout_ms)),
            "Async": "true",
        }
        if variables:
            payload["Variable"] = [
                f"{clean_ami_field_value(key, 'AMI Variable')}={clean_ami_field_value(value, 'AMI Variable')}"
                for key, value in variables.items()
            ]
        response = self.send_action(payload)
        event_result = self._wait_for_originate_result(action_id, wait_for_result_seconds) if response.ok and self.events else None
        if event_result:
            verification = originate_verification(str(event_result["status"]))
            return AsteriskOriginateResult(
                accepted=bool(event_result["accepted"]),
                action_id=action_id,
                channel=channel,
                status=str(event_result["status"]),
                message=str(event_result["message"]),
                raw_payload=json.dumps(
                    {
                        "provider": "asterisk",
                        "actionId": action_id,
                        "channel": channel,
                        "response": response.response,
                        "message": response.message,
                        "events": event_result["events"],
                    },
                    ensure_ascii=False,
                ),
                verification_stage=str(verification["verification_stage"]),
                cellular_confirmed=bool(verification["cellular_confirmed"]),
                media_loop_confirmed=bool(verification["media_loop_confirmed"]),
                acceptance_ready=bool(verification["acceptance_ready"]),
                acceptance_note=str(verification["acceptance_note"]),
            )
        accepted = response.ok
        status = "dialing" if accepted else "failed"
        verification = originate_verification(status)
        return AsteriskOriginateResult(
            accepted=accepted,
            action_id=action_id,
            channel=channel,
            status=status,
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
            verification_stage=str(verification["verification_stage"]),
            cellular_confirmed=bool(verification["cellular_confirmed"]),
            media_loop_confirmed=bool(verification["media_loop_confirmed"]),
            acceptance_ready=bool(verification["acceptance_ready"]),
            acceptance_note=str(verification["acceptance_note"]),
        )

    def send_action(self, fields: dict[str, str | list[str]]) -> AmiResponse:
        if self._socket is None:
            raise AsteriskAmiError("Asterisk AMI 尚未连接")
        lines: list[str] = []
        for key, value in fields.items():
            header_name = clean_ami_field_value(key, "AMI header")
            values = value if isinstance(value, list) else [value]
            for item in values:
                lines.append(f"{header_name}: {clean_ami_field_value(item, header_name)}")
        payload = "\r\n".join(lines) + "\r\n\r\n"
        try:
            self._socket.sendall(payload.encode("utf-8"))
            deadline = time.monotonic() + max(self.timeout_seconds, 1)
            while True:
                message = self._read_next_message()
                response = parse_ami_message(message)
                if "Response" in response.fields:
                    return response
                if response.fields.get("Event"):
                    self._event_messages.append(message)
                if time.monotonic() >= deadline:
                    raise TimeoutError
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

    def _read_next_message(self) -> str:
        if self._incoming_messages:
            return self._incoming_messages.pop(0)
        raw = self._read_message()
        messages = split_ami_messages(raw)
        if not messages:
            return ""
        self._incoming_messages.extend(messages[1:])
        return messages[0]

    def _read_next_event_message(self) -> str:
        if self._event_messages:
            return self._event_messages.pop(0)
        return self._read_next_message()

    def _wait_for_originate_result(self, action_id: str, timeout_seconds: float) -> dict[str, object] | None:
        if timeout_seconds <= 0 or self._socket is None:
            return None

        deadline = time.monotonic() + timeout_seconds
        started_at = time.monotonic()
        saw_ringing = False
        ringing_event: dict[str, str | list[str]] | None = None
        events: list[dict[str, str | list[str]]] = []
        previous_timeout = self._socket.gettimeout()
        self._socket.settimeout(min(max(timeout_seconds, 0.5), 1.0))
        try:
            while time.monotonic() < deadline:
                try:
                    raw_message = self._read_next_event_message()
                except TimeoutError:
                    continue
                response = parse_ami_message(raw_message)
                event = response.fields
                event_name = str(event.get("Event", ""))
                if not event_name:
                    continue
                events.append(event)

                event_action_id = str(event.get("ActionID", ""))
                normalized = normalize_ami_call_event({key: str(value) for key, value in event.items()})
                status = normalized["status"]
                if is_line_rejection_event(event):
                    status = "failed"
                if status == "ringing":
                    saw_ringing = True
                    ringing_event = event
                if is_immediate_originate_failure(event, status, saw_ringing, time.monotonic() - started_at):
                    status = "failed"
                message = ami_call_status_message(event, status)

                if event_name == "OriginateResponse" and event_action_id and event_action_id != action_id:
                    continue
                if status in {"failed", "busy", "no_answer", "cancelled"}:
                    return {
                        "accepted": False,
                        "status": status,
                        "message": message,
                        "events": safe_ami_event_log(events),
                    }
                if status == "answered":
                    return {
                        "accepted": True,
                        "status": "answered",
                        "message": message,
                        "events": safe_ami_event_log(events),
                    }
                if status == "ringing":
                    continue
        finally:
            self._socket.settimeout(previous_timeout)
        if saw_ringing:
            return {
                "accepted": True,
                "status": "ringing",
                "message": ami_call_status_message(ringing_event or {}, "ringing"),
                "events": safe_ami_event_log(events),
            }
        return None


def clean_ami_field_value(value: object, field_name: str) -> str:
    text = str(value)
    if any(char in text for char in ("\r", "\n", "\x00")):
        raise AsteriskAmiValidationError(f"{field_name} 不能包含换行或控制字符")
    return text


def normalize_originate_phone(phone: str) -> str:
    if any(char in phone for char in ("\r", "\n", "\x00")):
        raise AsteriskAmiValidationError("测试号码不能包含换行或控制字符")
    normalized = "".join(char for char in phone.strip() if char not in {" ", "\t", "-", "(", ")"})
    if not normalized:
        raise AsteriskAmiValidationError("测试号码不能为空")
    allowed = set("0123456789+*#,")
    if any(char not in allowed for char in normalized):
        raise AsteriskAmiValidationError("测试号码只能包含数字、+、*、#、逗号、空格、横线或括号")
    return normalized


def render_originate_channel(phone: str) -> str:
    profile = current_voice_gateway_profile()
    template = telephony_str("ASTERISK_ORIGINATE_CHANNEL_TEMPLATE", fallback=settings.asterisk_originate_channel_template)
    channel = template.format(
        phone=normalize_originate_phone(phone),
        trunk=profile.trunk_name or telephony_str("ASTERISK_TRUNK_NAME", fallback=settings.asterisk_trunk_name),
    )
    return clean_ami_field_value(channel, "AMI Channel")


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
    profile = current_voice_gateway_profile()
    configured = bool(
        telephony_str("ASTERISK_AMI_USERNAME", "AI_ACQ_ASTERISK_AMI_USERNAME", fallback=settings.asterisk_ami_username)
        and telephony_str("ASTERISK_AMI_PASSWORD", "AI_ACQ_ASTERISK_AMI_PASSWORD", fallback=settings.asterisk_ami_password)
    )
    trunk_configured = bool(profile.trunk_name)
    health = {
        "checked_at": datetime.utcnow(),
        "gateway_mode": telephony_str("TELEPHONY_GATEWAY_MODE", fallback=settings.telephony_gateway_mode),
        "voice_gateway_profile": profile.as_dict(),
        "configured": configured,
        "live_call_enabled": telephony_bool("ASTERISK_LIVE_CALL_ENABLED", fallback=settings.asterisk_live_call_enabled),
        "bulk_call_enabled": telephony_bool("ASTERISK_BULK_CALL_ENABLED", fallback=settings.asterisk_bulk_call_enabled),
        "ami_reachable": False,
        "authenticated": False,
        "ping_ok": False,
        "trunk_configured": trunk_configured,
        "trunk_reachable": None,
        "trunk_status": "待检测",
        "max_channels": telephony_int("ASTERISK_MAX_CHANNELS", "VOICE_GATEWAY_MAX_CHANNELS", fallback=profile.max_channels),
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
                    f"pjsip show endpoint {profile.trunk_name}",
                    f"sip show peer {profile.trunk_name}",
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
    if not telephony_bool("ASTERISK_LIVE_CALL_ENABLED", fallback=settings.asterisk_live_call_enabled):
        raise AsteriskAmiError("真实线路拨号开关未启用，请先设置 ASTERISK_LIVE_CALL_ENABLED=true")
    render_originate_channel(phone)
    if caller_id:
        clean_ami_field_value(caller_id, "AMI CallerID")
    with AsteriskAmiClient(events=True) as client:
        return client.originate(
            phone,
            caller_id=caller_id,
            variables={"AI_ACQ_TEST_CALL": "1"},
            wait_for_result_seconds=settings.asterisk_test_call_result_wait_seconds,
        )


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
    elif event_name in {"Hangup", "HangupRequest"}:
        status = {"1": "failed", "3": "failed", "16": "hangup", "17": "busy", "18": "no_answer", "19": "no_answer", "21": "failed"}.get(cause, "hangup")
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


def ami_call_status_message(event: dict[str, str | list[str]], status: str) -> str:
    gateway = voice_gateway_label()
    event_name = str(event.get("Event", ""))
    dial_status = str(event.get("DialStatus", "")).upper()
    cause = str(event.get("Cause", ""))
    cause_text = str(event.get("Cause-txt", ""))
    tech_cause = str(event.get("TechCause", ""))
    response = str(event.get("Response", ""))
    reason = str(event.get("Reason", ""))
    diagnostic = " ".join(part for part in [tech_cause, cause_text, dial_status, response, reason] if part)
    lower_diagnostic = diagnostic.lower()

    if "403" in diagnostic or "forbidden" in lower_diagnostic:
        return f"{gateway} 拒绝外呼：403 Forbidden。请在语音网关后台配置允许 Asterisk/SIP 分机通过外呼线路后重试。"
    if "404" in diagnostic or "not found" in lower_diagnostic or "no_route_destination" in lower_diagnostic or (status == "failed" and cause == "3"):
        return f"{gateway} 找不到可用外呼路由：404 Not Found / NO_ROUTE_DESTINATION。请检查语音网关的 SIP 到运营商线路路由、号码匹配规则和线路选择。"
    if status == "answered":
        return "电话已接通，实时音频桥已进入通话。"
    if status == "ringing":
        return f"{gateway}/SIP 侧已响应振铃，但尚未确认手机真实响铃；请以语音网关话单/当前呼叫和手机来电为准。"
    if status == "busy":
        return "号码忙线或被占用，请稍后重试。"
    if status == "no_answer":
        return "号码暂未接听或运营商未返回接通。"
    if status == "cancelled":
        return "试拨已取消或线路提前结束。"
    if status == "failed" and cause == "21":
        return "线路拒绝外呼。请检查语音网关的 SIP 分机/中继/呼叫路由是否允许当前 Asterisk 发起外呼。"
    if is_immediate_originate_failure(event, status, saw_ringing=False, elapsed_seconds=0):
        return f"{gateway}/运营商未放行外呼：呼叫没有进入振铃就被线路侧结束。请检查语音网关的 SIP 分机、呼叫路由和运营商外呼权限。"
    if status == "failed" and dial_status:
        return f"线路外呼失败：{dial_status}。请检查语音网关 SIP 路由、SIM 卡和运营商线路状态。"
    if status == "failed" and event_name == "OriginateResponse":
        return f"Asterisk 发起外呼失败：Reason {reason or 'unknown'}。"
    return "试拨状态已更新。"


def is_immediate_originate_failure(
    event: dict[str, str | list[str]],
    status: str,
    saw_ringing: bool,
    elapsed_seconds: float,
) -> bool:
    event_name = str(event.get("Event", ""))
    response = str(event.get("Response", "")).lower()
    reason = str(event.get("Reason", ""))
    if event_name != "OriginateResponse" or response != "failure" or saw_ringing:
        return False
    return reason == "1" and elapsed_seconds <= 5


def is_line_rejection_event(event: dict[str, str | list[str]]) -> bool:
    cause = str(event.get("Cause", ""))
    cause_text = str(event.get("Cause-txt", ""))
    tech_cause = str(event.get("TechCause", ""))
    diagnostic = " ".join(part for part in [tech_cause, cause_text] if part).lower()
    return (
        cause in {"3", "21"}
        or "403" in diagnostic
        or "404" in diagnostic
        or "forbidden" in diagnostic
        or "not found" in diagnostic
        or "no_route_destination" in diagnostic
    )
