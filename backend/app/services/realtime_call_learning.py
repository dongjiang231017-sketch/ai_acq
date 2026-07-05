from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings


def realtime_call_learning_path() -> Path:
    configured = settings.realtime_call_learning_path.strip()
    if configured:
        return Path(configured).expanduser()
    event_path = Path(settings.realtime_call_event_log_path).expanduser()
    return event_path.with_name("realtime_call_learning.jsonl")


def record_realtime_call_learning(
    *,
    call_id: str,
    conversation_history: list[dict[str, str]],
    close_reason: str = "",
) -> dict[str, object] | None:
    customer_turns = [
        _clean(turn.get("content") or "")
        for turn in conversation_history
        if (turn.get("role") or "").strip().lower() == "user"
    ]
    assistant_turns = [
        _clean(turn.get("content") or "")
        for turn in conversation_history
        if (turn.get("role") or "").strip().lower() == "assistant"
    ]
    customer_turns = [turn for turn in customer_turns if turn]
    assistant_turns = [turn for turn in assistant_turns if turn]
    if not call_id or not (customer_turns or assistant_turns):
        return None

    topics = _topic_counts(customer_turns)
    repeated_patterns = _repeated_reply_patterns(assistant_turns)
    lesson = {
        "at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "callId": call_id,
        "closeReason": close_reason,
        "customerTurns": customer_turns[-12:],
        "assistantTurns": assistant_turns[-12:],
        "topics": topics,
        "avoidPhrases": repeated_patterns,
        "nextGuidance": _build_next_guidance(topics, repeated_patterns, customer_turns),
    }
    path = realtime_call_learning_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(lesson, ensure_ascii=False) + "\n")
    return lesson


def load_recent_realtime_call_lessons(limit: int = 3) -> list[dict[str, Any]]:
    path = realtime_call_learning_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    lessons: list[dict[str, Any]] = []
    for line in reversed(lines[-50:]):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            lessons.append(payload)
        if len(lessons) >= limit:
            break
    return list(reversed(lessons))


def build_realtime_learning_instruction(limit: int = 3) -> str:
    lessons = load_recent_realtime_call_lessons(limit=limit)
    guidance: list[str] = []
    avoid: list[str] = []
    for lesson in lessons:
        for item in lesson.get("nextGuidance") or []:
            if isinstance(item, str) and item not in guidance:
                guidance.append(item)
        for item in lesson.get("avoidPhrases") or []:
            if isinstance(item, str) and item not in avoid:
                avoid.append(item)
    if not guidance and not avoid:
        return ""
    lines = ["最近真实通话复盘，下一通必须改进："]
    lines.extend(f"- {item}" for item in guidance[:6])
    if avoid:
        lines.append("- 避免复读这些表达：" + " / ".join(avoid[:5]))
    return "\n".join(lines)


def _topic_counts(customer_turns: list[str]) -> dict[str, int]:
    labels: list[str] = []
    for text in customer_turns:
        if _has_any(text, ["优势", "为什么要用", "凭什么", "比美团", "美团来讲"]):
            labels.append("advantage")
        if _has_any(text, ["美团", "抖音", "大众点评", "小红书", "高德"]):
            labels.append("channel_difference")
        if _has_any(text, ["收费", "费用", "价格", "多少钱", "付费", "要钱", "基础费"]):
            labels.append("price")
        if _has_any(text, ["流程", "怎么做", "怎么合作", "开发流程"]):
            labels.append("process")
        if _has_any(text, ["你是谁", "你谁", "哪位", "干嘛", "做什么"]):
            labels.append("identity")
        if _has_any(text, ["不合适", "不做", "挂了", "再见", "别打"]):
            labels.append("close")
    return dict(Counter(labels).most_common())


def _repeated_reply_patterns(assistant_turns: list[str]) -> list[str]:
    patterns = [
        "美团偏搜索",
        "视频号偏微信同城",
        "不合适不建议做",
        "费用看套餐",
        "给您来电是确认",
        "先看品类",
    ]
    found: list[str] = []
    joined = "\n".join(assistant_turns)
    for pattern in patterns:
        if joined.count(pattern) >= 2:
            found.append(pattern)
    normalized = [_normalize_reply(turn) for turn in assistant_turns]
    counts = Counter(item for item in normalized if len(item) >= 10)
    for item, count in counts.most_common(3):
        if count >= 2:
            found.append(item[:24])
    return found[:6]


def _build_next_guidance(topics: dict[str, int], repeated_patterns: list[str], customer_turns: list[str]) -> list[str]:
    guidance: list[str] = []
    if topics.get("advantage") or topics.get("channel_difference"):
        guidance.append("客户问优势/为什么用你时，直接给具体差异：微信同城内容曝光、私域沉淀、套餐核销；不要只重复“美团偏搜索”。")
    if topics.get("price"):
        guidance.append("客户问收费/基础费用时，先承认付费，再说明报价取决于套餐和投放节奏；不要连续说“不合适不建议做”。")
    if topics.get("process"):
        guidance.append("客户问流程时，用三步说清：看品类和客单价、设计可核销团购套餐、小范围测曝光/咨询/到店。")
    if topics.get("identity"):
        guidance.append("客户反复问身份时，先说“我在”，再一句话说明本地生活服务顾问和来电目的。")
    if topics.get("close"):
        guidance.append("客户明确说再见/挂了时，只短句告别并正常关闭，不再补充销售内容。")
    if repeated_patterns:
        guidance.append("下一通同一主题连续追问时必须换角度，优先补具体步骤、例子或边界，不复读上一句。")
    if not guidance and customer_turns:
        guidance.append("下一通先回答客户原问题，再决定是否推进；不要用固定开场或模板句覆盖客户问题。")
    return guidance[:6]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_reply(text: str) -> str:
    return re.sub(r"[\s。！？?!，,、.；;：:\"'“”‘’（）()]+", "", text.lower())


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)
