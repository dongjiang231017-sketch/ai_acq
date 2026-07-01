from __future__ import annotations

import json
import re
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
_FAST_LOCAL_INTENTS = {
    "价格异议",
    "明确拒绝",
    "礼貌结束",
    "稍后联系",
    "加微信/发资料",
    "身份确认",
    "听不清/澄清",
    "系统提示",
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


def generate_realtime_reply(text: str, intent: str, merchant_name: str, fallback_reply: str) -> RealtimeReplyResult:
    if intent in _FAST_LOCAL_INTENTS:
        return RealtimeReplyResult(
            reply=fallback_reply,
            strategy="rules_fast_path",
            latency_ms=0,
            fallback_used=True,
        )
    if not deepseek_configured():
        return RealtimeReplyResult(
            reply=fallback_reply,
            strategy="rules_fallback_no_deepseek_key",
            latency_ms=0,
            fallback_used=True,
            error="DEEPSEEK_API_KEY 未配置",
        )

    started = time.perf_counter()
    future = _DEEPSEEK_EXECUTOR.submit(_request_deepseek_reply, text, intent, merchant_name)
    try:
        reply = future.result(timeout=max(0.5, settings.realtime_llm_timeout_seconds))
    except TimeoutError:
        return RealtimeReplyResult(
            reply=fallback_reply,
            strategy="rules_fallback_deepseek_timeout",
            latency_ms=int((time.perf_counter() - started) * 1000),
            fallback_used=True,
            error=f"DeepSeek 超过 {settings.realtime_llm_timeout_seconds:.1f}s 电话预算",
        )
    except Exception as exc:  # noqa: BLE001
        return RealtimeReplyResult(
            reply=fallback_reply,
            strategy="rules_fallback_deepseek_error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            fallback_used=True,
            error=_safe_error(exc),
        )

    cleaned = _clean_phone_reply(reply)
    if not cleaned:
        return RealtimeReplyResult(
            reply=fallback_reply,
            strategy="rules_fallback_empty_deepseek_reply",
            latency_ms=int((time.perf_counter() - started) * 1000),
            fallback_used=True,
            error="DeepSeek 返回空回复",
        )
    return RealtimeReplyResult(
        reply=cleaned,
        strategy="deepseek_stream_first_sentence" if settings.deepseek_stream_first_sentence else "deepseek_chat",
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _request_deepseek_reply(text: str, intent: str, merchant_name: str) -> str:
    payload = {
        "model": settings.deepseek_chat_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是电话外呼AI坐席，只输出下一句要说的话。"
                    "使用自然中文口语，只说一句短句，不要Markdown。"
                    "任务是销售视频号团购到店获客服务，并礼貌确认对方是否有兴趣。"
                    "不能自称平台官方、微信官方、视频号官方或官方合作方；只能称本地生活服务顾问。"
                    "不能承诺已合作、补贴、保底效果或未授权身份。"
                    "如果对方拒绝就礼貌结束；如果对方要求身份或来电原因，先说明身份和目的；"
                    "如果对方说忙或找别人，询问是否方便稍后联系或转给负责人。每句尽量不超过36个中文字符。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"商家：{merchant_name or '客户门店'}\n"
                    f"本地意图：{intent}\n"
                    f"客户刚说：{text}\n"
                    "请给出下一句电话回复。"
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
