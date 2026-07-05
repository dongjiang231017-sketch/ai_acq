from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RealtimeTextNormalization:
    raw_text: str
    normalized_text: str
    fixes: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.normalized_text != self.raw_text

    def has_fix(self, fix: str) -> bool:
        return fix in self.fixes


def normalize_realtime_sales_text(text: str) -> RealtimeTextNormalization:
    """Repair high-confidence ASR slips before sales intent/reply routing."""
    raw = " ".join(str(text or "").strip().split())
    normalized = raw
    fixes: list[str] = []
    if not normalized:
        return RealtimeTextNormalization(raw, normalized)

    normalized = _dedupe_incremental_asr(normalized, fixes)
    normalized = _repair_group_buying_terms(normalized, fixes)
    normalized = _repair_video_account_terms(normalized, fixes)
    normalized = _repair_repeated_need_question_artifact(normalized, fixes)
    normalized = _repair_common_question_fragments(normalized, fixes)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return RealtimeTextNormalization(raw, normalized, tuple(dict.fromkeys(fixes)))


def has_incomplete_realtime_partial(text: str) -> bool:
    compact = _compact(text)
    if not compact:
        return False
    incomplete_suffixes = (
        "有需",
        "如果我有需",
        "怎么",
        "怎么做美",
        "如果客户不",
        "如果客户不搜",
        "客户不搜",
        "客户不搜索那是不是",
        "那是不是我还",
        "我是说我是不是还",
        "我是不是还",
        "是不是还",
        "是不是还要",
        "是不是还得",
        "一定要",
        "一定要客户",
        "你要帮我",
        "要帮我",
        "什么意",
        "什么意思你",
        "啥意",
        "啥意思你",
        "你们是",
        "你到底是",
    )
    if compact.endswith(incomplete_suffixes):
        return True
    if compact.endswith("套餐") and not any(marker in compact for marker in ("什么", "怎么", "要不要", "是不是")):
        return True
    return False


def _dedupe_incremental_asr(text: str, fixes: list[str]) -> str:
    before = text
    replacements = (
        ("我需我有需求", "我有需求"),
        ("如果我需我有需求", "如果我有需求"),
        ("我有需我有需求", "我有需求"),
        ("好如果我需我有需求", "好，如果我有需求"),
        ("好，如果我需我有需求", "好，如果我有需求"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    if text != before:
        fixes.append("dedupe_incremental_asr")
    return text


def _repair_group_buying_terms(text: str, fixes: list[str]) -> str:
    if not _looks_like_local_life_context(text):
        return text
    before = text
    text = re.sub(r"(?i)(?:四|4|４)\s*(?:g|ｇ|G|Ｇ)\s*套餐", "团购套餐", text)
    text = text.replace("团够套餐", "团购套餐").replace("团狗套餐", "团购套餐")
    text = text.replace("团购套菜", "团购套餐").replace("团购餐", "团购套餐")
    if text != before:
        fixes.append("group_buying_package")
    return text


def _repair_video_account_terms(text: str, fixes: list[str]) -> str:
    before = text
    if _looks_like_local_life_context(text):
        text = text.replace("视频好", "视频号").replace("视频后", "视频号")
        text = text.replace("视屏号", "视频号").replace("是频号", "视频号")
    if text != before:
        fixes.append("video_account_term")
    return text


def _repair_repeated_need_question_artifact(text: str, fixes: list[str]) -> str:
    before = text
    compact = _compact(text)
    local_life_need_answer = any(marker in compact for marker in ("新客到店", "新课到店", "客流", "获客", "到店"))
    repeated_prefix = compact.startswith("你需求什么") and any(marker in compact for marker in ("我都说了", "刚说了", "不是说了", "新客", "新课"))
    if not (local_life_need_answer and repeated_prefix):
        return text

    text = re.sub(r"^你需求什么[？?，,。；;\s]*", "", text).strip()
    text = re.sub(r"^你什么(?=新客|新课|到店)", "", text).strip()
    text = re.sub(r"新课(?=到店)", "新客", text)
    text = re.sub(r"新课$", "新客", text)
    if text != before:
        fixes.append("repeated_need_question_asr_artifact")
    return text


def _repair_common_question_fragments(text: str, fixes: list[str]) -> str:
    before = text
    text = text.replace("什么意？", "什么意思？")
    text = text.replace("什么意。", "什么意思。")
    if text != before:
        fixes.append("question_fragment")
    return text


def _looks_like_local_life_context(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "美团",
            "大众点评",
            "抖音",
            "视频号",
            "团购",
            "套餐",
            "到店",
            "同城",
            "获客",
            "投放",
            "需求",
            "怎么做",
            "什么意思",
        )
    )


def _compact(text: str) -> str:
    return re.sub(r"[\s。！？?!，,、.；;：:\"'“”‘’（）()\\[\\]【】]+", "", str(text or "").lower())
