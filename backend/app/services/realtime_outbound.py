from dataclasses import dataclass, field
from datetime import datetime
import socket
from uuid import uuid4

from app.core.config import settings


class RealtimeSessionNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class RealtimeVoice:
    voice_id: str
    voice_name: str
    voice_type: str
    provider: str
    external_voice_id: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "voiceId": self.voice_id,
            "voiceName": self.voice_name,
            "voiceType": self.voice_type,
            "provider": self.provider,
            "externalVoiceId": self.external_voice_id,
        }


@dataclass
class RealtimeEvent:
    id: str
    at: datetime
    type: str
    actor: str
    status: str
    text: str
    detail: str
    latency_ms: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "at": self.at,
            "type": self.type,
            "actor": self.actor,
            "status": self.status,
            "text": self.text,
            "detail": self.detail,
            "latencyMs": self.latency_ms,
        }


@dataclass
class RealtimeSession:
    id: str
    merchant_name: str
    phone: str | None
    voice: RealtimeVoice
    status: str = "listening"
    mode: str = "half_duplex_interruptible"
    bridge_mode: str = "mock_media"
    current_intent: str = "待识别"
    current_node: str = "开场白"
    interruptions: int = 0
    cost_estimate_per_minute: float = 0.04
    latency_estimate_ms: int = 1380
    current_tts_event_id: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    events: list[RealtimeEvent] = field(default_factory=list)

    def add_event(
        self,
        event_type: str,
        actor: str,
        status: str,
        text: str,
        detail: str,
        latency_ms: int = 0,
    ) -> RealtimeEvent:
        event = RealtimeEvent(
            id=uuid4().hex,
            at=datetime.utcnow(),
            type=event_type,
            actor=actor,
            status=status,
            text=text,
            detail=detail,
            latency_ms=latency_ms,
        )
        self.events.append(event)
        self.updated_at = event.at
        return event

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "mode": self.mode,
            "bridgeMode": self.bridge_mode,
            "merchantName": self.merchant_name,
            "phone": self.phone,
            "voice": self.voice.as_dict(),
            "currentIntent": self.current_intent,
            "currentNode": self.current_node,
            "interruptions": self.interruptions,
            "costEstimatePerMinute": self.cost_estimate_per_minute,
            "latencyEstimateMs": self.latency_estimate_ms,
            "startedAt": self.started_at,
            "updatedAt": self.updated_at,
            "events": [event.as_dict() for event in self.events[-40:]],
        }


_SESSIONS: dict[str, RealtimeSession] = {}


def build_realtime_pipeline() -> dict[str, object]:
    audio_socket_ready = _is_tcp_open(settings.asterisk_audio_socket_host, settings.asterisk_audio_socket_port)
    bridge_ready = settings.telephony_gateway_mode == "asterisk" and settings.asterisk_live_call_enabled and audio_socket_ready
    steps = [
        _pipeline_step(
            "media_bridge",
            "UC100/Asterisk 媒体桥",
            "warn" if not bridge_ready else "pass",
            "mock_media" if not bridge_ready else "asterisk_audiosocket",
            120,
            (
                f"AudioSocket 桥接服务监听 {settings.asterisk_audio_socket_host}:{settings.asterisk_audio_socket_port}，"
                "Asterisk 接通后把电话 8k PCM 音频送入 ASR/TTS 回路。"
                if bridge_ready
                else "真实媒体桥未完全就绪；需要 Asterisk/UC100、单号试拨开关和 AudioSocket bridge 同时在线。"
            ),
        ),
        _pipeline_step("asr", "流式 ASR", "pass", settings.realtime_asr_model, 380, "电话 8k PCM 直接送入 Paraformer realtime。"),
        _pipeline_step("router", "快速意图路由", "pass", "local intent rules", 50, "价格、拒绝、稍后联系、加微信、身份确认等高频意图先走规则。"),
        _pipeline_step("llm", "LLM 生成", "pass", "DeepSeek-V4-Flash adapter", 320, "当前使用短句模拟回复；真实接入时只给复杂问题调用 LLM。"),
        _pipeline_step("tts", "流式 TTS", "pass", settings.dashscope_tts_model, 430, "优先使用声音档案可用复刻 voice_id 输出 8k PCM；客户可在声音档案选择音色。"),
        _pipeline_step("barge_in", "打断处理", "pass", "VAD + playback queue cancel", 80, "AI 说话时收到客户插话会停止当前 TTS 并重新进入 listening。"),
    ]
    estimated_latency = sum(int(step["latencyMs"]) for step in steps)
    return {
        "mode": "half_duplex_interruptible",
        "bridgeMode": "mock_media" if not bridge_ready else "asterisk_audiosocket",
        "targetLatencyMs": 1500,
        "estimatedLatencyMs": estimated_latency,
        "estimatedAiCostPerMinute": 0.04,
        "readyForMockCall": True,
        "readyForAsteriskMedia": bridge_ready,
        "nextStep": (
            "真实电话媒体桥已就绪，可以从前端做单号试拨。"
            if bridge_ready
            else "先启动 AudioSocket bridge，再打开 ASTERISK_LIVE_CALL_ENABLED=true，并从前端做单号试拨。"
        ),
        "steps": steps,
    }


