from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.realtime_call_state import latest_realtime_call_events, reduce_realtime_call_events
from app.services.realtime_text_normalizer import normalize_realtime_sales_text


@dataclass(frozen=True)
class SalesTurnPlan:
    topic: str
    emotion: str
    stage: str
    answer_mode: str
    should_advance: bool
    repeat_risk: bool
    direct_answer_only: bool
    customer_summary: str


@dataclass(frozen=True)
class SalesBrainReply:
    reply: str
    strategy: str
    plan: SalesTurnPlan


EMOTION_ACKS = {
    "busy": ["我短说。", "不耽误您。"],
    "annoyed": ["我直接答重点。", "不硬推。"],
    "skeptical": ["您这个担心正常。", "对，这点要讲清楚。"],
    "confused": ["我换短点说。", "我说简单点。"],
    "interested": ["可以，我说重点。", "好，那我按重点说。"],
    "neutral": ["", ""],
}

TOPIC_ANSWERS = {
    "identity": [
        "我是做视频号团购到店获客的，想看您门店有没有微信同城曝光需求。",
        "我这边是本地生活服务顾问，主要做视频号团购和到店获客。",
        "简单说，我是帮门店做视频号团购获客的，不是平台官方。",
    ],
    "price": [
        "是付费服务，基础费用要看套餐和投放节奏，我不在电话里乱报。",
        "费用按套餐设计和投放范围定，适合再给明确报价。",
        "要收费，但先看品类和客单价，能做再谈具体费用。",
    ],
    "roi_risk": [
        "这个风险要控制：先小预算测曝光、咨询和到店，达不到就不放大投入。",
        "不建议一上来花大成本。先按小测试跑数据，客户量不达标就及时停。",
    ],
    "guarantee": [
        "效果不能空口保底，只能先测曝光、咨询和到店数据。",
        "不能承诺一定成交，靠谱的做法是小范围测试数据再放大。",
    ],
    "channel_difference": [
        "美团偏搜索下单，视频号偏微信同城推荐和私域沉淀，是补充不是替代。",
        "简单说，美团像货架搜索；视频号更像微信同城内容推荐和私域入口。",
    ],
    "advantage": [
        "优势是微信同城内容曝光、私域沉淀和套餐核销，补的是美团之外的入口。",
        "您用美团解决搜索下单，我们补微信同城推荐和老客沉淀，不冲突。",
        "不是替代美团，是多一个微信里的到店入口，适合做补充流量。",
    ],
    "exposure_detail": [
        "同城曝光就是把团购套餐放到微信视频号同城入口，附近用户刷到内容或团购券后进门店页下单核销。",
        "简单说，不是只拍视频；核心是同城内容曝光加团购券入口，把附近用户引到店。",
    ],
    "process": [
        "流程三步：先看品类和客单价，再设计可核销团购套餐，最后小范围测曝光和到店。",
        "先判断门店适不适合，再做团购套餐和页面，小范围投放看数据。",
        "团购套餐就是客户能线上下单、到店核销的优惠套餐。",
    ],
    "need_confirmed": [
        "对，您刚才说的是新客到店。那就按到店目标走：先做团购套餐和同城曝光，小范围测到店数据。",
        "明白，您的重点是新客到店。后面就围绕到店客流做套餐、曝光和核销数据，不再反复问需求。",
    ],
    "visibility": [
        "客户不一定主动搜索；视频号有同城推荐和团购券入口，视频只是曝光承载。",
        "需要一点视频内容承载，同时走同城推荐和团购券入口；不是天天拍大片。",
        "不搜索也有推荐流机会；客户能从门店主页和团购券入口看到，视频不用重拍很多。",
    ],
    "materials": [
        "可以，方便加个微信吗？我微信上把案例和费用发您。",
        "可以发，先确认下加微信方便吗？后面微信上继续聊。",
    ],
    "owner": [
        "方便转给负责团购或门店运营的人吗？我只说重点。",
        "那我不多讲，麻烦转给负责到店获客的人更合适。",
    ],
    "source": [
        "不方便我就不再联系，这通只做门店业务沟通。",
        "您介意的话我马上结束，只做门店业务沟通。",
    ],
    "quality": [
        "视频号团购，就是帮门店做可下单套餐，再用微信同城曝光引到店。",
        "我短说：做团购套餐加微信同城曝光，目标是到店客。",
    ],
    "correction": [
        "是我刚才理解错了。您是想问我是谁，还是让我直接说来电目的？",
        "对，是我刚才猜错了。您刚才是问身份，还是问这通电话具体干嘛？",
    ],
    "rejection": [
        "好的，不打扰了，再见。",
        "那我不打扰了，再见。",
    ],
    "busy": [
        "那我不展开，您看今天晚点还是明天上午方便？",
        "可以，我稍后再联系，别影响您现在忙。",
    ],
    "open_need": [
        "我先确认一个点，您现在更想提升到店客流，还是多一个微信曝光入口？",
        "那我问一句，您门店现在更缺新客到店，还是团购套餐转化？",
    ],
}

