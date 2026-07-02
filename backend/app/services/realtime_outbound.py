import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import socket
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.services.realtime_llm import deepseek_configured, generate_realtime_reply
from app.services.realtime_sales_brain import score_realtime_events
from app.services.voice_gateway_profiles import voice_gateway_label


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
    latency_estimate_ms: int = 980
    current_tts_event_id: str | None = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    events: list[RealtimeEvent] = field(default_factory=list)
    conversation_history: list[dict[str, str]] = field(default_factory=list)

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


def _normalize_conversation_route(route: str | None) -> str:
    normalized = (route or settings.realtime_conversation_mode or "pipeline").strip().lower()
    return "omni" if normalized in {"omni", "qwen_omni", "omni_realtime_interruptible"} else "pipeline"


def _route_mode_label(route: str) -> str:
    return "omni_realtime_interruptible" if route == "omni" else "half_duplex_interruptible"


def _route_cost(route: str, voice_type: str = "system") -> float:
    if route == "omni":
        return 0.09
    return _estimate_cost(voice_type)


def _route_latency(route: str, llm_ready: bool | None = None) -> int:
    if route == "omni":
        return 720
    if llm_ready is None:
        llm_ready = deepseek_configured()
    return 1075 if llm_ready else 755


def _conversation_route_options(current_route: str, bridge_ready: bool) -> list[dict[str, object]]:
    llm_ready = deepseek_configured()
    dashscope_ready = bool(settings.dashscope_api_key.strip())
    return [
        {
            "key": "omni",
            "label": "极速人声 Omni",
            "mode": "omni_realtime_interruptible",
            "summary": "端到端实时语音模型，直接听语音并直接说话，适合追求自然衔接和低延迟的正式拨测。",
            "estimatedLatencyMs": _route_latency("omni"),
            "estimatedAiCostPerMinute": _route_cost("omni"),
            "readyForAsteriskMedia": bridge_ready and dashscope_ready and current_route == "omni",
            "isActive": current_route == "omni",
        },
        {
            "key": "pipeline",
            "label": "低成本分段 Pipeline",
            "mode": "half_duplex_interruptible",
            "summary": "ASR、语义路由/LLM、流式 TTS 分段执行，成本更低，适合低频授权回访和成本敏感客户。",
            "estimatedLatencyMs": _route_latency("pipeline", llm_ready),
            "estimatedAiCostPerMinute": _route_cost("pipeline"),
            "readyForAsteriskMedia": bridge_ready and current_route == "pipeline",
            "isActive": current_route == "pipeline",
        },
    ]


