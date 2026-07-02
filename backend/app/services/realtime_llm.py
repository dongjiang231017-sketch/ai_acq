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
from app.services.realtime_sales_brain import render_sales_reply


@dataclass(frozen=True)
class RealtimeReplyResult:
    reply: str
    strategy: str
    latency_ms: int
    fallback_used: bool = False
    error: str | None = None


@dataclass(frozen=True)
class DialogueSignal:
    topic: str
    direct_question: bool = False
    complaint: bool = False
    from_context_repair: bool = False


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
}


def deepseek_configured() -> bool:
    return bool(settings.deepseek_api_key.strip())


def generate_realtime_reply(
    text: str,
    intent: str,
    merchant_name: str,
    fallback_reply: str,
    conversation_history: list[dict[str, str]] | None = None,
    stage_instruction: str = "",
) -> RealtimeReplyResult:
    history = conversation_history or []
    if intent in _FAST_LOCAL_INTENTS:
        return RealtimeReplyResult(
            reply=fallback_reply,
            strategy="rules_fast_path",
            latency_ms=0,
            fallback_used=True,
        )
    signal = _analyze_dialogue_signal(text, intent, history)
    brain_reply = render_sales_reply(text, intent, merchant_name, fallback_reply, history)
    contextual_reply = brain_reply.reply
    if intent in _CONTEXT_LOCAL_FIRST_INTENTS or _should_answer_locally_first(signal):
        return RealtimeReplyResult(
            reply=contextual_reply,
            strategy=brain_reply.strategy,
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
    future = _DEEPSEEK_EXECUTOR.submit(_request_deepseek_reply, text, intent, merchant_name, history, stage_instruction)
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
    signal: DialogueSignal | None = None,
) -> str:
    clean = text.strip()
    compact = re.sub(r"[\s。！？?!，,、.]+", "", clean.lower())
    last_assistant = _last_history_content(conversation_history, "assistant")
    last_user = _last_history_content(conversation_history, "user")
    merchant = merchant_name.strip() or "您的门店"
    signal = signal or _analyze_dialogue_signal(clean, intent, conversation_history)

    if signal.topic == "identity":
        if compact in {"喂", "喂喂", "你好"}:
            return _avoid_repeat("您好，我在。我是做视频号团购到店获客的，给您来电是确认微信同城曝光这块。", last_assistant)
        if _has_any(clean, ["做什么", "做啥", "干嘛", "什么事", "什么意思"]):
            return _avoid_repeat("我们做视频号团购，帮门店引附近客到店。", last_assistant)
        return _avoid_repeat(
            "我是做视频号团购到店获客的，给您来电是确认门店是否需要微信同城曝光。",
            last_assistant,
            ["不是平台官方，是做门店团购获客服务。"],
        )

    if signal.topic == "repetition_complaint":
        history_topic = _infer_history_topic(clean, last_user, last_assistant)
        if history_topic == "price":
            return _avoid_repeat("明白，我不重复。费用看套餐和投放，先判断适不适合再报价。", last_assistant)
        if history_topic == "guarantee":
            return _avoid_repeat("明白，我直接答：效果不能保底，只能先测曝光、咨询和到店。", last_assistant)
        if history_topic in {"existing_channel", "channel_difference"} or _is_channel_difference_question(clean):
            return _avoid_repeat("明白，不提资料了。美团偏搜索下单，视频号偏微信同城和私域补充。", last_assistant)
        return _avoid_repeat("明白，我不重复刚才那句。您是想听费用、效果，还是和美团区别？", last_assistant)

    if signal.topic == "direct_answer_only":
        if _is_channel_difference_question(clean):
            return _avoid_repeat("不发资料，我直接说：美团偏搜索成交，视频号偏微信同城曝光和私域沉淀。", last_assistant)
        if _is_price_question(clean):
            return _avoid_repeat("不发资料，直接说费用：这是付费服务，按套餐和投放节奏报价。", last_assistant)
        if _has_any(clean, ["效果", "客流", "到店", "有没有用", "靠谱吗"]):
            return _avoid_repeat("不发资料，直接说效果：先测曝光、咨询和到店数据，不空口保底。", last_assistant)
        return _avoid_repeat("明白，不发资料。您直接问我费用、效果或流程，我就按问题答。", last_assistant)

    if signal.topic == "channel_difference":
        return _avoid_repeat(
            "美团偏搜索、评价和平台成交；视频号偏微信同城内容和私域沉淀，是补充不是替代。",
            last_assistant,
            ["简单说，美团像货架搜索，视频号更像微信同城推荐和私域入口。"],
        )

    if signal.topic == "price":
        return _avoid_repeat(
            "是要付费，具体看套餐和投放，不合适不建议做。",
            last_assistant,
            ["您问费用对吧，是付费服务，但先看适不适合再报价。"],
        )

    if signal.topic == "guarantee":
        return _avoid_repeat(
            "不能空口保证，只能先测曝光、咨询和到店数据。",
            last_assistant,
            ["您问保障对吧，不能保底，只能先用数据测试效果。"],
        )

    if signal.topic == "effect_goal":
        return _avoid_repeat("那就按到店目标，先做引流团购，小范围测到店数据。", last_assistant)

    if signal.topic == "process":
        return _avoid_repeat(
            "流程是先看品类，再定团购套餐，小范围投放测试。",
            last_assistant,
            ["简单说，先设计团购套餐，再投同城曝光测试。"],
        )

    if signal.topic == "materials":
        if _has_any(last_assistant, ["案例", "资料", "微信"]):
            return "好的，我按微信发资料，电话里不多占您时间。"
        return _avoid_repeat("可以，稍后微信发案例和流程给您。", last_assistant)

    if signal.topic == "quality":
        return _avoid_repeat(
            "我放慢点说：视频号团购，就是帮门店做套餐和同城到店获客。",
            last_assistant,
            ["我换短点说：做视频号团购，主要是拿微信同城到店流量。"],
        )

    if signal.topic == "source":
        return _avoid_repeat("不方便我就不再联系，这通只做门店业务沟通。", last_assistant)

    if signal.topic == "owner":
        return _avoid_repeat("方便转给负责团购的人吗？我简单说。", last_assistant)

    if signal.topic == "existing_channel":
        return _avoid_repeat(
            "不冲突，美团偏搜索成交，视频号主要补微信同城推荐和私域流量。",
            last_assistant,
            ["已经做美团也可以，视频号是补微信生态，不替代原渠道。"],
        )

    if signal.topic == "low_info":
        if _has_any(last_assistant, ["发资料", "短信", "案例"]):
            return _avoid_repeat("好的，我发案例资料，您看完再决定。", last_assistant)
        if _has_any(last_assistant, ["方便", "半分钟", "可以吗"]):
            return _avoid_repeat("那我说重点：先做团购套餐，再测到店。", last_assistant)
        return _avoid_repeat("我接着说：先小范围测曝光和到店。", last_assistant)

    if signal.topic == "context_repair":
        history_topic = _infer_history_topic(clean, last_user, last_assistant)
        if history_topic == "price":
            return _avoid_repeat("您问费用对吧，是付费服务，但先看适不适合再报价。", last_assistant)
        if history_topic == "guarantee":
            return _avoid_repeat("您问保障对吧，不能保底，只能先用数据测试效果。", last_assistant)
        if history_topic == "process":
            return _avoid_repeat("您问怎么做对吧，先定团购套餐，再投同城曝光。", last_assistant)
        if history_topic == "identity":
            return _avoid_repeat("我是本地生活服务顾问，做视频号团购到店获客。", last_assistant)
        return _avoid_repeat("我换个说法：视频号团购是帮门店做可下单套餐，把附近客引到店。", last_assistant)

    if intent == "身份确认":
        if compact in {"喂", "喂喂", "你好"}:
            return _avoid_repeat("您好，我在。我是做视频号团购到店获客的，给您来电是确认微信同城曝光这块。", last_assistant)
        if _has_any(clean, ["做什么", "做啥", "干嘛", "什么事", "什么意思"]):
            return _avoid_repeat("我们做视频号团购，帮门店引附近客到店。", last_assistant)
        if _has_any(clean, ["你是谁", "哪里", "什么公司", "你们"]):
            return _avoid_repeat("我是做视频号团购到店获客的，给您来电是确认门店是否需要微信同城曝光。", last_assistant)
        return _avoid_repeat("我是做视频号团购到店获客的，主要帮门店做微信同城曝光。", last_assistant)

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
            return _avoid_repeat("我放慢点说：视频号团购，就是帮门店做套餐和同城到店获客。", last_assistant)
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
        return _avoid_repeat(
            "不冲突，美团偏搜索成交，视频号主要补微信同城推荐和私域流量。",
            last_assistant,
        )

    if intent == "找负责人":
        return _avoid_repeat("方便转给负责团购的人吗？我简单说。", last_assistant)

    if intent == "来源/隐私":
        return _avoid_repeat("不方便我就不再联系，这通只做门店业务沟通。", last_assistant)

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