ADVANCE_LINES = {
    "identity": "",
    "price": "您更关心基础费用，还是先看适不适合？",
    "roi_risk": "",
    "guarantee": "可以先拿小测试看数据，不用一上来做大投入。",
    "channel_difference": "已有美团也能做补充，不冲突。",
    "advantage": "如果您已有美团，就把视频号当补充测试，不替代原渠道。",
    "exposure_detail": "",
    "process": "如果品类合适，再看套餐怎么设计。",
    "need_confirmed": "",
    "visibility": "",
    "quality": "您更想听费用、效果，还是和美团区别？",
    "open_need": "",
}


def render_sales_reply(
    text: str,
    intent: str,
    merchant_name: str,
    fallback_reply: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> SalesBrainReply:
    history = conversation_history or []
    normalization = normalize_realtime_sales_text(text)
    customer_text = normalization.normalized_text or text
    plan = plan_sales_turn(customer_text, intent, history)
    last_assistant = _last_history_content(history, "assistant")
    recent_assistants = _recent_history_contents(history, "assistant", limit=5)
    answers = TOPIC_ANSWERS.get(plan.topic) or []
    answer = _choose_variant(answers, customer_text, last_assistant, recent_assistants) if answers else fallback_reply
    compact = re.sub(r"[\s。！？?!，,、.]+", "", customer_text.lower())
    if normalization.has_fix("group_buying_package"):
        answer = "不是4G套餐，是团购套餐，就是客户线上下单、到店核销的优惠套餐。"
    if plan.topic == "identity" and _recently_answered_identity(history):
        answer = "简单说，我是做视频号团购到店获客服务的，主要确认微信同城曝光需求。"
    if plan.topic == "identity" and compact in {"喂", "喂喂", "你好", "您好"}:
        if _recently_answered_identity(history):
            answer = "我在，刚才说的是视频号团购到店获客，主要确认微信同城曝光需求。"
        else:
            answer = "您好，我在。我是做视频号团购到店获客的，给您来电是确认微信同城曝光这块。"
    if plan.topic == "identity" and _has_any(text, ["干嘛", "打电话", "什么事", "来电原因", "为什么"]):
        answer = (
            "简单说，我是做视频号团购到店获客服务的，确认微信同城曝光需求。"
            if _recently_answered_identity(history)
            else "我是做视频号团购到店获客的，给您来电是确认门店是否需要微信同城曝光。"
        )
    ack = _choose_variant(EMOTION_ACKS.get(plan.emotion, EMOTION_ACKS["neutral"]), customer_text + intent, last_assistant, recent_assistants)
    if plan.direct_answer_only and plan.topic == "open_need":
        answer = "不推材料，我直接答。您问费用、效果或流程，我就按这个说。"
    if plan.direct_answer_only and plan.topic == "quality":
        answer = "我不重复。您问费用、效果或美团区别，我按这个答。"
    if plan.topic == "quality" and _has_any(text, ["没解决", "没回答", "不是问这个", "回答我"]):
        answer = "我刚才没答到点。您是问费用、效果、流程，还是和美团区别？"
    if plan.topic == "correction":
        ack = ""

    if plan.topic == "open_need" and merchant_name.strip():
        answer = answer.replace("您门店", f"{merchant_name.strip()}")

    if plan.topic in {"identity", "correction", "rejection"}:
        ack = ""
    pieces = [ack, answer]
    advance = ADVANCE_LINES.get(plan.topic, "")
    suppress_advance = plan.topic == "advantage" and _recently_answered_advantage(history)
    if plan.should_advance and advance and not suppress_advance and not _push_forbidden(text, history):
        pieces.append(advance)
    reply = _polish_reply("".join(piece for piece in pieces if piece))
    reply = _suppress_habitual_ack(reply, last_assistant, plan)
    reply = _avoid_repeat(reply, last_assistant, plan)
    reply = _avoid_recent_repeats(reply, recent_assistants, plan)
    return SalesBrainReply(reply=reply, strategy=f"sales_brain_{plan.topic}_{plan.emotion}", plan=plan)


def plan_sales_turn(text: str, intent: str = "", conversation_history: list[dict[str, str]] | None = None) -> SalesTurnPlan:
    history = conversation_history or []
    normalized = normalize_realtime_sales_text(text)
    clean = normalized.normalized_text
    topic = _detect_topic(clean, intent, history)
    emotion = _detect_emotion(clean, history)
    repeat_risk = _repeat_risk(clean, history)
    direct_answer_only = _push_forbidden(clean, history) or repeat_risk
    stage = _detect_stage(topic, intent, history)
    should_advance = topic not in {
        "rejection",
        "busy",
        "source",
        "owner",
        "identity",
        "correction",
        "visibility",
        "need_confirmed",
        "roi_risk",
        "quality",
        "exposure_detail",
    } and not direct_answer_only
    if emotion in {"annoyed", "busy", "confused"}:
        should_advance = should_advance and topic == "open_need"
    answer_mode = "direct_answer" if direct_answer_only else "answer_then_soft_advance"
    return SalesTurnPlan(
        topic=topic,
        emotion=emotion,
        stage=stage,
        answer_mode=answer_mode,
        should_advance=should_advance,
        repeat_risk=repeat_risk,
        direct_answer_only=direct_answer_only,
        customer_summary=_customer_summary(topic, emotion),
    )


def build_omni_sales_instruction(
    text: str,
    signal: str,
    *,
    recent_history: list[dict[str, str]] | None = None,
    first_human_after_screening: bool = False,
    last_reply: str = "",
) -> str:
    plan = plan_sales_turn(text, signal, recent_history or [])
    lines = [
        f"销售行为判断：客户主题={plan.topic}，情绪={plan.emotion}，阶段={plan.stage}，回答方式={plan.answer_mode}。",
        "像真人电销一样：先承接情绪，再直接答问题；一句话不超过35个字，默认一句，最多两句；总字数不超过55字，不要长段介绍；问下一步时第二句不超过20字。",
        "客户重复问时必须换角度；客户不想加微信/资料时，本通后续禁止再推资料。",
        "不要说你刚才被打断了，不要提识别、模型、系统、线路等技术词。",
    ]
    if first_human_after_screening:
        lines.append("真人可能刚接上来没听到前文，先自然说明身份和来电原因。")
    if last_reply:
        lines.append(f"上一句AI是：{last_reply[:80]}。本轮不能复读这句。")
    if plan.topic in TOPIC_ANSWERS:
        lines.append("可用回答方向：" + " / ".join(TOPIC_ANSWERS[plan.topic][:2]))
    if plan.should_advance:
        lines.append("回答完只允许轻轻问一个选择题或下一步，不要连续推销。")
    else:
        lines.append("本轮只回答或礼貌收尾，不要推进成交。")
    return "\n".join(lines)


def score_realtime_events(events: list[dict[str, object]]) -> dict[str, object] | None:
    call_events = latest_realtime_call_events(events)
    if not call_events:
        return None
    call_state = reduce_realtime_call_events(call_events)
    metrics = [
        _metric_answer_detection(call_events),
        _metric_latency(call_events),
        _metric_turn_taking(call_events, call_state.latest_turn_response_ms),
        _metric_understanding(call_events),
        _metric_naturalness(call_events),
        _metric_stability(call_events, call_state.issues),
    ]
    total = int(round(sum(metric["score"] * metric["weight"] for metric in metrics) / sum(metric["weight"] for metric in metrics)))
    has_human = _has_event(call_events, "human_speech_confirmed")
    has_screening = _has_event(call_events, "call_screening_detected")
    unanswered_customer_turn = _has_unanswered_customer_turn(call_events)
    if not has_human:
        total = min(total, 58 if has_screening else 52)
    if unanswered_customer_turn:
        total = min(total, 62)
    return {
        "callId": call_events[-1].get("callId"),
        "score": total,
        "status": _score_status(total),
        "summary": _score_summary(
            total,
            metrics,
            human_confirmed=has_human,
            call_screening=has_screening,
            unanswered_customer_turn=unanswered_customer_turn,
        ),
        "metrics": metrics,
    }


def _detect_topic(text: str, intent: str, history: list[dict[str, str]]) -> str:
    normalized = normalize_realtime_sales_text(text)
    text = normalized.normalized_text
    combined = " ".join([text, _last_history_content(history, "user"), _last_history_content(history, "assistant")])
    compact = re.sub(r"[\s。！？?!，,、.]+", "", text.lower())
    if _has_any(text, ["放个屁", "滚", "扯淡", "骗子", "神经病", "有病"]):
        return "rejection"
    if _has_any(text, ["机器人", "ai", "AI", "念稿", "不自然", "不像人", "机械", "不会说话", "你不会"]):
        return "quality"
    if intent == "身份确认" or compact in {
        "喂",
        "喂喂",
        "你好",
        "您好",
        "你好你",
        "您好你",
        "在",
        "在在",
        "你谁",
        "谁",
        "谁啊",
        "谁呀",
        "哪位",
        "您哪位",
        "你哪位",
    }:
        return "identity"
    if intent in {"明确拒绝", "礼貌结束", "terminal_close", "rejection"} or _has_any(
        text,
        [
            "别打",
            "别联系",
            "没兴趣",
            "拉黑",
            "不需要你们",
            "不需要了",
            "不用了",
            "不要了",
            "先这样",
            "就这样",
            "这样吧",
            "挂了",
            "挂电话",
            "再见",
            "拜拜",
            "不聊了",
            "不说了",
        ],
    ):
        return "rejection"
    if intent == "稍后联系" or _has_any(text, ["忙", "没空", "不方便", "开会", "晚点", "稍后"]):
        return "busy"
    if _has_any(text, ["没有提", "没提", "没有问", "没问", "不是费用", "别猜", "不要猜", "理解错", "猜错"]):
        return "correction"
    if _is_continue_prompt(text):
        return _infer_previous_topic(history) or "quality"
    if _is_exposure_detail_question(text):
        return "exposure_detail"
    if _has_any(text, ["怎么做", "怎么合作", "流程", "怎么弄", "具体讲", "详细讲", "详细说", "说详细", "细说", "展开说", "介绍一下"]):
        return "process"
    if _is_roi_risk_question(text):
        return "roi_risk"
    if _has_any(text, ["多少钱", "费用", "价格", "收费", "付费", "要钱", "花钱", "成本", "预算", "投入", "贵"]):
        return "price"
    if normalized.has_fix("group_buying_package") or (
        "团购套餐" in text and _has_any(text, ["什么意思", "什么", "怎么做", "怎么弄", "要帮我"])
    ):
        return "process"
    if _is_visibility_or_video_question(text):
        return "visibility"
    if _is_need_already_answered(text):
        return "need_confirmed"
    if _has_any(text, ["优势", "为什么要用", "为什么用", "凭什么", "比美团", "美团来讲"]):
        return "advantage"
    if _has_any(text, ["美团", "大众点评", "抖音团购", "小红书", "高德", "已经做", "在做团购"]):
        return "channel_difference"
    if _has_any(text, ["保证", "承诺", "保底", "效果", "客流", "到店", "曝光", "转化", "靠谱吗", "有用吗"]):
        return "guarantee"
    if _has_any(text, ["多少单", "带来多少", "能带多少", "能来多少"]):
        return "guarantee"
    if _has_any(text, ["哪来的", "哪里来的", "怎么知道", "电话来源", "号码来源", "个人信息"]):
        return "source"
    if _has_any(
        text,
        [
            "重复",
            "总说",
            "老说",
            "老是说",
            "老是说明白",
            "总说明白",
            "一直说明白",
            "别重复",
            "不要重复",
            "没回答",
            "没解决",
            "不是问这个",
        ],
    ):
        return _infer_previous_topic(history) or "quality"
    if _push_forbidden(text, history):
        return "open_need"
    if _has_any(text, ["微信", "资料", "发给我", "发我", "怎么发", "短信", "案例"]):
        return "materials"
    if _has_any(text, ["老板不在", "负责人", "店长", "不是我负责", "转给"]):
        return "owner"
    if _has_any(text, ["你是谁", "你谁", "谁啊", "谁呀", "哪位", "您哪位", "你咋", "咋的", "什么情况", "什么公司", "做什么", "做啥", "干嘛", "什么事", "来电原因", "官方"]):
        return "identity"
    if _has_any(text, ["听不清", "没听清", "听不懂", "说什么", "什么意思", "断断续续", "卡", "信号"]):
        return "quality"
    if not text.strip() and _has_any(combined, ["美团", "大众点评", "抖音团购", "小红书", "高德"]):
        return "channel_difference"
    return "open_need"


def _is_visibility_or_video_question(text: str) -> bool:
    compact = re.sub(r"[\s。！？?!，,、.]+", "", text.lower())
    if not compact:
        return False
    has_question = _has_any(compact, ["怎么", "如何", "是不是", "要不要", "一定要", "必须", "吗", "呢", "搜索"])
    visibility_markers = [
        "怎么看到",
        "怎么能看到",
        "客户看到",
        "用户看到",
        "看到我的团购券",
        "团购券",
        "客户搜索",
        "客户不搜索",
        "不搜索",
        "同城推荐",
        "推荐流",
        "门店主页",
        "主页入口",
    ]
    video_markers = ["做视频", "拍视频", "发视频", "视频呢", "还要视频", "还得视频"]
    return has_question and (_has_any(compact, visibility_markers) or _has_any(compact, video_markers))


def _is_exposure_detail_question(text: str) -> bool:
    compact = re.sub(r"[\s。！？?!，,、.]+", "", text.lower())
    if not compact:
        return False
    has_exposure = _has_any(compact, ["同城曝光", "微信曝光", "曝光入口", "同城入口"])
    has_detail = _has_any(compact, ["详细", "具体", "说一下", "讲一下", "怎么回事", "什么意思", "怎么做"])
    return has_exposure and has_detail


def _is_roi_risk_question(text: str) -> bool:
    compact = re.sub(r"[\s。！？?!，,、.]+", "", text.lower())
    if not compact:
        return False
    risk_markers = ["达不到", "没有达到", "没达到", "不达标", "达不成", "不来客户", "没客户", "客户不够"]
    cost_markers = ["成本", "花钱", "投入", "预算", "付费", "费用", "钱"]
    customer_markers = ["客户", "到店", "客流", "成交", "咨询"]
    return _has_any(compact, risk_markers) and (_has_any(compact, cost_markers) or _has_any(compact, customer_markers))


def _is_continue_prompt(text: str) -> bool:
    compact = re.sub(r"[\s。！？?!，,、.]+", "", text.lower())
    return compact in {"说话", "继续说", "接着说", "你说", "讲", "继续"}


def _is_need_already_answered(text: str) -> bool:
    compact = re.sub(r"[\s。！？?!，,、.]+", "", text.lower())
    if not compact:
        return False
    has_answered_marker = _has_any(compact, ["我都说了", "刚说了", "刚才说了", "不是说了", "都说了"])
    has_need_marker = _has_any(compact, ["新客到店", "到店客", "到店客流", "客流", "获客", "新客"])
    return has_answered_marker and has_need_marker


def _detect_emotion(text: str, history: list[dict[str, str]]) -> str:
    text = normalize_realtime_sales_text(text).normalized_text
    if _has_any(text, ["忙", "没空", "开会", "不方便", "快点", "赶时间"]):
        return "busy"
    if _has_any(
        text,
        [
            "别",
            "不要",
            "重复",
            "老是说明白",
            "总说明白",
            "一直说明白",
            "烦",
            "没解决",
            "没回答",
            "我都说了",
            "刚说了",
            "不是说了",
            "不需要",
            "不用",
            "挂了",
            "放个屁",
            "滚",
            "扯淡",
            "骗子",
        ],
    ):
        return "annoyed"
    if _has_any(text, ["保证", "靠谱吗", "真的假的", "有用吗", "怎么保证", "凭什么"]):
        return "skeptical"
    if _has_any(text, ["听不懂", "什么意思", "说什么", "没听清", "你是谁", "没有提", "没提", "没问", "理解错", "猜错"]):
        return "confused"
    if _has_any(text, ["可以", "说一下", "了解", "怎么合作", "资料", "发我"]):
        return "interested"
    if _repeat_risk(text, history):
        return "annoyed"
    return "neutral"


def _detect_stage(topic: str, intent: str, history: list[dict[str, str]]) -> str:
    if topic in {"identity", "quality", "correction"} or not history:
        return "opening_repair"
    if topic in {"price", "roi_risk", "guarantee", "channel_difference", "advantage", "source", "visibility", "exposure_detail"}:
        return "objection_handling"
    if topic in {"process", "open_need", "need_confirmed"}:
        return "discovery"
    if topic in {"materials", "owner"}:
        return "next_step"
    if topic in {"rejection", "busy"}:
        return "close_or_callback"
    return intent or "conversation"


def _customer_summary(topic: str, emotion: str) -> str:
    return f"客户当前在问{topic}，情绪偏{emotion}"


def _push_forbidden(text: str, history: list[dict[str, str]]) -> bool:
    text = normalize_realtime_sales_text(text).normalized_text
    combined = " ".join([text, _last_history_content(history, "user"), _last_history_content(history, "assistant")])
    return _has_any(combined, ["不需要资料", "不用资料", "不要资料", "别发资料", "不用发资料", "不用加微信", "不加微信", "直接回答", "说重点", "别推"])


def _repeat_risk(text: str, history: list[dict[str, str]]) -> bool:
    text = normalize_realtime_sales_text(text).normalized_text
    if _has_any(text, ["重复", "总说", "老说", "老是说", "老是说明白", "总说明白", "一直说明白", "别重复", "不要重复"]):
        return True
    current = _normalize_reply(text)
    if current:
        recent_users = [
            _normalize_reply(turn.get("content", ""))
            for turn in history[-8:]
            if turn.get("role") == "user"
        ]
        if current in {item for item in recent_users if item}:
            return True
    replies = [_normalize_reply(turn.get("content", "")) for turn in history if turn.get("role") == "assistant"]
    return bool(len(replies) >= 2 and replies[-1] and replies[-1] == replies[-2])


def _recently_answered_identity(history: list[dict[str, str]]) -> bool:
    recent_replies = [
        str(turn.get("content") or "")
        for turn in history[-6:]
        if (turn.get("role") or "").strip().lower() == "assistant"
    ]
    return any(_has_any(reply, ["做视频号团购", "到店获客", "同城曝光"]) for reply in recent_replies)


def _recently_answered_advantage(history: list[dict[str, str]]) -> bool:
    recent_replies = _recent_history_contents(history, "assistant", limit=4)
    return any(_has_any(reply, ["微信同城", "私域", "美团", "到店入口", "补充"]) for reply in recent_replies)


def _infer_previous_topic(history: list[dict[str, str]]) -> str | None:
    last_user = _last_history_content(history, "user")
    last_assistant = _last_history_content(history, "assistant")
    combined = last_user + last_assistant
    for topic in ("price", "roi_risk", "guarantee", "advantage", "channel_difference", "exposure_detail", "process", "identity"):
        if _detect_topic(combined, "", []) == topic:
            return topic
    return None


def _last_history_content(history: list[dict[str, str]], role: str) -> str:
    for turn in reversed(history):
        if (turn.get("role") or "").strip().lower() == role:
            return str(turn.get("content") or "").strip()
    return ""


def _recent_history_contents(history: list[dict[str, str]], role: str, *, limit: int = 5) -> list[str]:
    items: list[str] = []
    for turn in reversed(history):
        if (turn.get("role") or "").strip().lower() == role:
            content = str(turn.get("content") or "").strip()
            if content:
                items.append(content)
        if len(items) >= limit:
            break
    return items


def _choose_variant(options: list[str], seed: str, last_assistant: str, recent_assistants: list[str] | None = None) -> str:
    if not options:
        return ""
    start = sum(ord(ch) for ch in seed) % len(options)
    recent_norm = {_normalize_reply(item) for item in (recent_assistants or []) if item}
    for offset in range(len(options)):
        candidate = options[(start + offset) % len(options)]
        normalized = _normalize_reply(candidate)
        if normalized != _normalize_reply(last_assistant) and normalized not in recent_norm:
            return candidate
    return options[start]


def _polish_reply(reply: str) -> str:
    cleaned = re.sub(r"\s+", "", reply)
    cleaned = cleaned.replace("。。", "。").replace("？？", "？")
    if len(cleaned) <= 92:
        return cleaned
    parts = re.split(r"(?<=[。！？])", cleaned)
    shortened = ""
    for part in parts:
        if len(shortened + part) > 92:
            break
        shortened += part
    return shortened or cleaned[:92]


def _avoid_repeat(reply: str, last_assistant: str, plan: SalesTurnPlan) -> str:
    if _normalize_reply(reply) != _normalize_reply(last_assistant):
        return reply
    options = TOPIC_ANSWERS.get(plan.topic, []) + ["我换个说法：" + ADVANCE_LINES.get(plan.topic, "您更想先听费用、效果，还是流程？")]
    for candidate in options:
        polished = _polish_reply(candidate)
        if _normalize_reply(polished) != _normalize_reply(last_assistant):
            return polished
    return reply


def _avoid_recent_repeats(reply: str, recent_assistants: list[str], plan: SalesTurnPlan) -> str:
    normalized = _normalize_reply(reply)
    recent_norm = {_normalize_reply(item) for item in recent_assistants if item}
    if normalized not in recent_norm:
        return reply
    options = TOPIC_ANSWERS.get(plan.topic, []) + [
        "我换个角度说：微信同城曝光、私域沉淀、到店核销，这是视频号补的部分。",
        "简单讲，先看品类，再做可核销套餐，小范围测到店数据。",
        "您问得对，我直接答这个点，不再重复前面那句。",
    ]
    for candidate in options:
        polished = _polish_reply(candidate)
        if _normalize_reply(polished) not in recent_norm:
            return polished
    return reply


def _suppress_habitual_ack(reply: str, last_assistant: str, plan: SalesTurnPlan) -> str:
    if plan.topic in {"rejection", "materials", "busy"}:
        return reply
    if not reply.startswith(("明白", "好的", "好，", "好。", "可以，")):
        return reply
    stripped = re.sub(r"^(明白|好的|好|可以)[，。,.\s]+", "", reply, count=1)
    if len(stripped) >= 6:
        return stripped
    if _normalize_reply(last_assistant).startswith(("明白", "好的", "好", "可以")) and stripped:
        return stripped
    return reply


def _normalize_reply(text: str) -> str:
    return re.sub(r"[\s。！？?!，,、.]+", "", str(text).lower())


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _metric_answer_detection(events: list[dict[str, object]]) -> dict[str, object]:
    has_connected = _has_event(events, "call_connected")
    has_human = _has_event(events, "human_speech_confirmed")
    has_ai = _has_speech_audio(events)
    score = 100 if has_connected and has_human and has_ai else 65 if has_connected and (has_human or has_ai) else 30
    return _metric("接通识别", score, 1.2, "真人语音和AI首句都要确认" if score < 100 else "已确认真人语音和AI播报")


def _metric_latency(events: list[dict[str, object]]) -> dict[str, object]:
    starts = [_event_latency(event) for event in events if event.get("type") == "tts_start"]
    starts = [value for value in starts if value > 0]
    if not starts:
        return _metric("响应延迟", 35, 1.0, "没有检测到可评分的首音频延迟")
    average = sum(starts) / len(starts)
    score = 100 if average <= 650 else 82 if average <= 1000 else 62 if average <= 1500 else 35
    return _metric("响应延迟", score, 1.0, f"平均首音频约 {int(average)}ms")


def _metric_turn_taking(events: list[dict[str, object]], latest_turn_response_ms: int | None = None) -> dict[str, object]:
    human_at = next((_parse_event_time(event) for event in events if event.get("type") == "human_speech_confirmed"), None)
    scored_events = [
        event
        for event in events
        if not human_at or ((_parse_event_time(event) or human_at) >= human_at)
    ]
    barge_events = [
        event
        for event in scored_events
        if event.get("type") in {"barge_in", "barge_recovery_ready", "barge_turn_committed", "tts_interrupted"}
    ]
    if latest_turn_response_ms is not None:
        latency_score = 100 if latest_turn_response_ms <= 1000 else 78 if latest_turn_response_ms <= 1500 else 45
        if not barge_events:
            return _metric("轮次衔接", latency_score, 1.1, f"客户说完到AI首个声音约 {latest_turn_response_ms}ms")
    stopped = _has_event_after(
        scored_events,
        "barge_in",
        {"tts_interrupted", "barge_recovery_ready", "barge_playback_drained"},
        within_seconds=0.3,
    )
    recovered = any(
        _has_event_after(scored_events, start_type, {"tts_start", "llm_reply", "omni_response_slow_fallback"}, within_seconds=1.0)
        for start_type in ("barge_recovery_ready", "barge_turn_committed", "barge_in", "tts_interrupted")
    )
    if not barge_events:
        return _metric("轮次衔接", 78, 0.9, "本轮没有明显打断，按基础稳定分")
    score = 100 if recovered else 88 if stopped else 48
    if latest_turn_response_ms is not None:
        score = min(score, 100 if latest_turn_response_ms <= 1000 else 78 if latest_turn_response_ms <= 1500 else 45)
    if recovered:
        detail = "打断后1秒内已重新回复"
    elif stopped:
        detail = "客户打断后已快速停嘴并回到监听，等待客户说完"
    else:
        detail = "打断后未及时停嘴或恢复监听"
    return _metric("打断恢复", score, 1.1, detail)


def _metric_understanding(events: list[dict[str, object]]) -> dict[str, object]:
    user_turns = [
        str(event.get("text") or "")
        for event in events
        if event.get("type") in {"asr_final", "human_speech_confirmed"} and event.get("text")
    ]
    replies = [str(event.get("reply") or "") for event in events if event.get("type") == "llm_reply" and event.get("reply")]
    if not user_turns or not replies:
        return _metric("理解客户", 35, 1.2, "缺少客户转写或AI回复")
    generic_count = sum(_looks_generic(reply) for reply in replies)
    score = 95
    if len(replies) < max(1, len(user_turns) // 2):
        score -= 20
    score -= min(35, generic_count * 12)
    if _duplicate_ratio(replies) >= 0.3:
        score -= 25
    if _repeated_opening_count(replies) >= 2:
        score -= 25
    if _has_profanity(user_turns) and not _has_polite_close(replies):
        score -= 35
    if _has_unanswered_customer_turn(events):
        score -= 35
    return _metric("理解客户", max(25, score), 1.2, f"{len(user_turns)}轮客户语音，{len(replies)}轮AI回复")


def _metric_naturalness(events: list[dict[str, object]]) -> dict[str, object]:
    replies = [str(event.get("reply") or "") for event in events if event.get("type") == "llm_reply" and event.get("reply")]
    if not replies:
        return _metric("真人感", 35, 1.0, "没有AI回复文本")
    bad = sum(_has_any(reply, ["刚才被打断", "系统", "识别", "模型", "线路", "智能助手", "机器人", "先发份资料"]) for reply in replies)
    emotion = sum(_has_any(reply, ["明白", "可以", "对", "不急", "您问", "我换", "懂"]) for reply in replies)
    long = sum(len(reply) > 90 for reply in replies)
    repeated_opening = _repeated_opening_count(replies)
    score = 82 + min(12, emotion * 4) - bad * 18 - long * 8 - max(0, repeated_opening - 1) * 22
    return _metric("真人感", max(25, min(100, score)), 1.0, f"情绪承接 {emotion} 次，技术口吻 {bad} 次")


def _metric_stability(events: list[dict[str, object]], state_issues: list[str] | None = None) -> dict[str, object]:
    bad_types = {"omni_unavailable", "call_error", "omni_audio_append_error", "omni_response_request_error"}
    normal_socket_close = _normal_audiosocket_close_after_conversation(events)
    bad_count = sum(
        1
        for event in events
        if event.get("type") in bad_types
        and not (normal_socket_close and event.get("type") == "call_error")
    )
    no_audio = sum(1 for event in events if event.get("type") == "omni_no_audio_response")
    issue_count = len(state_issues or [])
    unanswered = 1 if _has_unanswered_customer_turn(events) else 0
    score = max(25, 100 - bad_count * 30 - no_audio * 15 - issue_count * 8 - unanswered * 28)
    detail = f"异常 {bad_count} 次，无音频兜底 {no_audio} 次，未回复客户轮次 {unanswered} 次"
    if state_issues:
        detail += "；" + "；".join(state_issues[:2])
    return _metric("链路稳定", score, 0.9, detail)


def _metric(name: str, score: int, weight: float, detail: str) -> dict[str, object]:
    bounded = max(0, min(100, int(score)))
    return {"name": name, "score": bounded, "status": _score_status(bounded), "weight": weight, "detail": detail}


def _score_status(score: int) -> str:
    if score >= 85:
        return "pass"
    if score >= 65:
        return "warn"
    return "fail"


def _score_summary(
    total: int,
    metrics: list[dict[str, object]],
    *,
    human_confirmed: bool = True,
    call_screening: bool = False,
    unanswered_customer_turn: bool = False,
) -> str:
    if not human_confirmed and call_screening:
        return "只检测到电话助理，还没有确认真人客户语音。"
    if not human_confirmed:
        return "还没有确认真人客户语音，不能作为实时通话验收。"
    if unanswered_customer_turn:
        return "客户最后一句没有得到可听见的AI回复，不能作为实时通话验收。"
    weak = [str(metric["name"]) for metric in metrics if int(metric["score"]) < 70]
    if total >= 85:
        return "本轮接近可交付标准，继续观察真实客户长通话。"
    if weak:
        return "需要重点修正：" + "、".join(weak[:3])
    return "整体可用，但还需要真实长通话继续压测。"


def _has_event(events: list[dict[str, object]], event_type: str) -> bool:
    return any(event.get("type") == event_type for event in events)


def _normal_audiosocket_close_after_conversation(events: list[dict[str, object]]) -> bool:
    if not _has_event(events, "human_speech_confirmed") or not _has_speech_audio(events):
        return False
    if _has_unanswered_customer_turn(events):
        return False
    for event in events:
        if event.get("type") != "call_error":
            continue
        raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
        message = " ".join(
            str(value or "")
            for value in (
                event.get("error"),
                event.get("detail"),
                raw.get("error"),
                raw.get("detail"),
            )
        )
        if "AudioSocket connection closed" in message:
            return True
    return False


def _has_unanswered_customer_turn(events: list[dict[str, object]]) -> bool:
    last_customer_at: datetime | None = None
    for event in events:
        if event.get("type") not in {"asr_final", "asr_partial_stable", "turn_endpoint_final", "turn_endpoint_candidate"}:
            continue
        text = str(event.get("text") or "")
        if not _is_actionable_customer_text(text):
            continue
        event_at = _parse_event_time(event)
        if event_at:
            last_customer_at = event_at
    if not last_customer_at:
        return False
    heard_response_after = any(
        event.get("type") in {"tts_start", "tts_done"}
        and _parse_event_time(event)
        and (_parse_event_time(event) or last_customer_at) > last_customer_at
        and _speech_event_has_audio(event)
        for event in events
    )
    if heard_response_after:
        return False
    terminal_after = any(
        event.get("type") in {"call_error", "call_disconnected", "call_closed", "hangup_frame"}
        and _parse_event_time(event)
        and (_parse_event_time(event) or last_customer_at) >= last_customer_at
        for event in events
    )
    return terminal_after


def _is_actionable_customer_text(text: str) -> bool:
    compact = _normalize_reply(text)
    if not compact or compact in {"喂", "喂喂", "你好", "您好", "你好你好", "在吗"}:
        return False
    return len(compact) >= 2


def _speech_event_has_audio(event: dict[str, object]) -> bool:
    raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
    return int(event.get("sentBytes") or event.get("bytes") or raw.get("sentBytes") or raw.get("bytes") or raw.get("totalBytes") or 0) > 0


def _has_speech_audio(events: list[dict[str, object]]) -> bool:
    for event in events:
        if event.get("type") not in {"tts_start", "tts_done"}:
            continue
        raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
        if int(raw.get("sentBytes") or raw.get("bytes") or 0) > 0:
            return True
    return False


def _event_latency(event: dict[str, object]) -> int:
    raw = event.get("raw") if isinstance(event.get("raw"), dict) else {}
    return int(event.get("latencyMs") or raw.get("firstAudioMs") or raw.get("synthMs") or 0)


def _looks_generic(reply: str) -> bool:
    return _has_any(reply, ["费用、效果", "更关心费用", "更想听费用"]) or len(reply.strip()) < 6


def _duplicate_ratio(replies: list[str]) -> float:
    normalized = [_normalize_reply(reply) for reply in replies if reply.strip()]
    if len(normalized) <= 1:
        return 0.0
    return 1.0 - (len(set(normalized)) / len(normalized))


def _repeated_opening_count(replies: list[str]) -> int:
    opening_markers = ["方便听我说", "确认门店是否需要", "想确认门店团购曝光"]
    return sum(_has_any(reply, opening_markers) for reply in replies)


def _has_profanity(texts: list[str]) -> bool:
    return any(_has_any(text, ["放个屁", "滚", "扯淡", "骗子", "神经病", "有病"]) for text in texts)


def _has_polite_close(replies: list[str]) -> bool:
    return any(_has_any(reply, ["不打扰", "不再跟进", "打扰您了", "祝您生意顺利"]) for reply in replies)


def _has_event_after(
    events: list[dict[str, object]],
    start_type: str,
    next_types: set[str],
    *,
    within_seconds: float,
) -> bool:
    start_times = [_parse_event_time(event) for event in events if event.get("type") == start_type]
    next_events = [(event.get("type"), _parse_event_time(event)) for event in events if event.get("type") in next_types]
    for start in start_times:
        if not start:
            continue
        for _, candidate in next_events:
            if candidate and 0 <= (candidate - start).total_seconds() <= within_seconds:
                return True
    return False


def _parse_event_time(event: dict[str, object]) -> datetime | None:
    text = str(event.get("at") or "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", ""))
    except ValueError:
        return None