def create_realtime_session(merchant_name: str, phone: str | None, voice: dict[str, object]) -> dict[str, object]:
    selected_voice = RealtimeVoice(
        voice_id=str(voice.get("voiceId") or voice.get("voice_id") or "qwen_tts_ethan"),
        voice_name=str(voice.get("voiceName") or voice.get("voice_name") or "晨煦（Ethan）"),
        voice_type=str(voice.get("voiceType") or voice.get("voice_type") or "system"),
        provider=str(voice.get("provider") or "Qwen-TTS"),
        external_voice_id=_optional_text(voice.get("externalVoiceId") or voice.get("external_voice_id")),
    )
    session = RealtimeSession(
        id=uuid4().hex,
        merchant_name=merchant_name,
        phone=phone,
        voice=selected_voice,
        cost_estimate_per_minute=_estimate_cost(selected_voice.voice_type),
    )
    session.add_event(
        "session_started",
        "system",
        "ready",
        "模拟实时外呼会话已创建。",
        f"使用音色：{selected_voice.voice_name}；模式：半双工 + 可打断。",
    )
    _SESSIONS[session.id] = session
    return session.as_dict()


def get_realtime_session(session_id: str) -> dict[str, object]:
    return _require_session(session_id).as_dict()


def handle_customer_utterance(session_id: str, text: str, barge_in: bool = True) -> dict[str, object]:
    session = _require_session(session_id)
    interrupted = False
    if barge_in and session.status == "speaking":
        interrupted = _interrupt_session(session, "客户插话，停止当前 TTS 播放队列。")

    clean_text = " ".join(text.strip().split())
    session.status = "thinking"
    session.add_event("customer_audio", "customer", "received", clean_text, "模拟媒体入口收到客户语音。")
    session.add_event("asr_final", "asr", "final", clean_text, "Paraformer 实时识别最终文本。", latency_ms=380)

    intent, node = _classify_intent(clean_text)
    session.current_intent = intent
    session.current_node = node
    session.add_event("intent", "router", "matched", intent, f"路由到话术节点：{node}。", latency_ms=50)

    reply = _build_reply(clean_text, intent, session.merchant_name)
    session.add_event("llm_reply", "assistant", "ready", reply, "规则优先，复杂问题由 DeepSeek-V4-Flash adapter 生成短句。", latency_ms=320)

    chunks = _build_tts_chunks(reply, session.voice.provider)
    tts_event = session.add_event(
        "tts_stream",
        "tts",
        "playing",
        reply,
        f"{session.voice.voice_name} 正在流式合成并送入播放队列。",
        latency_ms=430,
    )
    session.current_tts_event_id = tts_event.id
    session.status = "speaking"
    return {
        "session": session.as_dict(),
        "asrText": clean_text,
        "intent": intent,
        "reply": reply,
        "interrupted": interrupted,
        "ttsChunks": chunks,
    }