def _analyze_dialogue_signal(text: str, intent: str, conversation_history: list[dict[str, str]]) -> DialogueSignal:
    clean = text.strip()
    compact = re.sub(r"[\s。！？?!，,、.]+", "", clean.lower())
    last_assistant = _last_history_content(conversation_history, "assistant")
    last_user = _last_history_content(conversation_history, "user")

    if compact in {"喂", "喂喂", "你好", "您好", "在", "在在", "你谁", "谁", "谁啊", "谁呀", "哪位", "您哪位", "你哪位"} or intent == "身份确认":
        return DialogueSignal("identity", direct_question=True)

    if _has_any(clean, ["重复", "一直说", "总是说", "总说", "老说", "老是说", "别重复", "不要重复", "不要总", "你怎么总", "你老是"]):
        return DialogueSignal("repetition_complaint", direct_question=True, complaint=True)

    if _declines_materials_only(clean):
        return DialogueSignal("direct_answer_only", direct_question=True)

    if _is_channel_difference_question(clean):
        return DialogueSignal("channel_difference", direct_question=True)

    if _has_any(
        clean,
        ["信号", "断断续续", "太慢", "反应慢", "卡", "听不清", "听不到", "听不见", "没听清", "没听到"],
    ):
        return DialogueSignal("quality", complaint=True)

    if _has_any(clean, ["我问你", "没解决", "没回答", "别换", "不是问这个", "回答我"]):
        history_topic = _infer_history_topic(clean, last_user, last_assistant)
        if history_topic != "unknown":
            return DialogueSignal(history_topic, direct_question=True, from_context_repair=True)
        return DialogueSignal("context_repair", direct_question=True, from_context_repair=True)

    if _is_price_question(clean):
        return DialogueSignal("price", direct_question=True)

    if _has_any(clean, ["保证", "承诺", "保底"]):
        return DialogueSignal("guarantee", direct_question=True)

    if _has_any(last_assistant, ["更关心到店客流", "还是怎么合作", "效果，还是费用"]) and _has_any(
        clean,
        ["到店", "客流", "引流", "获客"],
    ):
        return DialogueSignal("effect_goal")

    if _has_any(clean, ["效果", "客流", "到店", "曝光", "转化", "能带来", "有用吗", "靠谱吗", "有没有用"]):
        return DialogueSignal("guarantee", direct_question=True)

    if _has_any(clean, ["你是谁", "你谁", "谁啊", "谁呀", "哪位", "您哪位", "什么公司", "哪里", "你们", "来电原因", "干嘛", "做什么", "做啥", "什么事"]):
        return DialogueSignal("identity", direct_question=True)

    if _has_any(clean, ["微信", "资料", "发我", "发给我", "给我发", "怎么发", "发哪里", "发到", "加一下", "短信"]):
        return DialogueSignal("materials")

    if _has_any(
        clean,
        [
            "怎么做",
            "怎么合作",
            "怎么弄",
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
        ],
    ):
        return DialogueSignal("process", direct_question=True)

    if _has_any(clean, ["老板不在", "负责人不在", "店长不在", "找老板", "找负责人", "找店长", "不是我负责", "我不负责", "转给"]):
        return DialogueSignal("owner")

    if _has_any(clean, ["已经做", "在做", "做过", "有做", "抖音团购", "美团", "大众点评", "小红书", "高德"]):
        return DialogueSignal("existing_channel")

    if _has_any(clean, ["哪来的", "哪里来的", "怎么知道", "谁给", "电话来源", "号码来源", "我的号码", "个人信息"]):
        return DialogueSignal("source", direct_question=True)

    if compact in {"在", "嗯", "嗯嗯", "啊", "哦", "噢", "好", "好的", "是", "是的", "对", "对的", "可以", "行", "估计是"}:
        return DialogueSignal("low_info")

    if _has_any(clean, ["不是", "不对", "听不懂", "什么意思", "说什么", "明白什么"]):
        return DialogueSignal("context_repair", direct_question=True, from_context_repair=True)

    return DialogueSignal("open_question" if intent == "需求探索" else "intent_" + intent)


