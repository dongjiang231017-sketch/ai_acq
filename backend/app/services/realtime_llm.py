from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class RealtimeReplyResult:
    reply: str
    strategy: str
    latency_ms: int
    fallback_used: bool = False
    error: str | None = None


_DEEPSEEK_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-acq-deepseek-realtime")
_DEEPSEEK_BACKOFF_LOCK = threading.Lock()
_DEEPSEEK_BACKOFF_UNTIL = 0.0
_DEEPSEEK_BACKOFF_SECONDS = 45.0
_FAST_LOCAL_INTENTS = {
    "明确拒绝",
    "礼貌结束",
    "稍后联系",
    "系统提示",
}
_CONTEXT_LOCAL_FIRST_INTENTS = {
    "价格异议",
    "加微信/发资料",
    "身份确认",
    "听不清/澄清",
    "合作咨询",
    "效果询问",
    "找负责人",
    "已有渠道",
    "来源/隐私",
    "低信息确认",
    "需求探索",
}


def deepseek_configured() -> bool:
    return bool(settings.deepseek_api_key.strip())


def generate_realtime_reply(
    text: str,
    intent: str,
    merchant_name: str,
    fallback_reply: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> RealtimeReplyResult:
    history = conversation_history or []
    if intent in _FAST_LOCAL_INTENTS:
        return RealtimeReplyResult(
            reply=fallback_reply,
            strategy="rules_fast_path",
            latency_ms=0,
            fallback_used=True,
        )
    contextual_reply = _build_contextual_local_reply(text, intent, merchant_name, fallback_reply, history)
    if intent in _CONTEXT_LOCAL_FIRST_INTENTS:
        return RealtimeReplyResult(
            reply=contextual_reply,
            strategy="local_context_fast_path",
            latency_ms=0,
            fallback_used=True,
        )
    if _deepseek_in_backoff():
        return RealtimeReplyResult(
            reply=contextual_reply,
            strategy="local_context_deepseek_backoff",
            latency_ms=0,
            fallback_used=True,
            error="DeepSeek 最近超时，电话会话内临时使用本地上下文策略。",
        )
    if not deepseek_configured():
        return RealtimeReplyResult(
            reply=contextual_reply,
            strategy="local_context_no_deepseek_key",
            latency_ms=0,
            fallback_used=True,
            error="DEEPSEEK_API_KEY 未配置",
        )

    started = time.perf_counter()
    future = _DEEPSEEK_EXECUTOR.submit(_request_deepseek_reply, text, intent, merchant_name, history)
    try:
        reply = future.result(timeout=max(0.5, settings.realtime_llm_timeout_seconds))
    except TimeoutError:
        _open_deepseek_backoff()
        return RealtimeReplyResult(
            reply=contextual_reply,
            strategy="local_context_deepseek_timeout",
            latency_ms=int((time.perf_counter() - started) * 1000),
            fallback_used=True,
            error=f"DeepSeek 超过 {settings.realtime_llm_timeout_seconds:.1f}s 电话预算",
        )
    except Exception as exc:  # noqa: BLE001
        _open_deepseek_backoff()
        return RealtimeReplyResult(
            reply=contextual_reply,
            strategy="local_context_deepseek_error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            fallback_used=True,
            error=_safe_error(exc),
        )

    cleaned = _clean_phone_reply(reply)
    if not cleaned:
        return RealtimeReplyResult(
            reply=contextual_reply,
            strategy="local_context_empty_deepseek_reply",
            latency_ms=int((time.perf_counter() - started) * 1000),
            fallback_used=True,
            error="DeepSeek 返回空回复",
        )
    return RealtimeReplyResult(
        reply=cleaned,
        strategy="deepseek_stream_first_sentence" if settings.deepseek_stream_first_sentence else "deepseek_chat",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _deepseek_in_backoff() -> bool:
    with _DEEPSEEK_BACKOFF_LOCK:
        return time.monotonic() < _DEEPSEEK_BACKOFF_UNTIL


def _open_deepseek_backoff() -> None:
    global _DEEPSEEK_BACKOFF_UNTIL
    with _DEEPSEEK_BACKOFF_LOCK:
        _DEEPSEEK_BACKOFF_UNTIL = time.monotonic() + _DEEPSEEK_BACKOFF_SECONDS


def _build_contextual_local_reply(
    text: str,
    intent: str,
    merchant_name: str,
    fallback_reply: str,
    conversation_history: list[dict[str, str]],
) -> str:
    clean = text.strip()
    compact = re.sub(r"[\s。！？?!，,、.]+", "", clean.lower())
    last_assistant = _last_history_content(conversation_history, "assistant")
    last_user = _last_history_content(conversation_history, "user")
    merchant = merchant_name.strip() or "您的门店"

    if intent == "身份确认":
        if compact in {"喂", "喂喂", "你好"}:
            return _avoid_repeat("您好，我做视频号团购获客，方便说半分钟吗？", last_assistant)
        if _has_any(clean, ["做什么", "做啥", "干嘛", "什么事", "什么意思"]):
            return _avoid_repeat("我们做视频号团购，帮门店引附近客到店。", last_assistant)
        if _has_any(clean, ["你是谁", "哪里", "什么公司", "你们"]):
            return _avoid_repeat("我是本地生活服务顾问，做视频号团购到店获客。", last_assistant)
        return _avoid_repeat("我做视频号团购获客，想确认您方便了解吗？", last_assistant)

    if intent == "加微信/发资料":
        if _has_any(last_assistant, ["案例", "资料", "微信"]):
            return "好的，我按微信发资料，电话里不多占您时间。"
        if _has_any(clean, ["怎么", "哪里", "发到", "短信"]):
            return _avoid_repeat("可以，短信或微信发案例和流程给您。", last_assistant)
        return _avoid_repeat("可以，稍后微信发案例和流程给您。", last_assistant)

    if intent == "听不清/澄清":
        if _has_any(clean + last_user, ["付费", "要钱", "花钱", "付钱", "费用", "收费", "价格"]):
            return _avoid_repeat("是要付费，具体看套餐和投放，不合适不建议做。", last_assistant)
        if _has_any(clean + last_user, ["保证", "承诺", "保底"]):
            return _avoid_repeat("不能空口保证，只能先测曝光、咨询和到店数据。", last_assistant)
        if _has_any(clean, ["信号", "断断续续", "太慢", "反应慢", "卡"]):
            return _avoid_repeat("抱歉可能信号不稳，我短说：视频号团购帮门店引流到店。", last_assistant)
        if _has_any(clean, ["不是", "不对"]):
            return _avoid_repeat("我换个说法：不是卖广告，是做可下单的团购入口。", last_assistant)
        if _has_any(clean, ["听不懂", "什么意思", "说什么", "明白什么"]):
            return _avoid_repeat("我短说：视频号团购，帮附近客户下单到店。", last_assistant)
        return _avoid_repeat("我再短说：做视频号团购，帮门店拿到店客。", last_assistant)

    if intent == "低信息确认":
        if _has_any(last_assistant, ["发资料", "短信", "案例"]):
            return _avoid_repeat("好的，我发案例资料，您看完再决定。", last_assistant)
        if _has_any(last_assistant, ["方便", "半分钟", "可以吗"]):
            return _avoid_repeat("那我说重点：先做团购套餐，再测到店。", last_assistant)
        return _avoid_repeat("我接着说：先小范围测曝光和到店。", last_assistant)

    if intent == "价格异议":
        if _has_any(clean, ["付费", "要钱", "花钱", "付钱"]):
            return _avoid_repeat("是要付费，具体看套餐和投放，不合适不建议做。", last_assistant)
        return _avoid_repeat("费用看套餐和投放，先判断适不适合再报价。", last_assistant)

    if intent == "效果询问":
        return _avoid_repeat("先测曝光、咨询、到店数据，不跟您空口保证。", last_assistant)

    if intent == "合作咨询":
        if _has_any(clean, ["怎么发", "资料"]):
            return _avoid_repeat("我先发流程和案例，您看完再判断。", last_assistant)
        return _avoid_repeat("先看品类，定团购套餐，小范围测试。", last_assistant)

    if intent == "已有渠道":
        return _avoid_repeat("不冲突，视频号主要补微信同城流量。", last_assistant)

    if intent == "找负责人":
        return _avoid_repeat("方便转给负责团购的人吗？我简单说。", last_assistant)

    if intent == "来源/隐私":
        return _avoid_repeat("不方便我就标记不再联系，只做门店业务沟通。", last_assistant)

    if intent == "需求探索":
        if _has_any(clean, ["都这样", "都这么", "每家", "都一样"]):
            return _avoid_repeat("不是每家都一样，要看品类，所以先小范围测。", last_assistant)
        if _has_any(clean, ["靠谱", "真的吗", "真的假的", "有没有用", "能不能"]):
            return _avoid_repeat("能不能做要看品类，我建议先测到店数据。", last_assistant)
        if _has_any(clean, ["怎么", "如何", "流程", "合作"]):
            return _avoid_repeat("先看品类和客单价，再定视频号团购套餐。", last_assistant)
        if _has_any(clean, ["效果", "客流", "到店", "有没有用"]):
            return _avoid_repeat("关键看套餐吸引力，先小范围测到店。", last_assistant)
        if _has_any(clean, ["费用", "多少钱", "价格", "收费"]):
            return _avoid_repeat("价格要看套餐和投放节奏，不先硬报。", last_assistant)
        if _has_any(clean, ["付费", "要钱", "花钱", "付钱"]):
            return _avoid_repeat("是要付费，具体看套餐和投放，不合适不建议做。", last_assistant)
        if _has_any(clean, ["保证", "承诺", "保底"]):
            return _avoid_repeat("不能空口保证，只能先测曝光、咨询和到店数据。", last_assistant)
        if _has_any(last_assistant, ["更想提升到店客流", "还是先了解怎么做"]):
            return _avoid_repeat("那我按到店说：用团购套餐吸引附近用户下单。", last_assistant)
        return _avoid_repeat(f"{merchant}更关心到店客流，还是怎么合作？", last_assistant)

    return _avoid_repeat(fallback_reply, last_assistant)


def _last_history_content(history: list[dict[str, str]], role: str) -> str:
    for turn in reversed(history):
        if (turn.get("role") or "").strip().lower() == role:
            return str(turn.get("content") or "").strip()
    return ""


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _avoid_repeat(reply: str, last_assistant: str) -> str:
    if not last_assistant or reply.strip() != last_assistant.strip():
        return reply
    alternatives = [
        "我换个说法：用视频号团购帮门店拿到店客。",
        "简单讲，先做套餐，再看曝光和到店数据。",
        "您主要想先了解效果，还是费用？",
    ]
    for alternative in alternatives:
        if alternative != last_assistant.strip():
            return alternative
    return reply


def _request_deepseek_reply(text: str, intent: str, merchant_name: str, conversation_history: list[dict[str, str]] | None = None) -> str:
    recent_history = _format_conversation_history(conversation_history or [])
    payload = {
        "model": settings.deepseek_chat_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是电话外呼AI坐席，只输出下一句要说的话。"
                    "使用自然中文口语，只说一句短句，不要Markdown，不要复读上一轮话术。"
                    "任务是销售视频号团购到店获客服务，并礼貌确认对方是否有兴趣。"
                    "不能自称平台官方、微信官方、视频号官方或官方合作方；只能称本地生活服务顾问。"
                    "不能承诺已合作、补贴、保底效果或未授权身份。"
                    "必须先回答客户当前问题，再轻轻推进下一步。"
                    "客户问你是谁、做什么，就直接说明身份和服务；客户问效果、费用、怎么做、怎么发资料，"
                    "就针对问题回答；客户说没听懂，就换更短说法；客户只是嗯、好、可以，要承接上一轮继续说重点。"
                    "如果对方拒绝就礼貌结束；如果对方说忙或找别人，询问稍后联系或转给负责人。"
                    "每句尽量不超过36个中文字符。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"商家：{merchant_name or '客户门店'}\n"
                    f"本地意图：{intent}\n"
                    f"最近对话：\n{recent_history}\n"
                    f"客户刚说：{text}\n"
                    "请给出下一句电话回复，必须像真人顺着客户的话回答，不要像录播话术。"
                ),
            },
        ],
        "max_tokens": settings.deepseek_max_tokens,
        "stream": settings.deepseek_stream_first_sentence,
        "thinking": {"type": "disabled"},
    }
    request = urllib.request.Request(
        _deepseek_chat_url(),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.deepseek_api_key.strip()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout_seconds = max(0.5, min(settings.deepseek_timeout_seconds, settings.realtime_llm_timeout_seconds))
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        if settings.deepseek_stream_first_sentence:
            return _read_streaming_content(response)
        data = json.loads(response.read().decode("utf-8"))
    return _extract_message_content(data)


def _deepseek_chat_url() -> str:
    return settings.deepseek_base_url.strip().rstrip("/") + "/chat/completions"


def _read_streaming_content(response: Any) -> str:
    chunks: list[str] = []
    max_chars = max(24, settings.realtime_reply_max_chars)
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="ignore").strip()
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        delta = payload.get("choices", [{}])[0].get("delta", {})
        content = str(delta.get("content") or "")
        if not content:
            continue
        chunks.append(content)
        current = "".join(chunks)
        if _can_return_first_sentence(current, max_chars):
            break
    return "".join(chunks)