def build_realtime_pipeline() -> dict[str, object]:
    gateway_label = voice_gateway_label()
    audio_socket_ready = _is_tcp_open(settings.asterisk_audio_socket_host, settings.asterisk_audio_socket_port)
    bridge_ready = settings.telephony_gateway_mode == "asterisk" and settings.asterisk_live_call_enabled and audio_socket_ready
    conversation_mode = _normalize_conversation_route(settings.realtime_conversation_mode)
    if conversation_mode == "omni":
        dashscope_ready = bool(settings.dashscope_api_key.strip())
        steps = [
            _pipeline_step(
                "media_bridge",
                "语音网关/Asterisk 媒体桥",
                "warn" if not bridge_ready else "pass",
                "mock_media" if not bridge_ready else "asterisk_audiosocket",
                120,
                (
                    f"AudioSocket 桥接服务监听 {settings.asterisk_audio_socket_host}:{settings.asterisk_audio_socket_port}，"
                    "Asterisk 接通后把电话 8k PCM 音频送入 Qwen Omni。"
                    if bridge_ready
                    else f"真实媒体桥未完全就绪；需要 Asterisk/{gateway_label}、单号试拨开关和 AudioSocket bridge 同时在线。"
                ),
            ),
            _pipeline_step(
                "omni_realtime",
                "端到端实时语音模型",
                "pass" if dashscope_ready else "warn",
                settings.dashscope_omni_realtime_model,
                520,
                "Qwen Omni 直接听语音、理解上下文并流式输出语音，素材话术作为实时销售指令注入。",
            ),
            _pipeline_step(
                "barge_in",
                "打断处理",
                "pass" if dashscope_ready else "warn",
                "semantic VAD + local RMS cancel",
                80,
                "客户插话时本地先停止播报，同时让 Omni 取消当前回复并继续听客户说话。",
            ),
        ]
        estimated_latency = sum(int(step["latencyMs"]) for step in steps)
        return {
            "mode": "omni_realtime_interruptible",
            "bridgeMode": "mock_media" if not bridge_ready else "asterisk_audiosocket",
            "targetLatencyMs": 1000,
            "estimatedLatencyMs": estimated_latency,
            "estimatedAiCostPerMinute": 0.09,
            "readyForMockCall": True,
            "readyForAsteriskMedia": bridge_ready and dashscope_ready,
            "nextStep": (
                "Omni 真实电话媒体桥已就绪，可以从前端做单号试拨。"
                if bridge_ready and dashscope_ready
                else "先启动 AudioSocket bridge 的 omni 模式，并确认 DashScope key 与 Asterisk 单号试拨开关。"
            ),
            "routeOptions": _conversation_route_options(conversation_mode, bridge_ready),
            "steps": steps,
        }
    llm_ready = deepseek_configured()
    steps = [
        _pipeline_step(
            "media_bridge",
            "语音网关/Asterisk 媒体桥",
            "warn" if not bridge_ready else "pass",
            "mock_media" if not bridge_ready else "asterisk_audiosocket",
            120,
            (
                f"AudioSocket 桥接服务监听 {settings.asterisk_audio_socket_host}:{settings.asterisk_audio_socket_port}，"
                "Asterisk 接通后把电话 8k PCM 音频送入 ASR/TTS 回路。"
                if bridge_ready
                else f"真实媒体桥未完全就绪；需要 Asterisk/{gateway_label}、单号试拨开关和 AudioSocket bridge 同时在线。"
            ),
        ),
        _pipeline_step("asr", "流式 ASR", "pass", settings.realtime_asr_model, 380, "电话 8k PCM 直接送入 Paraformer realtime。"),
        _pipeline_step(
            "router",
            "语义意图路由",
            "pass",
            "semantic context policy",
            35,
            "先抽取客户当前问题类型和最近对话主题；身份、费用、保证、流程、资料等直接回答，开放问题再交给 DeepSeek 增强。",
        ),
        _pipeline_step(
            "llm",
            "LLM 生成",
            "pass" if llm_ready else "warn",
            settings.deepseek_chat_model if llm_ready else "local rules fallback",
            320 if llm_ready else 0,
            (
                "DeepSeek 负责开放追问和复杂表达；电话主链路保留语义兜底，慢或失败不会卡住通话。"
                if llm_ready
                else "未配置 DeepSeek 运行时密钥；真实电话会先使用本地规则兜底。"
            ),
        ),
        _pipeline_step(
            "tts",
            "流式 TTS",
            "pass",
            settings.dashscope_realtime_tts_model,
            140,
            "默认使用 Qwen-TTS 实时系统音色增量播放；客户在声音档案明确选择复刻音色时才切换到克隆音色。",
        ),
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
        "routeOptions": _conversation_route_options(conversation_mode, bridge_ready),
        "steps": steps,
    }