def _should_answer_locally_first(signal: DialogueSignal) -> bool:
    return signal.topic in {
        "identity",
        "price",
        "guarantee",
        "effect_goal",
        "process",
        "materials",
        "quality",
        "source",
        "owner",
        "existing_channel",
        "channel_difference",
        "low_info",
        "context_repair",
        "repetition_complaint",
        "direct_answer_only",
    }


def _is_price_question(text: str) -> bool:
    return _has_any(text, ["多少钱", "费用", "价格", "收费", "贵", "付费", "要钱", "花钱", "付钱"])


def _is_channel_difference_question(text: str) -> bool:
    return _has_any(text, ["美团区别", "和美团", "跟美团", "比美团", "美团有啥区别", "美团有什么区别", "抖音区别", "和抖音", "跟抖音"])


def _declines_materials_only(text: str) -> bool:
    if not _has_any(text, ["不需要资料", "不用资料", "不要资料", "别发资料", "不用发资料", "不用加微信", "不加微信", "直接回答", "说重点", "讲重点"]):
        return False
    return not _has_any(text, ["别打", "别联系", "不要打", "拉黑", "没兴趣", "挂了"])


def _infer_history_topic(current_text: str, last_user: str, last_assistant: str) -> str:
    combined = " ".join([current_text, last_user, last_assistant])
    if _is_price_question(combined):
        return "price"
    if _is_channel_difference_question(combined) or _has_any(combined, ["美团", "抖音团购", "大众点评", "已有渠道"]):
        return "channel_difference"
    if _has_any(combined, ["保证", "承诺", "保底", "效果", "客流", "到店", "曝光", "转化", "有用吗", "靠谱吗", "测曝光", "到店数据"]):
        return "guarantee"
    if _has_any(combined, ["怎么做", "怎么合作", "流程", "套餐", "投放", "具体说", "详细讲", "讲解"]):
        return "process"
    if _has_any(combined, ["你是谁", "什么公司", "本地生活服务顾问", "做视频号团购", "来电原因"]):
        return "identity"
    if _has_any(combined, ["微信", "资料", "案例", "短信"]):
        return "materials"
    return "unknown"