def _extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "")


def _format_conversation_history(history: list[dict[str, str]]) -> str:
    rows: list[str] = []
    for turn in history[-8:]:
        role = (turn.get("role") or "").strip().lower()
        content = _clean_history_text(turn.get("content") or "")
        if not content:
            continue
        label = "客户" if role == "user" else "AI"
        rows.append(f"{label}：{content}")
    return "\n".join(rows) if rows else "无"


def _clean_history_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned[:80]


def _can_return_first_sentence(text: str, max_chars: int) -> bool:
    cleaned = _clean_phone_reply(text)
    if len(cleaned) >= max_chars:
        return True
    return len(cleaned) >= 12 and bool(re.search(r"[。！？!?]$", cleaned))


def _clean_phone_reply(reply: str) -> str:
    cleaned = re.sub(r"\s+", " ", reply).strip()
    cleaned = cleaned.strip("`*_#- \t\r\n")
    cleaned = cleaned.replace("AI：", "").replace("客服：", "").strip()
    max_chars = max(24, settings.realtime_reply_max_chars)
    if len(cleaned) <= max_chars:
        return cleaned
    sentence_match = re.search(r"^(.{12,%d}?[。！？!?])" % max_chars, cleaned)
    if sentence_match:
        return sentence_match.group(1).strip()
    return cleaned[:max_chars].rstrip("，,；;、 ") + "。"


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        detail = exc.read(300).decode("utf-8", errors="ignore")
        return f"DeepSeek HTTP {exc.code}: {detail}"
    if isinstance(exc, urllib.error.URLError):
        return f"DeepSeek URL error: {exc.reason}"
    return str(exc)