def interrupt_realtime_session(session_id: str) -> dict[str, object]:
    session = _require_session(session_id)
    _interrupt_session(session, "人工或 VAD 触发打断，停止当前 TTS。")
    return session.as_dict()


def complete_realtime_playback(session_id: str) -> dict[str, object]:
    session = _require_session(session_id)
    if session.status == "speaking":
        session.status = "listening"
        session.current_tts_event_id = None
        session.add_event("playback_done", "media", "done", "AI 播放完成。", "播放队列已清空，继续监听客户。")
    return session.as_dict()


def _require_session(session_id: str) -> RealtimeSession:
    session = _SESSIONS.get(session_id)
    if not session:
        raise RealtimeSessionNotFound("实时外呼会话不存在")
    return session


def _pipeline_step(key: str, label: str, status: str, provider: str, latency_ms: int, detail: str) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "provider": provider,
        "latencyMs": latency_ms,
        "detail": detail,
    }


def _estimate_cost(voice_type: str) -> float:
    return 0.06 if voice_type in {"clone", "cloned", "voice_clone"} else 0.04


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _classify_intent(text: str) -> tuple[str, str]:
    lower = text.lower()
    if any(keyword in text for keyword in ["多少钱", "费用", "价格", "收费", "贵"]):
        return "价格异议", "价格说明"
    if any(keyword in text for keyword in ["不需要", "不用", "没兴趣", "别打"]):
        return "明确拒绝", "礼貌结束"
    if any(keyword in text for keyword in ["忙", "晚点", "稍后", "改天"]):
        return "稍后联系", "预约复拨"
    if any(keyword in text for keyword in ["微信", "资料", "发我", "加一下"]):
        return "加微信/发资料", "留资转化"
    if any(keyword in text for keyword in ["你是谁", "哪里", "干嘛", "什么公司"]) or "who" in lower:
        return "身份确认", "身份说明"
    return "需求探索", "资格确认"


def _build_reply(text: str, intent: str, merchant_name: str) -> str:
    replies = {
        "价格异议": "费用不用现在决定，我们可以先按您的品类给一版基础方案，您看适不适合再说。",
        "明确拒绝": "好的，打扰您了。我这边给您标记不再跟进，祝您生意顺利。",
        "稍后联系": "可以的，我不多打扰。您看今天下午还是明天上午，我再简单跟您确认一下？",
        "加微信/发资料": "可以，我安排顾问把入驻资料和同品类案例发您，您看完觉得合适再沟通。",
        "身份确认": "我是本地生活获客服务顾问，主要帮商家做视频号团购曝光和到店转化，今天先跟您确认是否有需求。",
    }
    if intent in replies:
        return replies[intent]
    if len(text) <= 8:
        return f"明白，{merchant_name}这边目前更关注到店客流，还是线上团购曝光呢？"
    return "了解，我先确认一下：您现在主要是想增加到店客户，还是想先了解视频号团购怎么做？"


def _build_tts_chunks(reply: str, provider: str) -> list[dict[str, object]]:
    clauses = [item.strip() for item in reply.replace("？", "？|").replace("。", "。|").replace("，", "，|").split("|") if item.strip()]
    chunks: list[dict[str, object]] = []
    for index, clause in enumerate(clauses):
        chunks.append(
            {
                "index": index,
                "text": clause,
                "durationMs": max(360, min(1800, len(clause) * 85)),
                "provider": provider,
            }
        )
    return chunks


def _interrupt_session(session: RealtimeSession, detail: str) -> bool:
    session.interruptions += 1
    session.status = "listening"
    session.current_tts_event_id = None
    session.add_event("tts_interrupted", "system", "stopped", "已停止 AI 播放。", detail, latency_ms=80)
    return True


def _is_tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False