def _last_history_content(history: list[dict[str, str]], role: str) -> str:
    for turn in reversed(history):
        if (turn.get("role") or "").strip().lower() == role:
            return str(turn.get("content") or "").strip()
    return ""


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _avoid_repeat(reply: str, last_assistant: str, topic_alternatives: list[str] | None = None) -> str:
    if not last_assistant or reply.strip() != last_assistant.strip():
        return reply
    for alternative in topic_alternatives or []:
        if alternative != last_assistant.strip():
            return alternative
    alternatives = [
        "我换个角度说：视频号团购补的是微信同城和私域到店。",
        "简单讲，先做套餐，再看曝光、咨询和到店数据。",
        "您主要想先听费用、效果，还是和美团区别？",
    ]
    for alternative in alternatives:
        if alternative != last_assistant.strip():
            return alternative
    return reply


def _request_deepseek_reply(
    text: str,
    intent: str,
    merchant_name: str,
    conversation_history: list[dict[str, str]] | None = None,
    stage_instruction: str = "",
) -> str:
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
                    "客户说不要资料、不加微信、直接回答、别重复时，本轮停止推进资料和微信，只回答问题。"
                    "客户重复追问时必须换角度回答，不要复读上一轮。客户插话后直接接着答，不解释上一句为什么停了。"
                    "语气要像真人电销：先承接情绪，再给一个短解释，必要时问一个选择题。"
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
                    f"销售状态：{stage_instruction or '无'}\n"
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