def create_realtime_session(
    merchant_name: str,
    phone: str | None,
    voice: dict[str, object],
    conversation_route: str | None = None,
) -> dict[str, object]:
    selected_voice = RealtimeVoice(
        voice_id=str(voice.get("voiceId") or voice.get("voice_id") or "qwen_tts_ethan"),
        voice_name=str(voice.get("voiceName") or voice.get("voice_name") or "晨煦（Ethan）"),
        voice_type=str(voice.get("voiceType") or voice.get("voice_type") or "system"),
        provider=str(voice.get("provider") or "Qwen-TTS"),
        external_voice_id=_optional_text(voice.get("externalVoiceId") or voice.get("external_voice_id")),
    )
    route = _normalize_conversation_route(conversation_route)
    session = RealtimeSession(
        id=uuid4().hex,
        merchant_name=merchant_name,
        phone=phone,
        voice=selected_voice,
        mode=_route_mode_label(route),
        cost_estimate_per_minute=_route_cost(route, selected_voice.voice_type),
        latency_estimate_ms=_route_latency(route),
    )
    session.add_event(
        "session_started",
        "system",
        "ready",
        "模拟实时外呼会话已创建。",
        f"使用音色：{selected_voice.voice_name}；路线：{'Omni 实时语音' if route == 'omni' else 'ASR+LLM+TTS 分段'}；两条路线都启用短句、情绪承接、不同问法不同回答和不机械推进策略。",
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

    fallback_reply = _build_reply(clean_text, intent, session.merchant_name)
    reply_result = generate_realtime_reply(
        clean_text,
        intent,
        session.merchant_name,
        fallback_reply,
        list(session.conversation_history),
    )
    reply = reply_result.reply
    _append_session_conversation_turn(session, clean_text, reply)
    session.add_event(
        "llm_reply",
        "assistant",
        "ready",
        reply,
        _llm_event_detail(reply_result.strategy, reply_result.error),
        latency_ms=reply_result.latency_ms,
    )

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


def read_realtime_live_events(limit: int = 80, call_id: str | None = None) -> dict[str, object]:
    max_limit = max(1, min(limit, 300))
    path = Path(settings.realtime_call_event_log_path).expanduser()
    events: list[dict[str, object]] = []
    if not path.exists():
        return {
            "logPath": str(path),
            "hasEvents": False,
            "latestAt": None,
            "score": None,
            "events": [],
        }
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        lines = handle.readlines()[-max(max_limit * 4, 200) :]
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if call_id and str(payload.get("callId") or "") != call_id:
            continue
        event = _normalize_live_event(payload)
        if event:
            events.append(event)
    events = events[-max_limit:]
    return {
        "logPath": str(path),
        "hasEvents": bool(events),
        "latestAt": events[-1]["at"] if events else None,
        "score": score_realtime_events(events),
        "events": events,
    }


def _require_session(session_id: str) -> RealtimeSession:
    session = _SESSIONS.get(session_id)
    if not session:
        raise RealtimeSessionNotFound("实时外呼会话不存在")
    return session


def _append_session_conversation_turn(session: RealtimeSession, customer_text: str, assistant_reply: str) -> None:
    session.conversation_history.append({"role": "user", "content": customer_text.strip()})
    session.conversation_history.append({"role": "assistant", "content": assistant_reply.strip()})
    if len(session.conversation_history) > 8:
        del session.conversation_history[: len(session.conversation_history) - 8]


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
    clean = text.strip()
    lower = clean.lower()
    compact = re.sub(r"[\s。！？?!，,、.]+", "", clean.lower())
    system_prompt_keywords = [
        "通话已不再录音",
        "此通话已不再录音",
        "开始录音",
        "停止录音",
        "正在录音",
        "暂时无法接听",
        "用户无法接听",
        "无法接听",
        "无法接通",
        "语音信箱",
        "语音留言",
        "语音录音",
        "录制留言",
        "录音完成",
        "请在提示音后",
        "提示音后",
        "提示音后录制",
        "留言后",
        "挂断即可",
        "若要留言",
        "请留言",
    ]
    if any(keyword in clean for keyword in system_prompt_keywords):
        return "系统提示", "忽略系统提示"
    call_screening_keywords = [
        "姓名",
        "请留下",
        "留下您的姓名",
        "留下你的姓名",
        "来电原因",
        "此人是否方便",
        "确认此人",
        "为您确认",
        "能为帮您确认",
        "能帮您确认",
        "是否方便接听",
        "帮你确认",
        "帮您确认",
        "请说明",
        "请先说明",
        "请说出",
        "请先说",
        "来意",
        "电话秘书",
        "电话助理",
        "来电助理",
        "我是您的来电助理",
        "我是你的来电助理",
        "您正在与来电助理通话",
        "正在与来电助理通话",
        "智能助理",
        "为了保护机主",
        "请简短说明",
        "简短说明来意",
        "确认是否接听",
        "稍后为您转达",
        "机主接听前",
        "请不要挂断",
        "请不要挂断电话",
        "不要挂断电话",
        "不要挂断",
    ]
    if any(keyword in clean for keyword in call_screening_keywords):
        return "身份确认", "身份说明"
    if compact in {"喂", "喂喂", "你好", "您好", "在", "在在", "你谁", "谁", "谁啊", "谁呀", "哪位", "您哪位", "你哪位"}:
        return "身份确认", "身份说明"
    if any(keyword in text for keyword in ["多少钱", "费用", "价格", "收费", "贵", "付费", "要钱", "花钱", "付钱"]):
        return "价格异议", "价格说明"
    material_only_decline = any(
        keyword in clean
        for keyword in [
            "不需要资料",
            "不用资料",
            "不要资料",
            "别发资料",
            "不用发资料",
            "不需要加微信",
            "不用加微信",
            "不要加微信",
            "不加微信",
            "直接回答",
            "说重点",
            "讲重点",
        ]
    ) and not any(keyword in clean for keyword in ["别打", "别联系", "不要打", "拉黑", "没兴趣", "挂了"])
    style_or_repeat_complaint_keywords = [
        "像机器人",
        "机器人",
        "ai",
        "AI",
        "念稿",
        "不自然",
        "机械",
        "不会说话",
        "不要重复",
        "别重复",
        "一直重复",
        "总是重复",
        "老说",
    ]
    if any(keyword in clean for keyword in style_or_repeat_complaint_keywords):
        return "听不清/澄清", "体验修复"
    rejection_keywords = [
        "不需要",
        "不用",
        "不要",
        "别打",
        "别联系",
        "不要打",
        "请不要",
        "没兴趣",
        "拉黑",
        "取消",
        "放个屁",
        "滚",
        "扯淡",
        "骗子",
        "神经病",
        "有病",
    ]
    if any(keyword in text for keyword in rejection_keywords) and not material_only_decline:
        return "明确拒绝", "礼貌结束"
    end_keywords = [
        "ok了",
        "ok 了",
        "好了",
        "可以了",
        "先这样",
        "就这样",
        "就这样吧",
        "这样吧",
        "挂了",
        "我挂了",
        "挂电话",
        "再见",
        "拜拜",
        "结束",
        "结束吧",
        "别说了",
        "不用说",
        "不用讲",
        "不聊了",
        "不说了",
        "到这",
        "到这里",
        "知道了",
        "明白了",
        "清楚了",
    ]
    if any(keyword in lower or keyword in clean for keyword in end_keywords):
        return "礼貌结束", "礼貌结束"
    if any(keyword in text for keyword in ["忙", "晚点", "稍后", "改天", "没空", "有事", "不方便", "开会", "等会", "一会"]):
        return "稍后联系", "预约复拨"
    low_information_confirmations = {
        "在",
        "嗯",
        "嗯嗯",
        "啊",
        "哦",
        "噢",
        "好",
        "好的",
        "是",
        "是的",
        "对",
        "对的",
        "可以",
        "行",
        "估计是",
    }
    if compact in low_information_confirmations:
        return "低信息确认", "继续确认"
    if material_only_decline:
        if any(keyword in clean for keyword in ["美团", "抖音", "大众点评", "小红书", "高德", "已有渠道"]):
            return "已有渠道", "直接回答渠道区别"
        if any(keyword in clean for keyword in ["效果", "客流", "到店", "曝光", "转化", "有用吗", "靠谱吗", "保证", "承诺", "保底"]):
            return "效果询问", "直接回答效果"
        if any(keyword in clean for keyword in ["怎么做", "怎么合作", "流程", "合作", "具体说", "具体讲", "详细讲"]):
            return "合作咨询", "直接回答流程"
        return "需求探索", "只回答问题"
    if any(
        keyword in text
        for keyword in [
            "微信",
            "资料",
            "发我",
            "发给我",
            "给我发",
            "怎么发",
            "怎么给我",
            "发哪里",
            "发到",
            "加一下",
            "短信",
            "发短信",
        ]
    ):
        return "加微信/发资料", "留资转化"
    source_keywords = [
        "哪来的",
        "哪里来的",
        "怎么知道",
        "谁给",
        "谁给你",
        "电话来源",
        "号码来源",
        "我的号码",
        "个人信息",
    ]
    if any(keyword in clean for keyword in source_keywords):
        return "来源/隐私", "合规说明"
    owner_keywords = [
        "老板不在",
        "负责人不在",
        "店长不在",
        "找老板",
        "找负责人",
        "找店长",
        "不是我负责",
        "我不负责",
        "转给",
    ]
    if any(keyword in clean for keyword in owner_keywords):
        return "找负责人", "转接负责人"
    existing_channel_keywords = [
        "已经做",
        "在做",
        "做过",
        "有做",
        "抖音团购",
        "美团",
        "大众点评",
        "小红书",
        "高德",
    ]
    if any(keyword in clean for keyword in existing_channel_keywords):
        return "已有渠道", "渠道补充"
    effect_keywords = [
        "效果",
        "客流",
        "到店",
        "曝光",
        "转化",
        "能带来",
        "有用吗",
        "靠谱吗",
        "保证",
        "承诺",
        "保底",
    ]
    if any(keyword in clean for keyword in effect_keywords):
        return "效果询问", "效果说明"
    cooperation_keywords = [
        "怎么做",
        "怎么合作",
        "怎么弄",
        "怎么开",
        "流程",
        "合作",
        "介绍",
        "说一下",
        "了解一下",
        "可以听",
        "可以说",
        "具体说",
        "具体讲",
        "详细讲",
        "详细讲解",
        "讲解一下",
    ]
    if any(keyword in clean for keyword in cooperation_keywords):
        return "合作咨询", "方案说明"
    identity_keywords = [
        "你是谁",
        "谁",
        "哪里",
        "干嘛",
        "做什么",
        "做啥",
        "什么公司",
        "什么事",
        "什么东西",
        "你们",
        "来电原因",
    ]
    if any(keyword in clean for keyword in identity_keywords) or "who" in lower:
        return "身份确认", "身份说明"
    clarification_keywords = [
        "听不清",
        "听不到",
        "听不见",
        "没听清",
        "没听到",
        "没听见",
        "听不懂",
        "说什么",
        "明白什么",
        "拧不到",
        "那什么",
        "再说一遍",
        "说一遍",
        "重复一遍",
        "重新说",
        "信号不好",
        "断断续续",
        "反应慢",
        "太慢",
        "卡",
        "没解决",
        "没回答",
        "什么意思",
        "别换",
        "我问你",
        "不是",
        "不对",
    ]
    if any(keyword in clean for keyword in clarification_keywords):
        return "听不清/澄清", "重新说明"
    return "需求探索", "资格确认"


def _build_reply(text: str, intent: str, merchant_name: str) -> str:
    replies = {
        "价格异议": "费用先不急，我先帮您判断视频号团购适不适合您的门店。",
        "明确拒绝": "好的，不打扰了，再见。",
        "稍后联系": "可以，我不多打扰。今天下午还是明天上午再跟您确认方便？",
        "加微信/发资料": "可以，我稍后把视频号团购资料和同品类案例发您，您看完再沟通。",
        "身份确认": "我是做视频号团购到店获客的，给您来电是确认门店是否需要微信同城曝光。",
        "听不清/澄清": "我简单说：我们帮门店做视频号团购，到店获客。您方便听半分钟吗？",
        "礼貌结束": "好的，不打扰了，再见。",
        "系统提示": "",
        "合作咨询": "我先说重点：帮门店设计团购套餐，再做视频号同城曝光和到店转化。",
        "效果询问": "效果主要看品类和套餐，我们会先小范围测试曝光、咨询和到店数据。",
        "找负责人": "明白，那方便帮我转给负责团购或门店运营的人吗？我简单说明一下。",
        "已有渠道": "已经做团购更好；美团偏搜索成交，视频号补微信同城推荐和私域流量。",
        "来源/隐私": "您放心，不方便我就不再联系；这边只做门店业务回访确认。",
        "低信息确认": "我简单确认一下，您现在方便听我说半分钟吗？",
        "需求探索": "我先说重点：我们帮门店做视频号团购曝光，合适再细聊。",
    }
    if intent in replies:
        return replies[intent]
    if len(text) <= 8:
        return "您好，我是本地生活服务顾问，想问下您了解视频号团购获客吗？"
    return "了解，我先确认下：您现在有兴趣了解视频号团购到店获客吗？"


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


def _llm_event_detail(strategy: str, error: str | None) -> str:
    if strategy.startswith("deepseek"):
        return "DeepSeek 已生成电话短句。"
    if error:
        return f"DeepSeek 未接管，本地规则兜底：{error}"
    return "本地规则生成电话短句。"


def _normalize_live_event(payload: dict[str, Any]) -> dict[str, object] | None:
    event_type = str(payload.get("type") or "")
    if not event_type:
        return None
    at = str(payload.get("at") or "")
    call_id = str(payload.get("callId") or "") or None
    probe_noise_events = {
        "socket_connected",
        "call_error",
        "call_disconnected",
        "hangup_before_uuid",
        "uuid_timeout",
        "frame_before_uuid",
    }
    if not call_id and event_type in probe_noise_events:
        return None
    digest_source = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {
        "id": hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:16],
        "at": at,
        "type": event_type,
        "callId": call_id,
        "text": _optional_text(payload.get("text")),
        "reply": _optional_text(payload.get("reply")),
        "strategy": _optional_text(payload.get("strategy")),
        "latencyMs": int(payload.get("latencyMs") or payload.get("synthMs") or 0),
        "detail": _optional_text(payload.get("detail") or payload.get("error")),
        "raw": payload,
    }


def _is_tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False
