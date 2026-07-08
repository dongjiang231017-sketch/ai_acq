from __future__ import annotations

import argparse
import base64
import errno
import json
import math
import os
import queue
import re
import signal
import socket
import struct
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field, replace
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from dashscope.audio.tts_v2 import SpeechSynthesizer
from dashscope.audio.tts_v2.speech_synthesizer import AudioFormat as CosyAudioFormat
from dashscope.audio.qwen_omni import MultiModality, OmniRealtimeCallback, OmniRealtimeConversation
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.growth import VoiceCloneRecord
from app.services.realtime_answer_classifier import AnswerClassifier, CallAnswerType, classify_answer_text
from app.services.realtime_audio_quality import RealtimeAudioQualityChain, analyze_pcm16
from app.services.realtime_call_learning import record_realtime_call_learning
from app.services.realtime_intent_capture import (
    claim_realtime_call_context,
    record_realtime_intent_signal,
    record_realtime_wechat_signal,
)
from app.services.realtime_llm import generate_realtime_reply
from app.services.realtime_outbound import _build_reply, _classify_intent
from app.services.realtime_route_health import mark_omni_route_unavailable, omni_route_unavailable_reason
from app.services.realtime_sales_playbook import (
    build_omni_turn_instruction,
    build_video_group_buying_sales_instructions,
    classify_realtime_call_input,
    extract_human_text_after_system_prompt,
)
from app.services.realtime_sales_state import SalesStateMachine
from app.services.realtime_text_normalizer import has_incomplete_realtime_partial, normalize_realtime_sales_text
from app.services.realtime_voice_cache import (
    CachedVoiceMatch,
    get_cached_opening_voice_match,
    iter_cached_voice_pcm_chunks,
    match_cached_voice_reply,
    voice_cache_status,
)
from app.services.runtime_ai_config import get_runtime_ai_config


AUDIO_SOCKET_KIND_HANGUP = 0x00
AUDIO_SOCKET_KIND_UUID = 0x01
AUDIO_SOCKET_KIND_DTMF = 0x03
AUDIO_SOCKET_KIND_AUDIO = 0x10
AUDIO_SOCKET_KIND_ERROR = 0xFF
PCM_FRAME_BYTES = 320
PCM_FRAME_SECONDS = 0.02
TTS_STREAM_START_BUFFER_BYTES = PCM_FRAME_BYTES * 8
AUDIOSOCKET_IDLE_KEEPALIVE_GAP_SECONDS = PCM_FRAME_SECONDS * 2
REMOTE_AUDIO_SAMPLE_INTERVAL_SECONDS = 1.0
OMNI_LOCAL_BARGE_MIN_SENT_BYTES = PCM_FRAME_BYTES * 70
OMNI_BARGE_RECOVERY_MIN_SECONDS = 0.35
OMNI_BARGE_RECOVERY_SILENCE_SECONDS = 0.9
OMNI_BARGE_RECOVERY_MAX_SECONDS = 2.4
OMNI_BARGE_RECOVERY_WATCHDOG_SECONDS = OMNI_BARGE_RECOVERY_MAX_SECONDS + 0.05
OMNI_BARGE_FORCED_RESPONSE_SKIP_SECONDS = 4.0
OMNI_FIRST_AUDIO_DEADLINE_SECONDS = 1.8
OMNI_TRANSCRIPTION_FALLBACK_DELAY_SECONDS = 0.75
OMNI_NO_AUDIO_FALLBACK_TEXT = "我短说：我是做视频号团购到店获客的，帮门店做套餐和微信同城曝光。"
SOLUTION_INTRO_REPLY = "我先多讲一句：我们先看门店品类和客单价，设计可核销团购套餐，再小范围测曝光、咨询和到店数据。"
SOFT_WECHAT_OFFER_REPLY = "落地流程就是诊断品类、设计套餐、上架测试和复盘。如果您愿意，我可以微信发一份同品类案例和费用区间。"
BUSINESS_CATEGORY_REPLY = "您这类门店适合先做低门槛引流套餐，用视频号同城推荐带附近客户到店，再看咨询和核销数据。"
INTERRUPTED_OPENING_SHORT_FALLBACK_REPLY = (
    "嗯，不是卖课，也不是平台招商，就是看你们店应该能做到店套餐，"
    "想问下你有没有了解过视频号团购这块。"
)
GENERIC_MERCHANT_NAMES = {"", "单号真实试拨", "测试", "test", "商家", "客户门店", "您的门店"}
STRONG_TERMINAL_CLOSE_MARKERS = (
    "别打",
    "不要打",
    "别再打",
    "不要再打",
    "别联系",
    "不要联系",
    "拉黑",
    "没兴趣",
    "不感兴趣",
    "不需要了",
    "不需要你们",
    "不用了",
    "不要了",
    "挂了",
    "挂电话",
    "不聊了",
    "不说了",
    "再见",
    "拜拜",
    "滚",
    "骗子",
    "神经病",
)
SOFT_BUSY_MARKERS = ("忙", "没空", "不方便", "没时间", "来不及", "开会", "晚点", "稍后", "等下")
BUSINESS_CATEGORY_MARKERS = (
    "沙县",
    "小吃",
    "餐饮",
    "饭店",
    "餐馆",
    "快餐",
    "火锅",
    "烧烤",
    "奶茶",
    "粉面",
    "面馆",
    "美甲",
    "美睫",
    "美容",
    "理发",
    "健身",
    "足浴",
    "按摩",
)
REMOTE_AUDIO_CLASSIFY_WAIT_SECONDS = 7.0
REMOTE_AUDIO_SILENCE_SECONDS = 0.95
BARGE_AUDIO_FORWARD_SECONDS = 2.8
ASR_PARTIAL_STABLE_SECONDS = 0.32
ASR_PARTIAL_DUPLICATE_SECONDS = 12.0
ASR_PARTIAL_MIN_COMPACT_CHARS = 5
SCRIPTED_REPLY_SUPPRESS_SECONDS = 15.0
ASR_PARTIAL_FAST_SIGNALS = {
    "continue_prompt",
    "identity_handoff",
    "audio_issue",
    "repetition_complaint",
    "direct_answer_only",
    "terminal_close",
    "rejection",
    "call_screening",
}
ASR_PARTIAL_FAST_MARKERS = (
    "喂",
    "你谁",
    "谁啊",
    "谁呀",
    "你是谁",
    "哪位",
    "干嘛",
    "做什么",
    "什么事",
    "什么鬼",
    "什么意思",
    "啥意思",
    "你说",
    "说你说",
    "说您说",
    "方便你说",
    "方便您说",
    "方便说",
    "你方便说",
    "您方便说",
    "继续说",
    "你继续",
    "说吧",
    "讲吧",
    "可以",
    "好的",
    "是的",
    "对的",
    "没错",
    "说一下",
    "讲一下",
    "可以说",
    "可以你说",
    "怎么不说",
    "听不清",
    "没听清",
    "不说话",
    "不会说话",
    "直接说",
    "别绕",
    "收费",
    "怎么收费",
    "价格",
    "报价",
    "多少钱",
    "费用",
    "不需要",
    "不需",
    "不用",
    "不要",
    "不行",
    "不是",
    "另一个",
    "其他微信",
    "加微信",
    "加我微信",
    "发资料",
    "发案例",
    "发给我",
    "发过来",
    "发一下",
    "给我发",
    "了解一下",
    "想了解",
    "想都想",
    "都",
    "都想",
    "都想了解",
    "都行",
    "都可以",
    "都是",
    "想做",
    "看看",
    "怎么合作",
    "下一步",
)
ASR_PARTIAL_COMPLETE_QUESTION_MARKERS = (
    "详细说一下",
    "详细讲一下",
    "具体说一下",
    "介绍一下",
    "说一下吗",
    "讲一下吗",
    "怎么做",
    "怎么合作",
    "流程",
    "有什么优势",
    "有什么用",
    "有啥用",
    "多少钱",
    "费用",
    "收费",
    "价格",
    "报价",
    "成本",
    "手机号",
    "手机号码",
    "电话号码",
    "号码",
    "加微信",
    "加我微信",
    "了解一下",
    "想了解",
    "想做",
    "发过来",
    "发一下",
    "看看",
    "怎么合作",
    "下一步",
    "发资料",
    "发案例",
    "达不到",
    "曝光",
    "投流",
    "获客",
    "客源",
    "上架",
    "保证",
    "多少客户",
    "多少单",
    "到店客流",
)
ASR_SIGNIFICANT_QUESTION_MARKERS = (
    "是不是",
    "要不要",
    "是否",
    "怎么",
    "怎么能",
    "怎么看",
    "吗",
    "呢",
    "还是",
)
ASR_SIGNIFICANT_BUSINESS_KEYWORDS = (
    "团购券",
    "券",
    "搜索",
    "不搜索",
    "客户看到",
    "用户看到",
    "看到我",
    "看到券",
    "同城推荐",
    "推荐流",
    "视频",
    "做视频",
    "拍视频",
    "发视频",
    "主页",
    "入口",
    "曝光",
    "投流",
    "获客",
    "客源",
    "上架",
)
OMNI_CUMULATIVE_FILLER_COMPACTS = {
    "喂",
    "喂喂",
    "在吗",
    "你在吗",
    "喂你在吗",
    "听得到吗",
    "听得到",
    "现在",
    "毛毛",
    "有毛有",
    "此通话将录音",
    "通话将录音",
    "将录音",
}
ASR_AUDIO_QUALITY_COMPLAINT_MARKERS = (
    "卡顿",
    "一卡一卡",
    "卡了",
    "太卡",
    "很卡",
    "这么卡",
    "那么卡",
    "延迟",
    "迟钝",
    "太慢",
    "很慢",
    "慢半拍",
    "像电影",
    "电影",
    "电影慢",
    "断断续续",
    "断了",
    "听不清",
    "没听清",
    "不清楚",
    "不说话",
    "不会说话",
    "你说话",
    "你讲话",
)
ASR_AUDIO_QUALITY_INCOMPLETE_SUFFIXES = (
    "怎么",
    "怎么那",
    "怎么这么",
    "怎么那么",
    "说话怎么",
    "说话怎么那",
    "讲话怎么",
    "讲话怎么那",
    "这么",
    "那么",
    "那",
)
ASR_PARTIAL_SHORT_FAST_COMPACTS = {
    "你说",
    "说你说",
    "说您说",
    "方便你说",
    "方便您说",
    "方便说",
    "你方便说",
    "您方便说",
    "继续说",
    "你继续",
    "说吧",
    "讲吧",
    "可以",
    "好的",
    "是的",
    "对的",
    "没错",
    "说一下",
    "讲一下",
    "可以说",
    "可以你说",
    "想都想",
    "都",
    "都想",
    "都想了解",
    "都行",
    "都可以",
    "都是",
    "不是",
    "不是的",
    "不行",
}
OPENING_RAW_BARGE_PROTECT_SECONDS = 1.8
_DOWNSAMPLE_FACTOR = 3
_DOWNSAMPLE_FIR_TAPS = 31
_DOWNSAMPLE_CUTOFF = 3600 / 24000


def _build_downsample_taps() -> tuple[float, ...]:
    center = (_DOWNSAMPLE_FIR_TAPS - 1) / 2
    taps: list[float] = []
    for index in range(_DOWNSAMPLE_FIR_TAPS):
        distance = index - center
        if abs(distance) < 1e-9:
            sinc = 2 * _DOWNSAMPLE_CUTOFF
        else:
            sinc = math.sin(2 * math.pi * _DOWNSAMPLE_CUTOFF * distance) / (math.pi * distance)
        window = 0.54 - 0.46 * math.cos(2 * math.pi * index / (_DOWNSAMPLE_FIR_TAPS - 1))
        taps.append(sinc * window)
    total = sum(taps) or 1.0
    return tuple(tap / total for tap in taps)


_DOWNSAMPLE_TAPS = _build_downsample_taps()


def _compact_customer_text(text: str) -> str:
    return "".join(
        char.lower()
        for char in text
        if char not in " \t\r\n。！？?!，,、.；;：:\"'“”‘’（）()[]【】"
    )


def _is_business_category_signal(text: str) -> bool:
    compact = _compact_customer_text(text)
    if not compact:
        return False
    if any(marker in compact for marker in ("不是", "不做", "没有", "没做", "不需要")):
        return False
    return any(marker in compact for marker in BUSINESS_CATEGORY_MARKERS)


def _is_wechat_affirmative_text(text: str) -> bool:
    compact = _compact_customer_text(text)
    if not compact:
        return False
    if any(marker in compact for marker in ("不行", "不用", "不要", "不加", "不发", "不是")):
        return False
    if compact in {
        "是",
        "是的",
        "是啊",
        "对",
        "对的",
        "对啊",
        "嗯",
        "嗯嗯",
        "好",
        "好的",
        "好啊",
        "可以",
        "可以的",
        "可以啊",
        "行",
        "行啊",
        "没问题",
        "没错",
        "对就是",
        "发吧",
        "加吧",
        "你加吧",
    }:
        return True
    return any(
        marker in compact
        for marker in (
            "可以加",
            "你加我",
            "加我",
            "加一下",
            "发过来",
            "发来",
            "发一下",
            "你发我",
            "给我发",
            "发我",
            "微信聊",
            "微信发",
        )
    )


def _is_identity_question_text(compact_text: str) -> bool:
    compact = compact_text or ""
    if not compact:
        return False
    return any(
        marker in compact
        for marker in (
            "你是谁",
            "你们是谁",
            "你哪位",
            "您哪位",
            "哪家公司",
            "哪个公司",
            "什么公司",
            "你们公司",
            "你们是干嘛",
            "你是干嘛",
            "你们干嘛",
            "你干嘛",
            "你们是干什么",
            "你是干什么",
            "你们干什么",
            "你干什么",
            "你们做什么",
            "你做什么",
            "做什么的",
            "什么业务",
        )
    )


def _is_no_videohao_prior_knowledge(compact_text: str) -> bool:
    compact = compact_text or ""
    if not compact:
        return False
    if any(marker in compact for marker in ("没兴趣", "不感兴趣", "不需要", "不用", "不要", "别打")):
        return False
    return compact in {"没有", "没有啊", "没", "没啊", "没了解", "没了解过", "不了解", "没听过"} or any(
        marker in compact for marker in ("没了解过", "没有了解过", "不了解这个", "没听过")
    )


def _is_interest_to_learn_signal(text: str) -> bool:
    compact = _compact_customer_text(text)
    if not compact:
        return False
    if any(marker in compact for marker in ("不需要", "不用", "不要", "没兴趣", "不感兴趣", "别发", "不加")):
        return False
    if compact in {
        "要",
        "需要",
        "需要的",
        "要的",
        "想要",
        "有需要",
        "有",
        "可以了解",
        "了解",
        "都",
        "都是",
        "都行",
        "都可以",
        "想都想",
        "都想",
        "都想都想",
    }:
        return True
    direct_markers = (
        "了解一下",
        "我了解",
        "想了解",
        "可以了解",
        "都想了解",
        "都想",
        "想都想",
        "都行",
        "都可以",
        "都是",
        "想看",
        "看一下",
        "看看",
        "发我",
        "发给我",
        "给我发",
        "发过来",
        "发来",
        "发一下",
        "发资料",
        "发案例",
        "资料发",
        "案例发",
        "有兴趣",
        "感兴趣",
        "可以试",
        "试一下",
        "先试",
        "想试",
        "想做",
        "要做",
        "准备做",
        "考虑做",
        "想弄",
        "怎么合作",
        "合作一下",
        "怎么开通",
        "怎么弄",
        "怎么办理",
        "下一步",
        "后面怎么",
        "后续怎么",
        "那就做",
        "可以做",
    )
    if any(marker in compact for marker in direct_markers):
        return True
    return ("想" in compact or "要" in compact or "可以" in compact) and any(
        marker in compact for marker in ("做", "了解", "看看", "资料", "案例", "合作", "开通", "办理")
    )


def _reply_has_solution_intro(reply: str) -> bool:
    compact = _compact_customer_text(reply or "")
    if not compact:
        return False
    return any(
        marker in compact
        for marker in (
            "视频号团购",
            "团购套餐",
            "同城曝光",
            "客单价",
            "核销",
            "到店数据",
            "咨询和到店",
            "小范围测",
            "小范围测试",
            "品类诊断",
            "上架测试",
            "同品类案例",
        )
    )


def _is_latency_or_audio_quality_complaint(text: str) -> bool:
    compact = _compact_customer_text(text)
    if not compact:
        return False
    if any(marker in compact for marker in ASR_AUDIO_QUALITY_COMPLAINT_MARKERS):
        return True
    return "卡" in compact and not any(marker in compact for marker in ("卡券", "会员卡", "银行卡"))


def _is_complete_audio_quality_complaint(text: str) -> bool:
    compact = _compact_customer_text(text)
    if not _is_latency_or_audio_quality_complaint(text):
        return False
    if has_incomplete_realtime_partial(text):
        return False
    if any(compact.endswith(suffix) for suffix in ASR_AUDIO_QUALITY_INCOMPLETE_SUFFIXES):
        return False
    if any(marker in compact for marker in ("听不清", "没听清", "不清楚", "断断续续", "不会说话", "不说话")):
        return len(compact) >= 3
    if "卡" in compact or "慢" in compact or "延迟" in compact:
        return len(compact) >= 5
    return len(compact) >= ASR_PARTIAL_MIN_COMPACT_CHARS


def _has_fast_asr_marker(compact: str) -> bool:
    if compact in ASR_PARTIAL_SHORT_FAST_COMPACTS:
        return True
    for marker in ASR_PARTIAL_FAST_MARKERS:
        if marker in ASR_PARTIAL_SHORT_FAST_COMPACTS:
            continue
        if marker in compact:
            return True
    return False


def _is_strong_terminal_close_text(text: str) -> bool:
    normalized = normalize_realtime_sales_text(text).normalized_text or text
    compact = _compact_customer_text(normalized)
    if not compact:
        return False
    if compact in {
        "挂了",
        "再见",
        "拜拜",
        "不聊了",
        "不说了",
        "不用",
        "不用了",
        "不要",
        "不要了",
        "不需要",
        "不需要了",
        "我不要",
        "我不用",
        "我不需要",
        "暂时不需要",
        "没兴趣",
    }:
        return True
    return any(marker in normalized or marker in compact for marker in STRONG_TERMINAL_CLOSE_MARKERS)


def _is_soft_busy_customer_text(text: str) -> bool:
    normalized = normalize_realtime_sales_text(text).normalized_text or text
    compact = _compact_customer_text(normalized)
    return bool(compact and any(marker in normalized or marker in compact for marker in SOFT_BUSY_MARKERS))


def _looks_like_open_nonbusiness_question_partial(text: str) -> bool:
    compact = _compact_customer_text(text)
    if not compact:
        return False
    if any(mark in text for mark in ("？", "?", "。", "！", "!")) or compact.endswith(("吗", "呢", "嘛")):
        return False
    if _is_complete_actionable_asr_partial(text) or _has_significant_business_question(text):
        return False
    return any(marker in compact for marker in ("会不会", "是不是", "为什么", "为啥", "怎么回事", "怎么搞"))


def _has_significant_business_question(text: str) -> bool:
    normalized = normalize_realtime_sales_text(text).normalized_text or text
    compact = _compact_customer_text(normalized)
    if not compact:
        return False
    has_question = any(marker in compact for marker in ASR_SIGNIFICANT_QUESTION_MARKERS)
    has_business_keyword = any(keyword in compact for keyword in ASR_SIGNIFICANT_BUSINESS_KEYWORDS)
    return has_question and has_business_keyword


def _adds_significant_business_question(current: str, previous: str) -> bool:
    if not current or not previous:
        return False
    if has_incomplete_realtime_partial(previous) and not has_incomplete_realtime_partial(current):
        return _has_significant_business_question(current)
    current_norm = normalize_realtime_sales_text(current).normalized_text or current
    previous_norm = normalize_realtime_sales_text(previous).normalized_text or previous
    current_compact = _compact_customer_text(current_norm)
    previous_compact = _compact_customer_text(previous_norm)
    if not current_compact or not previous_compact:
        return False
    if len(current_compact) <= len(previous_compact) + 6:
        return False
    previous_keywords = {
        keyword for keyword in ASR_SIGNIFICANT_BUSINESS_KEYWORDS if keyword in previous_compact
    }
    current_keywords = {
        keyword for keyword in ASR_SIGNIFICANT_BUSINESS_KEYWORDS if keyword in current_compact
    }
    added_keywords = current_keywords - previous_keywords
    if added_keywords and _has_significant_business_question(current_norm):
        return True
    if previous_compact in current_compact:
        suffix = current_compact.split(previous_compact, 1)[-1]
        return len(suffix) >= 6 and _has_significant_business_question(suffix)
    return False


def _adds_meaningful_question_detail(current: str, previous: str) -> bool:
    current_compact = _compact_customer_text(current)
    previous_compact = _compact_customer_text(previous)
    if not current_compact or not previous_compact:
        return False
    if previous_compact not in current_compact:
        return False
    if len(current_compact) <= len(previous_compact) + 3:
        return False
    if _is_complete_audio_quality_complaint(current) and not _is_complete_audio_quality_complaint(previous):
        return True
    return any(marker in current_compact for marker in ("会不会", "是不是", "为什么", "为啥", "怎么", "信号不好"))


def _is_complete_actionable_asr_partial(text: str) -> bool:
    normalized = normalize_realtime_sales_text(text).normalized_text or text
    compact = _compact_customer_text(normalized)
    if len(compact) < ASR_PARTIAL_MIN_COMPACT_CHARS:
        return False
    if compact.startswith("你需求什么"):
        return False
    has_question_shape = any(marker in text for marker in ("？", "?")) or compact.endswith(("吗", "呢", "嘛"))
    has_actionable_marker = any(marker in compact for marker in ASR_PARTIAL_COMPLETE_QUESTION_MARKERS)
    return has_question_shape and has_actionable_marker


def _is_actionable_asr_clause(text: str) -> bool:
    compact = _compact_customer_text(text)
    if len(compact) < ASR_PARTIAL_MIN_COMPACT_CHARS:
        return False
    if _is_complete_audio_quality_complaint(text):
        return True
    if _looks_like_open_nonbusiness_question_partial(text):
        return False
    signal = classify_realtime_call_input(text)
    if signal in ASR_PARTIAL_FAST_SIGNALS:
        return True
    if _has_fast_asr_marker(compact):
        return True
    if _is_complete_actionable_asr_partial(text):
        return True
    return _has_significant_business_question(text)


def _looks_like_incomplete_wechat_phone_confirmation_text(text: str) -> bool:
    compact = _compact_customer_text(text)
    if not compact or _is_wechat_phone_confirmation_partial(text):
        return False
    if any(marker in compact for marker in ("不是", "另一个", "其他微信", "换一个")):
        return False
    phone_markers = ("手机号", "手机号码", "这手机号", "这个手机号", "这个号", "这个号码")
    return any(marker in compact for marker in phone_markers) and any(
        marker in compact for marker in ("是", "就", "就是", "我")
    )


def _stable_asr_partial_turn_text(text: str) -> str:
    clean = " ".join(text.strip().split())
    if not clean:
        return ""
    if _is_wechat_phone_confirmation_partial(clean):
        return clean
    clauses = [part.strip() for part in re.split(r"[。！？?!；;，,、]+", clean) if part.strip()]
    if len(clauses) <= 1:
        return clean
    if _looks_like_incomplete_wechat_phone_confirmation_text(clauses[-1]):
        return clauses[-1]
    for clause in reversed(clauses):
        compact = _compact_customer_text(clause)
        if len(compact) < 2 or compact in OMNI_CUMULATIVE_FILLER_COMPACTS:
            continue
        if len(compact) <= 3 and not _is_actionable_asr_clause(clause):
            continue
        if _is_actionable_asr_clause(clause):
            return clause
    return clean


def _is_wechat_phone_confirmation_partial(text: str) -> bool:
    compact = _compact_customer_text(text)
    if "微信" not in compact:
        return False
    has_phone_marker = any(
        marker in compact
        for marker in ("手机号", "手机号码", "这手机号", "这个手机号", "这个号", "这个号码")
    )
    if not has_phone_marker:
        return False
    if any(marker in compact for marker in ("不是", "另一个", "其他微信", "换一个")):
        return True
    return any(
        marker in compact
        for marker in (
            "手机号就是微信",
            "手机号码就是微信",
            "微信就是手机号",
            "微信是手机号",
            "这手机号是我微信",
            "这手机号是我的微信",
            "这手机号就是我微信",
            "这手机号就是我的微信",
            "这个手机号是我微信",
            "这个手机号是我的微信",
            "这个手机号就是我微信",
            "这个手机号就是我的微信",
            "这个号是我微信",
            "这个号是我的微信",
            "是我微信",
            "是我的微信",
            "就是我微信",
            "就是我的微信",
        )
    )


def should_commit_stable_asr_partial(text: str) -> bool:
    compact = _compact_customer_text(text)
    if compact == "喂":
        return True
    if compact == "都":
        return True
    if len(compact) < 2:
        return False
    if _is_wechat_phone_confirmation_partial(text):
        return True
    if _is_latency_or_audio_quality_complaint(text):
        return _is_complete_audio_quality_complaint(text)
    if has_incomplete_realtime_partial(text):
        return False
    if _looks_like_open_nonbusiness_question_partial(text):
        return False
    signal = classify_realtime_call_input(text)
    if signal in {"empty", "system_prompt"}:
        return False
    if signal in ASR_PARTIAL_FAST_SIGNALS:
        return True
    if _has_fast_asr_marker(compact):
        return True
    if _is_complete_actionable_asr_partial(text):
        return True
    if _has_significant_business_question(text):
        return True
    return False


def _asr_partial_stable_delay_seconds(text: str) -> float:
    compact = _compact_customer_text(text)
    if _is_wechat_phone_confirmation_partial(text):
        return 0.18
    if _is_latency_or_audio_quality_complaint(text):
        return 0.9
    signal = classify_realtime_call_input(text)
    if signal in ASR_PARTIAL_FAST_SIGNALS or _has_fast_asr_marker(compact):
        return ASR_PARTIAL_STABLE_SECONDS
    if _is_complete_actionable_asr_partial(text) or _has_significant_business_question(text):
        return 0.25
    return ASR_PARTIAL_STABLE_SECONDS + 0.35


def _latest_actionable_omni_turn_text(text: str) -> str:
    clean = " ".join(text.strip().split())
    if not clean:
        return ""
    clauses = [part.strip() for part in re.split(r"[。！？?!；;，,、]+", clean) if part.strip()]
    if len(clauses) <= 1:
        return clean
    for clause in reversed(clauses):
        if _is_complete_audio_quality_complaint(clause):
            return clause
    for clause in reversed(clauses):
        compact = _compact_customer_text(clause)
        if len(compact) < 2 or compact in OMNI_CUMULATIVE_FILLER_COMPACTS:
            continue
        signal = classify_realtime_call_input(clause)
        if signal not in {"empty", "system_prompt"}:
            if len(compact) <= 3 and not _is_actionable_asr_clause(clause):
                continue
            return clause
    return clauses[-1] if clauses else clean


@dataclass(frozen=True)
class BridgeConfig:
    bind_host: str
    port: int
    asr_model: str
    tts_model: str
    tts_voice_id: str
    tts_voice_name: str
    tts_voice_type: str
    conversation_mode: str
    omni_model: str
    omni_url: str
    omni_voice: str
    omni_input_transcription_model: str
    opening_text: str
    log_path: Path
    workspace: str | None
    barge_rms_threshold: int = 2200
    barge_frames: int = 6
    tts_gain: float = 1.0
    opening_grace_seconds: float = 1.2
    debug_audio_capture_enabled: bool = False
    debug_audio_capture_dir: Path = Path("/tmp/ai-acq-realtime-audio")
    audio_quality_enabled: bool = True
    answer_classification_seconds: float = 7.0
    call_screening_hangup_seconds: float = 12.0
    no_response_hangup_seconds: float = 20.0


class JsonlEventLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(self, event_type: str, **fields: Any) -> None:
        payload = {
            "at": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "type": event_type,
            **fields,
        }
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        print(line, flush=True)


class CallAudioCapture:
    def __init__(self, call_id: str, directory: Path) -> None:
        safe_call_id = "".join(char for char in call_id if char.isalnum() or char in {"-", "_"}) or "unknown"
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.inbound_path = self.directory / f"{safe_call_id}.inbound.wav"
        self.outbound_raw_path = self.directory / f"{safe_call_id}.outbound.raw.wav"
        self.outbound_path = self.directory / f"{safe_call_id}.outbound.wav"
        self._lock = threading.Lock()
        self._inbound = self._open_wave(self.inbound_path)
        self._outbound_raw = self._open_wave(self.outbound_raw_path)
        self._outbound = self._open_wave(self.outbound_path)
        self.closed = False

    @staticmethod
    def _open_wave(path: Path) -> wave.Wave_write:
        handle = wave.open(str(path), "wb")
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        return handle

    def write_inbound(self, payload: bytes) -> None:
        self._write(self._inbound, payload)

    def write_outbound(self, payload: bytes) -> None:
        self._write(self._outbound, payload)

    def write_outbound_raw(self, payload: bytes) -> None:
        self._write(self._outbound_raw, payload)

    def _write(self, handle: wave.Wave_write, payload: bytes) -> None:
        if self.closed or not payload:
            return
        with self._lock:
            if not self.closed:
                handle.writeframesraw(payload)

    def close(self) -> dict[str, str]:
        with self._lock:
            if not self.closed:
                self._inbound.close()
                self._outbound_raw.close()
                self._outbound.close()
                self.closed = True
        return {
            "inboundPath": str(self.inbound_path),
            "outboundRawPath": str(self.outbound_raw_path),
            "outboundPath": str(self.outbound_path),
        }


class AudioSocketProtocolError(RuntimeError):
    pass


def _is_socket_closed_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return False
    message = str(exc)
    if isinstance(exc, AudioSocketProtocolError) and "AudioSocket connection closed" in message:
        return True
    errno_value = getattr(exc, "errno", None)
    if errno_value in {errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN, errno.EBADF}:
        return True
    return any(
        marker in message
        for marker in (
            "AudioSocket connection closed",
            "Broken pipe",
            "Connection reset by peer",
            "Bad file descriptor",
        )
    )


class CallRecognitionCallback(RecognitionCallback):
    def __init__(self, call: "AudioSocketCallSession") -> None:
        self.call = call
        self.last_text = ""

    def on_open(self) -> None:
        self.call.logger.emit("asr_open", callId=self.call.call_id, model=self.call.config.asr_model)

    def on_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if not isinstance(sentence, dict):
            return
        text = str(sentence.get("text") or "").strip()
        is_final = RecognitionResult.is_sentence_end(sentence)
        if text and text != self.last_text:
            event_text = text
            normalization = normalize_realtime_sales_text(text) if is_final else None
            if normalization and normalization.changed and normalization.normalized_text:
                event_text = normalization.normalized_text
            self.call.customer_activity_event.set()
            asr_fields: dict[str, Any] = {
                "callId": self.call.call_id,
                "text": event_text,
                "beginMs": sentence.get("begin_time"),
                "endMs": sentence.get("end_time"),
            }
            if normalization and normalization.changed:
                asr_fields["rawText"] = text
                asr_fields["fixes"] = list(normalization.fixes)
            self.call.logger.emit("asr_final" if is_final else "asr_partial", **asr_fields)
            self.call.handle_answer_text(text, is_final=is_final)
            if is_final:
                self.call.commit_asr_final_text(event_text)
            else:
                self.call.note_asr_partial_text(text)
            self.last_text = text

    def on_error(self, message: object) -> None:
        self.call.logger.emit("asr_error", callId=self.call.call_id, error=_safe_error_text(message))

    def on_complete(self) -> None:
        self.call.logger.emit("asr_complete", callId=self.call.call_id)

    def on_close(self) -> None:
        self.call.logger.emit("asr_close", callId=self.call.call_id)


class CallOmniCallback(OmniRealtimeCallback):
    def __init__(self, call: "OmniAudioSocketCallSession") -> None:
        self.call = call

    def on_open(self) -> None:
        self.call.logger.emit("omni_open", callId=self.call.call_id, model=self.call.config.omni_model)

    def on_close(self, close_status_code: object, close_msg: object) -> None:
        self.call.logger.emit(
            "omni_close",
            callId=self.call.call_id,
            code=str(close_status_code),
            message=str(close_msg),
        )
        self.call.handle_omni_closed(close_status_code, close_msg)

    def on_event(self, response: dict[str, Any]) -> None:
        event_type = str(response.get("type") or "")
        if event_type == "session.updated":
            session = response.get("session") if isinstance(response.get("session"), dict) else {}
            self.call.mark_omni_session_ready()
            self.call.logger.emit(
                "omni_session_updated",
                callId=self.call.call_id,
                model=session.get("model") or self.call.config.omni_model,
                voice=session.get("voice") or self.call.config.omni_voice,
            )
            return
        if event_type == "input_audio_buffer.speech_started":
            self.call.handle_omni_speech_started()
            return
        if event_type == "conversation.item.input_audio_transcription.completed":
            text = str(response.get("transcript") or "").strip()
            if text:
                self.call.handle_omni_transcription(text)
            return
        if event_type == "conversation.item.input_audio_transcription.failed":
            self.call.logger.emit(
                "asr_error",
                callId=self.call.call_id,
                provider="qwen_omni",
                error=json.dumps(response, ensure_ascii=False)[:600],
            )
            return
        if event_type in {
            "input_audio_buffer.speech_stopped",
            "input_audio_buffer.committed",
            "input_audio_buffer.cleared",
        }:
            self.call.handle_omni_input_buffer_event(event_type, response)
            return
        if event_type == "response.created":
            response_id = _omni_response_id_from_event(response)
            self.call.start_omni_response(response_id)
            return
        if event_type == "response.audio_transcript.delta":
            self.call.append_omni_transcript_delta(str(response.get("delta") or ""), _omni_response_id_from_event(response))
            return
        if event_type == "response.audio_transcript.done":
            self.call.finish_omni_transcript(
                str(response.get("transcript") or ""),
                _omni_response_id_from_event(response),
            )
            return
        if event_type == "response.audio.delta":
            self.call.play_omni_audio_delta(str(response.get("delta") or ""), _omni_response_id_from_event(response))
            return
        if event_type == "response.done":
            self.call.finish_omni_response(_omni_response_id_from_event(response))
            return
        if event_type == "error" or response.get("error"):
            self.call.logger.emit("omni_error", callId=self.call.call_id, error=json.dumps(response, ensure_ascii=False)[:600])


def _omni_response_id_from_event(response: dict[str, Any]) -> str:
    for key in ("response_id", "responseId"):
        value = response.get(key)
        if value:
            return str(value)
    nested = response.get("response")
    if isinstance(nested, dict) and nested.get("id"):
        return str(nested.get("id"))
    return ""


class AudioSocketCallSession:
    def __init__(self, conn: socket.socket, peer: tuple[str, int], config: BridgeConfig, logger: JsonlEventLogger) -> None:
        self.conn = conn
        self.peer = peer
        self.config = config
        self.logger = logger
        self.call_id = ""
        self.customer_texts: queue.Queue[tuple[int, str]] = queue.Queue()
        self.stop_event = threading.Event()
        self.interrupt_event = threading.Event()
        self.speaking_event = threading.Event()
        self.customer_activity_event = threading.Event()
        self.send_lock = threading.Lock()
        self.playback_lock = threading.Lock()
        self.generation_lock = threading.Lock()
        self.asr_partial_lock = threading.Lock()
        self.speech_state_lock = threading.Lock()
        self.speech_generation = 0
        self.speech_jobs = 0
        self.close_state_lock = threading.Lock()
        self._loud_frames = 0
        self._last_barge_at = 0.0
        self._barge_forward_until = 0.0
        self._recognition: Recognition | None = None
        self._audio_capture: CallAudioCapture | None = None
        self._intent_counts: dict[str, int] = {}
        self._conversation_history: list[dict[str, str]] = []
        self._call_history: list[dict[str, str]] = []
        self._sales_fsm = SalesStateMachine()
        self._answer_classifier = AnswerClassifier(max_wait_seconds=self.config.answer_classification_seconds)
        self._answer_classification_reported: CallAnswerType | None = None
        self._audio_quality = RealtimeAudioQualityChain(enabled=self.config.audio_quality_enabled)
        self._audio_quality_frame_count = 0
        self._human_speech_confirmed = False
        self._call_screening_seen = False
        self._call_screening_answered = False
        self._call_screening_hangup_generation = 0
        self._no_response_hangup_generation = 0
        self._no_response_hangup_active = False
        self._system_prompt_seen = False
        self._opening_started = False
        self._opening_playback_active = False
        self._opening_started_at = 0.0
        self._opening_raw_barge_protect_until = 0.0
        self._opening_raw_barge_protected_logged = False
        self._last_remote_audio_at = 0.0
        self._last_remote_speech_started_at = 0.0
        self._asr_partial_generation = 0
        self._asr_partial_text = ""
        self._last_committed_customer_text = ""
        self._last_committed_customer_at = 0.0
        self._recent_committed_customer_turns: list[tuple[str, float]] = []
        self._last_remote_audio_sample_at = 0.0
        self._remote_audio_sample_peak = 0
        self._last_outbound_audio_at = 0.0
        self._startup_keepalive_active = threading.Event()
        self._intentional_close_reason = ""
        self._call_closed_emitted = False
        self._learning_recorded = False
        self._call_context: dict[str, Any] = {}
        self._turn_thread = threading.Thread(target=self._turn_worker, name="ai-acq-audiosocket-turn", daemon=True)

    def run(self) -> None:
        self.conn.settimeout(1.0)
        self.logger.emit("socket_connected", peer=f"{self.peer[0]}:{self.peer[1]}", voice=self.config.tts_voice_name)
        try:
            if not self._await_call_uuid():
                return
            self.logger.emit("call_connected", callId=self.call_id, peer=f"{self.peer[0]}:{self.peer[1]}", voice=self.config.tts_voice_name)
            self._start_startup_keepalive()
            self._start_asr()
            self._turn_thread.start()
            threading.Thread(target=self._speak_opening_after_grace, daemon=True).start()
            self._read_loop()
        except Exception as exc:  # noqa: BLE001
            if self._is_intentional_socket_close(exc):
                self._emit_call_closed_once(
                    self._intentional_close_reason,
                    detail="客户明确结束后系统主动关闭 AudioSocket。",
                    source="intentional_close",
                )
            elif _is_socket_closed_error(exc):
                self._emit_call_closed_once(
                    "remote_hangup",
                    detail="远端关闭 AudioSocket，按正常挂断收口。",
                    source="audiosocket_closed",
                )
            else:
                self.logger.emit("call_error", callId=self.call_id, error=str(exc))
        finally:
            self.stop_event.set()
            self.interrupt_event.set()
            self._record_learning_summary()
            self._stop_startup_keepalive()
            self._stop_asr()
            self._stop_audio_capture()
            try:
                self.conn.close()
            except OSError:
                pass
            self.logger.emit("call_disconnected", callId=self.call_id)

    def _is_intentional_socket_close(self, exc: Exception) -> bool:
        return bool(self._intentional_close_reason) and "AudioSocket connection closed" in str(exc)

    def _emit_call_closed_once(self, reason: str, *, detail: str, source: str = "") -> None:
        clean_reason = reason or "remote_hangup"
        with self.close_state_lock:
            if self._call_closed_emitted:
                return
            self._call_closed_emitted = True
            if not self._intentional_close_reason:
                self._intentional_close_reason = clean_reason
        fields: dict[str, Any] = {
            "callId": self.call_id,
            "reason": clean_reason,
            "detail": detail,
        }
        if source:
            fields["source"] = source
        if self.config.conversation_mode == "omni":
            fields["mode"] = "omni"
        self.logger.emit("call_closed", **fields)

    def _record_learning_summary(self) -> None:
        if self._learning_recorded or not self.call_id:
            return
        self._learning_recorded = True
        try:
            lesson = record_realtime_call_learning(
                call_id=self.call_id,
                conversation_history=list(self._call_history or self._conversation_history),
                close_reason=self._intentional_close_reason,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("call_learning_error", callId=self.call_id, error=str(exc))
            return
        if lesson:
            self.logger.emit(
                "call_learning_summary",
                callId=self.call_id,
                topics=lesson.get("topics", {}),
                avoidPhrases=lesson.get("avoidPhrases", []),
                nextGuidance=lesson.get("nextGuidance", []),
            )

    def _record_realtime_intent_signal(
        self,
        text: str,
        intent: str,
        signal: str,
        source: str,
        *,
        force: bool = False,
        evidence: str | None = None,
        latest_signal: str | None = None,
        intent_level: str = "A",
        intent_score: int = 92,
        need_handoff: bool = True,
    ) -> None:
        try:
            result = record_realtime_intent_signal(
                call_id=self.call_id,
                context=self._call_context,
                text=text,
                intent=intent,
                signal=signal,
                source=source,
                force=force,
                evidence=evidence,
                latest_signal=latest_signal,
                intent_level=intent_level,
                intent_score=intent_score,
                need_handoff=need_handoff,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("intent_capture_error", callId=self.call_id, text=text, intent=intent, error=str(exc))
            return
        if result:
            self.logger.emit(
                "intent_customer_upserted",
                callId=self.call_id,
                text=text,
                intent=intent,
                customerId=result.get("customerId"),
                intentLevel=result.get("intentLevel"),
                sourceRecordId=result.get("sourceRecordId"),
                summary=result.get("summary"),
            )

    def _record_realtime_wechat_signal(
        self,
        text: str,
        signal: str,
        source: str,
        *,
        wechat_id: str,
        wechat_is_phone: bool,
        summary: str,
    ) -> None:
        try:
            result = record_realtime_wechat_signal(
                call_id=self.call_id,
                context=self._call_context,
                text=text,
                signal=signal,
                source=source,
                wechat_id=wechat_id,
                wechat_is_phone=wechat_is_phone,
                summary=summary,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.emit(
                "intent_capture_error",
                callId=self.call_id,
                text=text,
                intent="加微信/发资料",
                error=str(exc),
                source=source,
            )
            return
        if result:
            self.logger.emit(
                "wechat_capture_recorded",
                callId=self.call_id,
                text=text,
                customerId=result.get("customerId"),
                sourceRecordId=result.get("sourceRecordId"),
                wechatId=result.get("wechatId"),
                wechatIsPhone=result.get("wechatIsPhone"),
                summary=result.get("summary"),
                source=source,
            )

    def _merchant_name(self) -> str:
        raw = str(
            self._call_context.get("merchantName")
            or self._call_context.get("merchant_name")
            or self._call_context.get("leadName")
            or self._call_context.get("shopName")
            or ""
        ).strip()
        clean = " ".join(raw.split())
        if clean and clean not in GENERIC_MERCHANT_NAMES:
            return clean
        return "您的门店"

    def _call_phone(self) -> str:
        return str(self._call_context.get("phone") or self._call_context.get("mobile") or "").strip()

    def _has_named_merchant(self) -> bool:
        return self._merchant_name() != "您的门店"

    def _merchant_subject(self) -> str:
        merchant = self._merchant_name()
        return f"{merchant}这边" if merchant != "您的门店" else "门店"

    def _merchant_context_instruction(self) -> str:
        merchant = self._merchant_name()
        if merchant == "您的门店":
            return "当前商户名称未知，通话中用“您门店”或“门店”称呼，不要编造店名。"
        return f"当前通话商户/店名：{merchant}。开场和后续回复可以自然称呼“{merchant}”，不要编造其他店名。"

    def _opening_text_for_call(self) -> str:
        merchant = self._merchant_name()
        if merchant == "您的门店":
            return "您好，我是做视频号团购到店获客的，想确认您门店需不需要微信同城曝光。"
        return f"喂，老板您好，是{merchant}吗？我是做视频号团购到店获客的，想确认您门店需不需要微信同城曝光。"

    def _screening_handoff_reply(self) -> str:
        return f"您好，我这边做视频号团购到店获客，来电想确认{self._merchant_subject()}微信同城曝光合作，麻烦转接负责人，谢谢。"

    def _identity_opening_reply(self) -> str:
        return f"您好，我在。我是做视频号团购到店获客的，给您来电是确认{self._merchant_subject()}微信同城曝光这块。"

    def _start_startup_keepalive(self) -> None:
        self._startup_keepalive_active.set()
        threading.Thread(target=self._startup_keepalive_loop, name="ai-acq-audiosocket-keepalive", daemon=True).start()

    def _stop_startup_keepalive(self) -> None:
        self._startup_keepalive_active.clear()

    def _startup_keepalive_loop(self) -> None:
        silence = b"\x00" * PCM_FRAME_BYTES
        sent = 0
        next_frame_at = time.perf_counter()
        while self._startup_keepalive_active.is_set() and not self.stop_event.is_set():
            if time.monotonic() - self._last_outbound_audio_at >= AUDIOSOCKET_IDLE_KEEPALIVE_GAP_SECONDS:
                try:
                    self._send_frame(AUDIO_SOCKET_KIND_AUDIO, silence)
                    self._last_outbound_audio_at = time.monotonic()
                except Exception as exc:  # noqa: BLE001
                    self.logger.emit("idle_keepalive_error", callId=self.call_id, error=str(exc))
                    self._close_after_socket_write_error("idle_keepalive", exc)
                    break
                sent += 1
            next_frame_at += PCM_FRAME_SECONDS
            time.sleep(max(0.0, next_frame_at - time.perf_counter()))
        self._startup_keepalive_active.clear()
        if sent:
            self.logger.emit("idle_keepalive_done", callId=self.call_id, frames=sent)

    def _close_after_socket_write_error(self, source: str, exc: Exception) -> None:
        if self.stop_event.is_set():
            return
        if _is_socket_closed_error(exc):
            self._emit_call_closed_once(
                "remote_hangup",
                detail="写入音频时发现远端已关闭 AudioSocket，按正常挂断收口。",
                source=source,
            )
        self.logger.emit(
            "socket_write_closed",
            callId=self.call_id,
            source=source,
            error=str(exc),
            detail="向 AudioSocket 写入音频失败，判定电话媒体链路已断开并立即结束本次会话。",
        )
        self.stop_event.set()
        self.interrupt_event.set()
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _await_call_uuid(self) -> bool:
        started = time.monotonic()
        while not self.stop_event.is_set() and time.monotonic() - started < 5:
            try:
                frame_type, payload = self._read_frame()
            except TimeoutError:
                continue
            if frame_type == AUDIO_SOCKET_KIND_UUID:
                self.call_id = _decode_call_id(payload)
                self.logger.emit("call_uuid", callId=self.call_id)
                self._call_context = claim_realtime_call_context(self.call_id)
                if self._call_context:
                    self.logger.emit(
                        "call_context_attached",
                        callId=self.call_id,
                        source="realtime_test_call",
                        merchantName=self._call_context.get("merchantName"),
                        requestedRoute=self._call_context.get("requestedRoute"),
                        effectiveRoute=self._call_context.get("effectiveRoute"),
                    )
                self._start_audio_capture()
                return True
            if frame_type == AUDIO_SOCKET_KIND_HANGUP:
                self.logger.emit("hangup_before_uuid")
                return False
            self.logger.emit("frame_before_uuid", frameType=frame_type, bytes=len(payload))
        self.logger.emit("uuid_timeout", peer=f"{self.peer[0]}:{self.peer[1]}")
        return False

    def _start_asr(self) -> None:
        runtime_config = get_runtime_ai_config()
        if not runtime_config.dashscope_api_key:
            raise AudioSocketProtocolError("缺少 DASHSCOPE_API_KEY，不能启动实时 ASR。")
        dashscope.api_key = runtime_config.dashscope_api_key
        callback = CallRecognitionCallback(self)
        self._recognition = Recognition(
            model=self.config.asr_model,
            callback=callback,
            format="pcm",
            sample_rate=8000,
            workspace=self.config.workspace,
            disfluency_removal_enabled=True,
        )
        self._recognition.start()

    def _stop_asr(self) -> None:
        if not self._recognition:
            return
        try:
            self._recognition.stop()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("asr_stop_error", callId=self.call_id, error=str(exc))
        self._recognition = None

    def _read_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                frame_type, payload = self._read_frame()
            except TimeoutError:
                continue
            if frame_type == AUDIO_SOCKET_KIND_HANGUP:
                self.logger.emit("hangup_frame", callId=self.call_id)
                self._emit_call_closed_once(
                    "remote_hangup",
                    detail="收到 AudioSocket 挂断帧，按正常远端挂断收口。",
                    source="hangup_frame",
                )
                break
            if frame_type == AUDIO_SOCKET_KIND_UUID:
                self.call_id = _decode_call_id(payload)
                self.logger.emit("call_uuid", callId=self.call_id)
                self._start_audio_capture()
                continue
            if frame_type == AUDIO_SOCKET_KIND_DTMF:
                self.logger.emit("dtmf", callId=self.call_id, digit=payload.decode("utf-8", errors="replace"))
                continue
            if frame_type == AUDIO_SOCKET_KIND_ERROR:
                self.logger.emit("audiosocket_error_frame", callId=self.call_id, payload=payload.hex())
                break
            if frame_type != AUDIO_SOCKET_KIND_AUDIO:
                self.logger.emit("unknown_frame", callId=self.call_id, frameType=frame_type, bytes=len(payload))
                continue
            self._handle_audio(payload)

    def _handle_audio(self, payload: bytes) -> None:
        if self._audio_capture:
            self._audio_capture.write_inbound(payload)
        rms = _pcm_rms(payload)
        now = time.monotonic()
        self._emit_remote_audio_sample(rms, now)
        self._handle_answer_audio(rms, now)
        if rms >= self.config.barge_rms_threshold:
            if now - self._last_remote_speech_started_at > 1.5:
                self._last_remote_speech_started_at = now
                self.logger.emit(
                    "remote_speech_started",
                    callId=self.call_id,
                    source="rms",
                    rms=rms,
                    detail="检测到客户开始说话，进入听完本轮再回复。",
                )
            self._note_customer_activity("remote_audio", now=now)
        if self.speaking_event.is_set():
            if now < self._barge_forward_until:
                if self._recognition:
                    self._recognition.send_audio_frame(payload)
                return
            if self._should_protect_opening_from_raw_barge(now, rms):
                self._loud_frames = 0
                if self._recognition:
                    self._recognition.send_audio_frame(payload)
                return
            if rms >= self.config.barge_rms_threshold:
                self._loud_frames += 1
            else:
                self._loud_frames = 0
            if self._loud_frames >= self.config.barge_frames and now - self._last_barge_at > 0.8:
                self._barge_forward_until = now + BARGE_AUDIO_FORWARD_SECONDS
                self.cancel_pending_speech("客户插话，停止后续 TTS 音频帧并继续听客户说话。", source="rms", rms=rms)
                if self._recognition:
                    self._recognition.send_audio_frame(payload)
            return
        self._loud_frames = 0
        if self._recognition:
            self._recognition.send_audio_frame(payload)

    def _should_protect_opening_from_raw_barge(self, now: float, rms: int) -> bool:
        if not self._opening_started or now > self._opening_raw_barge_protect_until:
            return False
        if self._human_speech_confirmed or self._last_committed_customer_text:
            return False
        if rms < self.config.barge_rms_threshold:
            return False
        if not self._opening_raw_barge_protected_logged:
            self._opening_raw_barge_protected_logged = True
            self.logger.emit(
                "opening_raw_barge_protected",
                callId=self.call_id,
                rms=rms,
                protectMs=int(max(0.0, self._opening_raw_barge_protect_until - now) * 1000),
                detail="首句刚开始播放时检测到对端问候音，先不断开首句，等待ASR确认后再接话。",
            )
        return True

    def _emit_remote_audio_sample(self, rms: int, now: float) -> None:
        self._remote_audio_sample_peak = max(self._remote_audio_sample_peak, rms)
        if now - self._last_remote_audio_sample_at < REMOTE_AUDIO_SAMPLE_INTERVAL_SECONDS:
            return
        self._last_remote_audio_sample_at = now
        peak = self._remote_audio_sample_peak
        self._remote_audio_sample_peak = rms
        self.logger.emit(
            "remote_audio_sample",
            callId=self.call_id,
            rms=rms,
            peakRms=peak,
            threshold=self.config.barge_rms_threshold,
            active=peak >= max(120, int(self.config.barge_rms_threshold * 0.35)),
        )

    def _handle_answer_audio(self, rms: int, now: float) -> None:
        answer_type = self._answer_classifier.on_audio_frame(rms, now)
        self._handle_answer_classification(answer_type, text="", source="audio")

    def handle_answer_text(self, text: str, *, is_final: bool) -> None:
        if text.strip():
            self._last_remote_audio_at = time.monotonic()
        classifier_text = text
        if classify_realtime_call_input(text) == "system_prompt":
            human_tail = extract_human_text_after_system_prompt(text)
            if human_tail:
                classifier_text = human_tail
        answer_type = self._answer_classifier.on_asr_text(classifier_text, is_final=is_final)
        self._handle_answer_classification(
            answer_type,
            text=classifier_text,
            source="asr_final" if is_final else "asr_partial",
        )

    def note_asr_partial_text(self, text: str) -> None:
        clean = " ".join(text.strip().split())
        if not clean:
            return
        self._note_customer_activity("asr_partial", text=clean)
        should_commit = should_commit_stable_asr_partial(clean)
        if not should_commit:
            with self.asr_partial_lock:
                if self._asr_partial_text and clean != self._asr_partial_text:
                    self._asr_partial_generation += 1
                    self._asr_partial_text = ""
            self.logger.emit(
                "turn_waiting_final",
                callId=self.call_id,
                text=clean,
                reason="incomplete_or_nonactionable_partial",
                detail="客户这句话还没有足够完整，继续听最终转写，避免抢答或重复旧问题。",
            )
            return
        with self.asr_partial_lock:
            self._asr_partial_generation += 1
            generation = self._asr_partial_generation
            self._asr_partial_text = clean
        delay = _asr_partial_stable_delay_seconds(clean)
        self.logger.emit(
            "turn_endpoint_candidate",
            callId=self.call_id,
            text=clean,
            waitMs=int(delay * 1000),
            detail="客户短句或完整问题已足够可答，若 ASR final 未到会先接话。",
        )
        threading.Thread(
            target=self._commit_stable_asr_partial_after_delay,
            args=(generation, clean, delay),
            name="ai-acq-asr-partial-turn",
            daemon=True,
        ).start()

    def commit_asr_final_text(self, text: str) -> None:
        self._cancel_pending_asr_partial_turn("asr_final")
        self.logger.emit(
            "turn_endpoint_final",
            callId=self.call_id,
            text=text,
            detail="ASR final 到达，客户本轮说话完成。",
        )
        self._commit_customer_text(text, source="asr_final", detail="客户说话完成，取消旧 TTS 队列。")

    def _commit_stable_asr_partial_after_delay(self, generation: int, text: str, delay: float) -> None:
        time.sleep(delay)
        if self.stop_event.is_set():
            return
        with self.asr_partial_lock:
            if generation != self._asr_partial_generation or text != self._asr_partial_text:
                return
        if not should_commit_stable_asr_partial(text):
            return
        self.logger.emit(
            "asr_partial_stable",
            callId=self.call_id,
            text=text,
            waitMs=int(delay * 1000),
            detail="ASR 最终文本尚未到达，但客户短句已稳定，先触发回复避免客户空等。",
        )
        self._commit_customer_text(text, source="asr_partial_stable", detail="客户语音已稳定，先接话并取消旧 TTS 队列。")

    def _commit_customer_text(self, text: str, *, source: str, detail: str) -> None:
        clean = " ".join(text.strip().split())
        if not clean or self.stop_event.is_set():
            return
        self._note_customer_activity(source, text=clean)
        if self._is_recent_committed_customer_text(clean):
            self.logger.emit(
                "customer_turn_duplicate_ignored",
                callId=self.call_id,
                text=clean,
                source=source,
                detail="ASR final 与前面的稳定 partial 内容重复，避免重复回复或打断刚开始的回复。",
            )
            return
        self.logger.emit(
            "turn_reply_preparing",
            callId=self.call_id,
            text=clean,
            source=source,
            detail="客户本轮已提交给销售脑，准备生成回复。",
        )
        generation = self.cancel_pending_speech(detail, source=source)
        self._remember_committed_customer_text(clean)
        self.customer_texts.put((generation, clean))

    def _note_customer_activity(self, source: str, *, text: str = "", now: float | None = None) -> None:
        self.customer_activity_event.set()
        self._last_remote_audio_at = now or time.monotonic()
        self._cancel_no_response_hangup(source, text=text)

    def _cancel_no_response_hangup(self, source: str, *, text: str = "") -> None:
        if not self._no_response_hangup_active:
            return
        self._no_response_hangup_active = False
        self._no_response_hangup_generation += 1
        self.logger.emit(
            "no_response_hangup_cancelled",
            callId=self.call_id,
            source=source,
            text=text[:100],
            detail="检测到客户新语音，取消 AI 回复后的无响应挂断计时。",
        )

    def _cancel_pending_asr_partial_turn(self, source: str) -> None:
        with self.asr_partial_lock:
            self._asr_partial_generation += 1
            self._asr_partial_text = ""
        self.logger.emit("asr_partial_turn_cancelled", callId=self.call_id, source=source)

    def _remember_committed_customer_text(self, text: str) -> None:
        with self.asr_partial_lock:
            self._last_committed_customer_text = text
            self._last_committed_customer_at = time.monotonic()
            self._recent_committed_customer_turns.append((text, self._last_committed_customer_at))
            self._recent_committed_customer_turns = self._recent_committed_customer_turns[-8:]

    def _is_recent_committed_customer_text(self, text: str) -> bool:
        compact = _compact_customer_text(text)
        if not compact:
            return False
        with self.asr_partial_lock:
            previous = self._last_committed_customer_text
            previous_at = self._last_committed_customer_at
            recent_turns = list(self._recent_committed_customer_turns)
        if not previous or time.monotonic() - previous_at > ASR_PARTIAL_DUPLICATE_SECONDS:
            recent_turns = [
                (previous_text, committed_at)
                for previous_text, committed_at in recent_turns
                if time.monotonic() - committed_at <= ASR_PARTIAL_DUPLICATE_SECONDS
            ]
        else:
            recent_turns.append((previous, previous_at))
        for previous_text, committed_at in reversed(recent_turns):
            if time.monotonic() - committed_at > ASR_PARTIAL_DUPLICATE_SECONDS:
                continue
            if self._is_duplicate_customer_turn(text, previous_text):
                return True
        return False

    def _is_duplicate_customer_turn(self, text: str, previous: str) -> bool:
        compact = _compact_customer_text(text)
        previous_compact = _compact_customer_text(previous)
        if not previous_compact:
            return False
        if _adds_significant_business_question(text, previous):
            return False
        if _adds_meaningful_question_detail(text, previous):
            return False
        if compact == previous_compact:
            return True
        shorter, longer = sorted((compact, previous_compact), key=len)
        if len(shorter) >= 3 and shorter in longer:
            return True
        similarity = SequenceMatcher(None, compact, previous_compact).ratio()
        if similarity >= 0.72:
            return True
        signal = classify_realtime_call_input(text)
        previous_signal = classify_realtime_call_input(previous)
        return (
            similarity >= 0.62
            and signal == previous_signal
            and signal in ASR_PARTIAL_FAST_SIGNALS
            and min(len(compact), len(previous_compact)) >= 2
        )

    def _handle_answer_classification(self, answer_type: CallAnswerType | None, *, text: str, source: str) -> None:
        if not answer_type or answer_type == CallAnswerType.UNKNOWN:
            return
        if self._answer_classification_reported == answer_type:
            return
        self._answer_classification_reported = answer_type
        state = self._answer_classifier.state
        self.logger.emit(
            "answer_classified",
            callId=self.call_id,
            answerType=answer_type.value,
            source=source,
            reason=state.reason,
            text=text,
            speechCount=state.speech_count,
            longestSpeechMs=int(state.longest_speech * 1000),
        )
        if answer_type == CallAnswerType.HUMAN:
            self._confirm_human_speech(text, detail="接听判定确认是真人，进入实时对话。")
            return
        if answer_type == CallAnswerType.PHONE_ASSISTANT:
            self._respond_to_call_screening(text or "电话助理提示", source=f"answer_classifier:{source}")
            return
        if answer_type == CallAnswerType.VOICEMAIL:
            self.logger.emit(
                "voicemail_detected",
                callId=self.call_id,
                text=text,
                detail="检测到语音信箱，直接挂断不留言。",
            )
            self.stop_event.set()
            return
        if answer_type == CallAnswerType.SYSTEM_PROMPT:
            self._system_prompt_seen = True
            self.logger.emit(
                "system_prompt_detected",
                callId=self.call_id,
                text=text,
                detail="检测到运营商或手机系统提示，暂不触发销售话术。",
            )

    def _respond_to_call_screening(self, text: str, *, source: str) -> None:
        self._call_screening_seen = True
        if self._call_screening_answered or self.stop_event.is_set():
            return
        self._call_screening_answered = True
        reply = self._screening_handoff_reply()
        self.logger.emit(
            "call_screening_detected",
            callId=self.call_id,
            text=text,
            source=source,
            detail="识别到电话助理/秘书提示，只说明身份和来电原因，等待真人转接。",
        )
        self.logger.emit(
            "llm_reply",
            callId=self.call_id,
            reply=reply,
            strategy="phone_assistant_handoff",
            latencyMs=0,
            fallbackUsed=True,
            historyTurns=len(self._conversation_history),
            error=None,
        )
        with self.generation_lock:
            generation = self.speech_generation
        threading.Thread(target=self._speak, args=(reply, "call_screening", generation), daemon=True).start()
        self._schedule_call_screening_hangup(source)

    def _confirm_human_speech(self, text: str, *, detail: str) -> None:
        if self._human_speech_confirmed:
            return
        self._human_speech_confirmed = True
        self.logger.emit(
            "human_speech_confirmed",
            callId=self.call_id,
            text=text,
            detail=detail,
        )

    def _schedule_call_screening_hangup(self, source: str) -> None:
        wait_seconds = max(0.0, self.config.call_screening_hangup_seconds)
        if wait_seconds <= 0:
            return
        self._call_screening_hangup_generation += 1
        generation = self._call_screening_hangup_generation
        self.logger.emit(
            "call_screening_hangup_scheduled",
            callId=self.call_id,
            waitMs=int(wait_seconds * 1000),
            source=source,
            detail="电话助理说明来意后进入短等待；若无人转接真人，将主动挂断避免空等计费。",
        )
        threading.Thread(
            target=self._close_if_no_human_after_call_screening,
            args=(generation, wait_seconds),
            daemon=True,
        ).start()

    def _close_if_no_human_after_call_screening(self, generation: int, wait_seconds: float) -> None:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline and not self.stop_event.is_set():
            if self._human_speech_confirmed:
                return
            time.sleep(0.1)
        if (
            self.stop_event.is_set()
            or self._human_speech_confirmed
            or generation != self._call_screening_hangup_generation
        ):
            return
        self.logger.emit(
            "call_screening_hangup_timeout",
            callId=self.call_id,
            waitMs=int(wait_seconds * 1000),
            detail="电话助理后未等到真人转接，主动结束本次通话。",
        )
        self._close_after_terminal_reply("call_screening_no_human")

    def _schedule_no_response_hangup(self, reason: str) -> None:
        if reason == "call_screening":
            return
        wait_seconds = max(0.0, self.config.no_response_hangup_seconds)
        if wait_seconds <= 0:
            return
        self._no_response_hangup_generation += 1
        generation = self._no_response_hangup_generation
        self._no_response_hangup_active = True
        baseline_remote_audio_at = self._last_remote_audio_at
        self.logger.emit(
            "no_response_hangup_scheduled",
            callId=self.call_id,
            waitMs=int(wait_seconds * 1000),
            reason=reason,
            detail="AI 说完后进入短等待；若客户没有新语音，将主动结束通话，避免长时间空等计费。",
        )
        threading.Thread(
            target=self._close_if_no_response_after_speech,
            args=(generation, wait_seconds, baseline_remote_audio_at, reason),
            daemon=True,
        ).start()

    def _close_if_no_response_after_speech(
        self,
        generation: int,
        wait_seconds: float,
        baseline_remote_audio_at: float,
        reason: str,
    ) -> None:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline and not self.stop_event.is_set():
            if self._last_remote_audio_at > baseline_remote_audio_at:
                if generation == self._no_response_hangup_generation:
                    self._no_response_hangup_active = False
                return
            time.sleep(0.2)
        if (
            self.stop_event.is_set()
            or self.speaking_event.is_set()
            or self._last_remote_audio_at > baseline_remote_audio_at
            or generation != self._no_response_hangup_generation
        ):
            if generation == self._no_response_hangup_generation:
                self._no_response_hangup_active = False
            return
        self._no_response_hangup_active = False
        self.logger.emit(
            "no_response_hangup_timeout",
            callId=self.call_id,
            waitMs=int(wait_seconds * 1000),
            reason=reason,
            detail="AI 说完后没有检测到客户新语音，主动结束本次通话。",
        )
        self._close_after_terminal_reply("no_customer_response")

    def _speak_opening_after_grace(self) -> None:
        grace = max(0.0, self.config.opening_grace_seconds)
        if grace and self.customer_activity_event.wait(grace):
            self.logger.emit("opening_deferred", callId=self.call_id, reason="remote_audio_detected")
            if not self._wait_for_remote_classification_before_opening("pipeline"):
                return
        if self._mark_opening_started():
            with self.generation_lock:
                generation = self.speech_generation
            cached_voice_match = get_cached_opening_voice_match()
            opening_text = cached_voice_match.reply_text if cached_voice_match else self._opening_text_for_call()
            self.logger.emit(
                "opening_start",
                callId=self.call_id,
                mode="pipeline",
                text=opening_text,
                merchantName=self._merchant_name(),
                source="voice_cache" if cached_voice_match else "local_tts",
            )
            threading.Thread(
                target=self._speak,
                args=(opening_text, "opening", generation, False, cached_voice_match),
                daemon=True,
            ).start()

    def _wait_for_remote_classification_before_opening(self, mode: str) -> bool:
        wait_seconds = max(0.2, self.config.answer_classification_seconds)
        deadline = time.monotonic() + wait_seconds
        saw_remote_audio = bool(self._last_remote_audio_at)
        while time.monotonic() < deadline and not self.stop_event.is_set():
            if self._opening_blocked():
                return False
            if self._answer_classifier.state.done:
                break
            if self._last_remote_audio_at:
                saw_remote_audio = True
            if self._last_remote_audio_at and time.monotonic() - self._last_remote_audio_at < REMOTE_AUDIO_SILENCE_SECONDS:
                time.sleep(0.08)
                continue
            time.sleep(0.08)
        if self._opening_blocked():
            return False
        answer_type = self._answer_classifier.state.detected_type
        if not self._answer_classifier.state.done:
            answer_type = self._answer_classifier.classify_after_wait()
            self._handle_answer_classification(answer_type, text="", source="opening_wait_timeout")
        if answer_type in {CallAnswerType.PHONE_ASSISTANT, CallAnswerType.VOICEMAIL, CallAnswerType.SYSTEM_PROMPT}:
            return False
        if answer_type == CallAnswerType.HUMAN:
            self.logger.emit(
                "opening_after_human_audio",
                callId=self.call_id,
                mode=mode,
                waitMs=int(wait_seconds * 1000),
                detail="已确认对端是真人但还没有最终转写，先播短开场避免电话里长时间沉默。",
            )
            return True
        if saw_remote_audio:
            self.logger.emit(
                "opening_after_unknown_remote",
                callId=self.call_id,
                mode=mode,
                waitMs=int(wait_seconds * 1000),
                answerType=answer_type.value,
                detail="对端已有声音但未能明确分类，避免长时间沉默，使用短开场接话。",
            )
            return True
        self.logger.emit(
            "opening_after_remote_silence",
            callId=self.call_id,
            mode=mode,
            waitMs=int(wait_seconds * 1000),
        )
        return True

    def _opening_blocked(self) -> bool:
        return (
            self.stop_event.is_set()
            or self.speaking_event.is_set()
            or self._opening_started
            or self._call_screening_seen
            or self._system_prompt_seen
        )

    def _mark_opening_started(self) -> bool:
        if self._opening_blocked():
            return False
        self._opening_started = True
        self._opening_started_at = time.monotonic()
        self._opening_raw_barge_protect_until = self._opening_started_at + OPENING_RAW_BARGE_PROTECT_SECONDS
        self._opening_raw_barge_protected_logged = False
        return True

    def _turn_worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                generation, text = self.customer_texts.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.stop_event.is_set():
                break
            generation, text = self._drain_latest_customer_text(generation, text)
            if self.stop_event.is_set() or not text.strip():
                continue
            signal = classify_realtime_call_input(text)
            if signal == "system_prompt":
                human_tail = extract_human_text_after_system_prompt(text)
                if human_tail:
                    self.logger.emit(
                        "system_prompt_stripped",
                        callId=self.call_id,
                        text=text,
                        strippedText=human_tail,
                        detail="ASR 同一句里包含系统提示和真人客户语音，已只剥离系统提示并继续回复真人内容。",
                    )
                    text = human_tail
                    signal = classify_realtime_call_input(text)
                    if signal == "system_prompt":
                        signal = "human_speech"
                else:
                    if classify_answer_text(text) == CallAnswerType.VOICEMAIL:
                        self.logger.emit(
                            "voicemail_detected",
                            callId=self.call_id,
                            text=text,
                            detail="识别到语音信箱/留言提示，直接挂断不留言。",
                        )
                        self.stop_event.set()
                        continue
                    self._system_prompt_seen = True
                    self.logger.emit(
                        "system_prompt_ignored",
                        callId=self.call_id,
                        text=text,
                        detail="识别到运营商、手机系统或语音留言提示，已忽略，不触发销售回复。",
                    )
                    continue
            if signal == "call_screening":
                if self._call_screening_answered:
                    self.logger.emit(
                        "call_screening_followup_ignored",
                        callId=self.call_id,
                        text=text,
                        detail="电话助理后续等待提示已忽略，避免重复说明身份和来电原因。",
                    )
                    continue
                self._respond_to_call_screening(text, source="pipeline_turn")
                continue
            if not self._human_speech_confirmed:
                self._confirm_human_speech(text, detail="已识别到真人客户语音，可以进入实时对话。")
            normalization = normalize_realtime_sales_text(text)
            routed_text = normalization.normalized_text
            if normalization.changed:
                self.logger.emit(
                    "asr_sales_text_normalized",
                    callId=self.call_id,
                    text=text,
                    normalizedText=routed_text,
                    fixes=list(normalization.fixes),
                    detail="ASR 文本进入销售脑前已做高置信语境纠错，原始转写仍保留在 ASR 事件中。",
                )
            intent, node = _classify_intent(routed_text)
            stage = self._sales_fsm.update(routed_text, intent, signal)
            stage_instruction = self._sales_fsm.get_stage_instruction()
            if intent == "系统提示":
                self.logger.emit("intent", callId=self.call_id, text=text, intent=intent, node=node)
                continue
            self._record_realtime_intent_signal(routed_text, intent, signal, "pipeline_turn")
            if _is_business_category_signal(routed_text):
                self._record_realtime_intent_signal(
                    routed_text,
                    "品类确认",
                    signal,
                    "pipeline_business_category",
                    force=True,
                    evidence="客户主动说明门店品类，已进入可跟进意向。",
                    latest_signal=f"客户主动说明门店品类：{routed_text}",
                    intent_level="B",
                    intent_score=78,
                    need_handoff=True,
                )
            turn_count, fallback_reply = self._reply_for_turn(routed_text, intent)
            history_snapshot = list(self._conversation_history)
            wechat_result = self._sales_fsm.handle_wechat_closing_turn(routed_text, intent, phone=self._call_phone())
            if wechat_result:
                if wechat_result.record:
                    self._record_realtime_wechat_signal(
                        routed_text,
                        signal,
                        "pipeline_wechat_closing",
                        wechat_id=wechat_result.wechat_id,
                        wechat_is_phone=wechat_result.wechat_is_phone,
                        summary=wechat_result.summary,
                    )
                if not wechat_result.reply:
                    self.logger.emit(
                        "wechat_closing_waiting_more_text",
                        callId=self.call_id,
                        text=routed_text,
                        action=wechat_result.action,
                        detail="客户的手机号微信确认还没说完整，先不回复也不记入去重，继续听下一段。",
                    )
                    continue
                reply = wechat_result.reply
                self._append_conversation_turn(text, reply)
                self._sales_fsm.record_assistant_reply(reply)
                self.logger.emit(
                    "intent",
                    callId=self.call_id,
                    text=text,
                    intent=intent,
                    node=node,
                    turnCount=turn_count,
                    salesStage=stage.value,
                )
                self.logger.emit(
                    "llm_reply",
                    callId=self.call_id,
                    reply=reply,
                    strategy=f"wechat_closing_{wechat_result.action}",
                    latencyMs=0,
                    fallbackUsed=True,
                    historyTurns=len(history_snapshot),
                    error=None,
                )
                threading.Thread(target=self._speak, args=(reply, "wechat_closing", generation, False), daemon=True).start()
                continue
            cached_voice_match = match_cached_voice_reply(routed_text)
            if cached_voice_match:
                reply = cached_voice_match.reply_text
                self._append_conversation_turn(text, reply)
                self._sales_fsm.record_assistant_reply(reply)
                self.logger.emit(
                    "voice_cache_match",
                    callId=self.call_id,
                    text=routed_text,
                    intent=intent,
                    intentId=cached_voice_match.intent_id,
                    sceneTitle=cached_voice_match.scene_title,
                    seqs=list(cached_voice_match.seqs),
                    confidence=cached_voice_match.confidence,
                    matchedTrigger=cached_voice_match.matched_trigger,
                    recommendedAction=cached_voice_match.recommended_action,
                    voiceProfile=cached_voice_match.voice_profile,
                )
                self.logger.emit(
                    "intent",
                    callId=self.call_id,
                    text=text,
                    intent=intent,
                    node=node,
                    turnCount=turn_count,
                    salesStage=stage.value,
                )
                self.logger.emit(
                    "llm_reply",
                    callId=self.call_id,
                    reply=reply,
                    strategy="cached_voice",
                    latencyMs=0,
                    fallbackUsed=False,
                    historyTurns=len(history_snapshot),
                    error=None,
                )
                threading.Thread(
                    target=self._speak,
                    args=(reply, "voice_cache", generation, False, cached_voice_match),
                    daemon=True,
                ).start()
                continue
            self.logger.emit(
                "turn_llm_start",
                callId=self.call_id,
                text=routed_text,
                intent=intent,
                signal=signal,
                salesStage=stage.value,
                historyTurns=len(history_snapshot),
                detail="客户本轮已进入回复生成，等待 LLM/本地话术返回。",
            )
            reply_result = generate_realtime_reply(
                text,
                intent,
                self._merchant_name(),
                fallback_reply,
                history_snapshot,
                stage_instruction=stage_instruction,
            )
            if self.stop_event.is_set():
                continue
            reply = self._sales_fsm.constrain_reply(reply_result.reply)
            self._append_conversation_turn(text, reply)
            self._sales_fsm.record_assistant_reply(reply)
            self.logger.emit(
                "intent",
                callId=self.call_id,
                text=text,
                intent=intent,
                node=node,
                turnCount=turn_count,
                salesStage=stage.value,
            )
            self.logger.emit(
                "llm_reply",
                callId=self.call_id,
                reply=reply,
                strategy=reply_result.strategy,
                latencyMs=reply_result.latency_ms,
                fallbackUsed=reply_result.fallback_used,
                historyTurns=len(history_snapshot),
                error=reply_result.error,
            )
            terminal_intent = intent in {"明确拒绝", "礼貌结束"} or self._sales_fsm.should_end_call()
            close_after = terminal_intent and _is_strong_terminal_close_text(routed_text)
            if terminal_intent and not close_after:
                self.logger.emit(
                    "terminal_close_guarded",
                    callId=self.call_id,
                    text=routed_text,
                    intent=intent,
                    signal=signal,
                    detail="客户文本不是明确挂断语，已拦截自动挂断，继续保持通话。",
                )
            reason = "closing_reply" if close_after else "reply"
            threading.Thread(target=self._speak, args=(reply, reason, generation, close_after), daemon=True).start()

    def _reply_for_turn(self, text: str, intent: str) -> tuple[int, str]:
        turn_count = self._intent_counts.get(intent, 0)
        self._intent_counts[intent] = turn_count + 1
        clean = text.strip()
        compact = "".join(char for char in clean.lower() if char not in " \t\r\n。！？?!，,、.")
        if intent == "身份确认":
            if compact in {"喂", "喂喂", "你好"}:
                if turn_count == 0:
                    return turn_count, self._identity_opening_reply()
                return turn_count, "我在。刚才说的是视频号团购到店获客，不方便我就不打扰。"
            if turn_count == 0:
                return turn_count, f"我是做视频号团购到店获客的，给您来电是确认{self._merchant_subject()}是否需要微信同城曝光。"
            return turn_count, "我直接说身份：做视频号团购到店获客，不是平台官方，也不是催您马上办理。"
        if intent == "加微信/发资料":
            if "怎么" in clean or "哪里" in clean:
                return turn_count, "短信或微信都可以，您看哪种方便？我只发一份案例资料。"
            if turn_count > 0:
                return turn_count, "可以，我加您微信，把案例、流程和费用区间发您。这个手机号就是您的微信吗？"
        if intent == "听不清/澄清" and turn_count > 0:
            return turn_count, "我再说短一点：做视频号团购，帮门店多拿到店客户。"
        if intent == "合作咨询" and turn_count > 0:
            return turn_count, SOFT_WECHAT_OFFER_REPLY
        if intent == "低信息确认" and turn_count > 0:
            return turn_count, "可以的话我就说重点，不方便我就不打扰。"
        if _is_business_category_signal(clean):
            return turn_count, BUSINESS_CATEGORY_REPLY
        if intent == "需求探索" and turn_count > 0:
            return turn_count, SOFT_WECHAT_OFFER_REPLY
        return turn_count, _build_reply(text, intent, self._merchant_name())

    def _append_conversation_turn(self, customer_text: str, assistant_reply: str) -> None:
        self._call_history.append({"role": "user", "content": customer_text.strip()})
        self._call_history.append({"role": "assistant", "content": assistant_reply.strip()})
        self._conversation_history.append({"role": "user", "content": customer_text.strip()})
        self._conversation_history.append({"role": "assistant", "content": assistant_reply.strip()})
        if len(self._conversation_history) > 12:
            del self._conversation_history[: len(self._conversation_history) - 12]

    def _drain_latest_customer_text(self, generation: int, text: str) -> tuple[int, str]:
        latest_generation = generation
        latest_text = text
        while True:
            try:
                latest_generation, latest_text = self.customer_texts.get_nowait()
            except queue.Empty:
                return latest_generation, latest_text

    def cancel_pending_speech(self, detail: str, source: str, rms: int | None = None) -> int:
        now = time.monotonic()
        with self.speech_state_lock:
            active_jobs_at_start = self.speech_jobs
            was_speaking = self.speaking_event.is_set() or active_jobs_at_start > 0
        with self.generation_lock:
            self.speech_generation += 1
            generation = self.speech_generation
        self.interrupt_event.set()
        drained = False
        deadline = now + 0.2
        while time.monotonic() < deadline:
            with self.speech_state_lock:
                active_jobs = self.speech_jobs
            if active_jobs <= 0:
                drained = True
                break
            time.sleep(0.01)
        with self.speech_state_lock:
            remaining_jobs = self.speech_jobs
            if remaining_jobs > 0:
                self.speech_jobs = 0
            self.speaking_event.clear()
        if was_speaking and (remaining_jobs > 0 or drained):
            self.logger.emit(
                "barge_playback_drained",
                callId=self.call_id,
                source=source,
                generation=generation,
                drained=drained,
                remainingJobs=remaining_jobs,
                waitMs=int((time.monotonic() - now) * 1000),
            )
        if was_speaking and now - self._last_barge_at > 0.8:
            self._last_barge_at = now
            fields: dict[str, Any] = {
                "callId": self.call_id,
                "detail": detail,
                "source": source,
                "generation": generation,
            }
            if rms is not None:
                fields["rms"] = rms
            self.logger.emit("barge_in", **fields)
            self.logger.emit(
                "barge_recovery_ready",
                callId=self.call_id,
                source=source,
                generation=generation,
                waitMs=int((time.monotonic() - now) * 1000),
                detail="已停止当前 AI 语音，恢复监听客户本轮问题。",
            )
        elif not was_speaking:
            self.logger.emit(
                "turn_generation_advanced",
                callId=self.call_id,
                source=source,
                generation=generation,
                detail="客户新一轮输入到达，更新回复代次；当前没有正在播放的 AI 语音。",
            )
        return generation

    def _speak(
        self,
        text: str,
        reason: str,
        generation: int,
        close_after: bool = False,
        cached_voice_match: CachedVoiceMatch | None = None,
    ) -> None:
        if self.stop_event.is_set():
            return
        opening_playback = reason in {"opening", "omni_opening_local"}
        if opening_playback:
            self._opening_playback_active = True
        self._mark_speech_job_started()
        with self.generation_lock:
            if self.speech_generation == generation:
                self.interrupt_event.clear()
        if self._speech_is_obsolete(generation):
            self.logger.emit(
                "tts_interrupted",
                callId=self.call_id,
                reason=reason,
                phase="queued",
                sentBytes=0,
                totalBytes=0,
                generation=generation,
            )
            self._mark_speech_job_finished()
            if opening_playback:
                self._opening_playback_active = False
            return
        start = time.perf_counter()
        playback_started = False
        first_audio_ms = 0
        total_bytes = 0
        sent = 0
        pending = b""
        next_frame_at: float | None = None
        playback_lag_events = 0
        audio_mode = "cached" if cached_voice_match else "dynamic_tts"
        streaming_tts = not cached_voice_match and _is_qwen_realtime_model(self.config.tts_model)
        if cached_voice_match:
            self.logger.emit(
                "voice_cache_playback_start",
                callId=self.call_id,
                reason=reason,
                intentId=cached_voice_match.intent_id,
                sceneTitle=cached_voice_match.scene_title,
                seqs=list(cached_voice_match.seqs),
                confidence=cached_voice_match.confidence,
                matchedTrigger=cached_voice_match.matched_trigger,
                voiceProfile=cached_voice_match.voice_profile,
                assetVersion=cached_voice_match.asset_version,
            )
        try:
            with self.playback_lock:
                for audio_chunk in iter_tts_pcm_chunks(text, self.config, cached_voice_match):
                    if not audio_chunk:
                        continue
                    total_bytes += len(audio_chunk)
                    if self._speech_is_obsolete(generation):
                        break
                    if not playback_started:
                        first_audio_ms = int((time.perf_counter() - start) * 1000)
                        playback_started = True
                        self.logger.emit(
                            "tts_start",
                            callId=self.call_id,
                            reason=reason,
                            text=text,
                            bytes=total_bytes,
                            synthMs=first_audio_ms,
                            firstAudioMs=first_audio_ms,
                            voice=self.config.tts_voice_name,
                            voiceType=self.config.tts_voice_type,
                            model=self.config.tts_model,
                            streaming=_is_qwen_realtime_model(self.config.tts_model),
                            audioMode=audio_mode,
                            voiceCacheIntentId=cached_voice_match.intent_id if cached_voice_match else "",
                            voiceCacheSeqs=list(cached_voice_match.seqs) if cached_voice_match else [],
                            voiceCacheProfile=cached_voice_match.voice_profile if cached_voice_match else "",
                            generation=generation,
                        )
                    pending += audio_chunk
                    if streaming_tts and sent == 0 and len(pending) < TTS_STREAM_START_BUFFER_BYTES:
                        continue
                    while len(pending) >= PCM_FRAME_BYTES:
                        if self.stop_event.is_set() or self._speech_is_obsolete(generation):
                            break
                        frame = pending[:PCM_FRAME_BYTES]
                        pending = pending[PCM_FRAME_BYTES:]
                        next_frame_at, playback_lag_events = self._send_audio_frame_at_cadence(
                            frame,
                            next_frame_at,
                            playback_lag_events,
                            reason,
                            generation,
                        )
                        sent += len(frame)
                    if self.stop_event.is_set() or self._speech_is_obsolete(generation):
                        break
                if pending and not self.stop_event.is_set() and not self._speech_is_obsolete(generation):
                    padded_pending = pending.ljust(PCM_FRAME_BYTES, b"\x00")
                    next_frame_at, playback_lag_events = self._send_audio_frame_at_cadence(
                        padded_pending,
                        next_frame_at,
                        playback_lag_events,
                        reason,
                        generation,
                    )
                    sent += len(pending)
        except Exception as exc:  # noqa: BLE001
            if _is_socket_closed_error(exc):
                self.logger.emit(
                    "tts_stopped_after_socket_close",
                    callId=self.call_id,
                    text=text,
                    reason=reason,
                    audioMode=audio_mode,
                    detail="播放时远端已挂断，停止本轮音频，不按 TTS 异常处理。",
                )
            else:
                self.logger.emit("tts_error", callId=self.call_id, text=text, error=str(exc), audioMode=audio_mode)
            self._mark_speech_job_finished()
            if opening_playback:
                self._opening_playback_active = False
            return
        if not playback_started or self._speech_is_obsolete(generation):
            self.logger.emit(
                "tts_interrupted",
                callId=self.call_id,
                reason=reason,
                phase="playback" if playback_started else "synthesis",
                sentBytes=sent,
                totalBytes=total_bytes,
                synthMs=first_audio_ms or int((time.perf_counter() - start) * 1000),
                audioMode=audio_mode,
                voiceCacheIntentId=cached_voice_match.intent_id if cached_voice_match else "",
                voiceCacheSeqs=list(cached_voice_match.seqs) if cached_voice_match else [],
                generation=generation,
            )
            self._mark_speech_job_finished()
            if opening_playback:
                self._opening_playback_active = False
            if close_after:
                self.logger.emit(
                    "terminal_close_interrupted_suppressed",
                    callId=self.call_id,
                    reason=reason,
                    sentBytes=sent,
                    generation=generation,
                    detail="结束收口语音已被新的客户话轮打断，不再执行主动挂断。",
                )
            return
        interrupted = self._speech_is_obsolete(generation)
        self._mark_speech_job_finished()
        if opening_playback:
            self._opening_playback_active = False
        with self.generation_lock:
            if self.speech_generation == generation:
                self.interrupt_event.clear()
        self.logger.emit(
            "tts_interrupted" if interrupted else "tts_done",
            callId=self.call_id,
            reason=reason,
            phase="playback" if playback_started else "queued",
            sentBytes=sent,
            totalBytes=total_bytes,
            firstAudioMs=first_audio_ms,
            audioMode=audio_mode,
            voiceCacheIntentId=cached_voice_match.intent_id if cached_voice_match else "",
            voiceCacheSeqs=list(cached_voice_match.seqs) if cached_voice_match else [],
            generation=generation,
        )
        if close_after and not interrupted:
            self._close_after_terminal_reply(self._close_reason_for_spoken_reply(text, reason))
        elif not close_after and not interrupted:
            self._schedule_no_response_hangup(reason)

    def _close_reason_for_spoken_reply(self, text: str, reason: str) -> str:
        compact = _compact_customer_text(text)
        if "稍后按这个手机号添加" in text or ("添加您" in text and "感谢您接听" in text) or "资料发过去" in text:
            return "wechat_confirmed"
        if "不打扰" in text or reason in {"terminal_close", "closing_reply"}:
            return "customer_rejected"
        if reason == "omni_unavailable":
            return "omni_unavailable"
        return reason or "spoken_reply_close"

    def _send_audio_frame_at_cadence(
        self,
        frame: bytes,
        next_frame_at: float | None,
        lag_events: int,
        reason: str,
        generation: int,
    ) -> tuple[float, int]:
        now = time.perf_counter()
        if next_frame_at is None or next_frame_at < now - PCM_FRAME_SECONDS * 2:
            if next_frame_at is not None and lag_events < 5:
                lag_ms = int((now - next_frame_at) * 1000)
                self.logger.emit(
                    "tts_playback_lag",
                    callId=self.call_id,
                    reason=reason,
                    lagMs=lag_ms,
                    generation=generation,
                )
                lag_events += 1
            next_frame_at = now
        wait_seconds = next_frame_at - now
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        scaled_frame = _scale_pcm16(frame, self.config.tts_gain)
        if self._audio_capture:
            self._audio_capture.write_outbound_raw(scaled_frame)
        processed_frame = self._audio_quality.process(scaled_frame)
        self._audio_quality_frame_count += 1
        if self.config.audio_quality_enabled and self._audio_quality_frame_count % 250 == 0:
            raw_stats = analyze_pcm16(scaled_frame)
            processed_stats = analyze_pcm16(processed_frame)
            self.logger.emit(
                "audio_quality_sample",
                callId=self.call_id,
                generation=generation,
                rawRms=raw_stats.rms,
                rawPeak=raw_stats.peak,
                rawClipped=raw_stats.clipped,
                processedRms=processed_stats.rms,
                processedPeak=processed_stats.peak,
                processedClipped=processed_stats.clipped,
            )
        if self._audio_capture:
            self._audio_capture.write_outbound(processed_frame)
        try:
            self._send_frame(AUDIO_SOCKET_KIND_AUDIO, processed_frame)
        except Exception as exc:  # noqa: BLE001
            self._close_after_socket_write_error("tts_playback", exc)
            raise
        self._last_outbound_audio_at = time.monotonic()
        return next_frame_at + PCM_FRAME_SECONDS, lag_events

    def _read_frame(self) -> tuple[int, bytes]:
        header = _read_exact(self.conn, 3)
        frame_type, payload_length = struct.unpack("!BH", header)
        payload = _read_exact(self.conn, payload_length) if payload_length else b""
        return frame_type, payload

    def _send_frame(self, frame_type: int, payload: bytes = b"") -> None:
        if len(payload) > 65535:
            raise AudioSocketProtocolError("AudioSocket payload too large.")
        packet = struct.pack("!BH", frame_type, len(payload)) + payload
        with self.send_lock:
            self.conn.sendall(packet)

    def _speech_is_obsolete(self, generation: int) -> bool:
        with self.generation_lock:
            return self.stop_event.is_set() or self.interrupt_event.is_set() or self.speech_generation != generation

    def _mark_speech_job_started(self) -> None:
        with self.speech_state_lock:
            self.speech_jobs += 1
            self.speaking_event.set()

    def _mark_speech_job_finished(self) -> None:
        with self.speech_state_lock:
            self.speech_jobs = max(0, self.speech_jobs - 1)
            if self.speech_jobs == 0:
                self.speaking_event.clear()

    def _close_after_terminal_reply(self, reason: str) -> None:
        self._intentional_close_reason = reason
        self.logger.emit("call_closing", callId=self.call_id, reason=reason)
        self.stop_event.set()
        try:
            self._send_frame(AUDIO_SOCKET_KIND_HANGUP)
        except OSError:
            pass
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("call_close_frame_error", callId=self.call_id, reason=reason, error=str(exc))
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _start_audio_capture(self) -> None:
        if not self.config.debug_audio_capture_enabled or not self.call_id or self._audio_capture:
            return
        try:
            self._audio_capture = CallAudioCapture(self.call_id, self.config.debug_audio_capture_dir)
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("audio_capture_error", callId=self.call_id, error=str(exc))
            return
        self.logger.emit(
            "audio_capture_started",
            callId=self.call_id,
            inboundPath=str(self._audio_capture.inbound_path),
            outboundPath=str(self._audio_capture.outbound_path),
        )

    def _stop_audio_capture(self) -> None:
        if not self._audio_capture:
            return
        try:
            paths = self._audio_capture.close()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("audio_capture_error", callId=self.call_id, error=str(exc))
            self._audio_capture = None
            return
        self.logger.emit("audio_capture_saved", callId=self.call_id, **paths)
        self._audio_capture = None


class OmniAudioSocketCallSession(AudioSocketCallSession):
    def __init__(self, conn: socket.socket, peer: tuple[str, int], config: BridgeConfig, logger: JsonlEventLogger) -> None:
        super().__init__(conn, peer, config, logger)
        self._omni: OmniRealtimeConversation | None = None
        self._omni_downsample_state = _PcmDownsampleState()
        self._omni_lock = threading.Lock()
        self._omni_generation = 0
        self._omni_response_id = ""
        self._omni_cancelled_response_ids: set[str] = set()
        self._omni_reply_parts: list[str] = []
        self._omni_pending_audio = b""
        self._omni_next_frame_at: float | None = None
        self._omni_playback_lag_events = 0
        self._omni_first_audio_ms = 0
        self._omni_audio_sent = 0
        self._omni_audio_total = 0
        self._omni_response_started_at = 0.0
        self._omni_response_request_active = False
        self._omni_response_request_started_at = 0.0
        self._omni_tts_started = False
        self._omni_session_ready = False
        self._omni_closed = False
        self._omni_pipeline_fallback = False
        self._omni_unavailable_closing = False
        self._omni_barge_collecting = False
        self._omni_barge_started_at = 0.0
        self._omni_barge_last_voice_at = 0.0
        self._omni_barge_forced_response_until = 0.0
        self._omni_barge_forced_audio_started = False
        self._omni_barge_forced_requested = False
        self._omni_barge_server_stopped = False
        self._omni_barge_server_committed = False
        self._omni_barge_recovery_generation = 0
        self._omni_barge_last_text = ""
        self._human_speech_confirmed = False
        self._last_remote_speech_started_at = 0.0
        self._call_screening_seen = False
        self._call_screening_answered = False
        self._call_screening_hangup_generation = 0
        self._no_response_hangup_generation = 0
        self._no_response_hangup_active = False
        self._system_prompt_seen = False
        self._opening_started = False
        self._opening_playback_active = False
        self._last_remote_audio_at = 0.0
        self._omni_pending_customer_text = ""
        self._omni_pending_signal = ""
        self._omni_pending_forced_reply = ""
        self._last_omni_reply = ""
        self._last_omni_reply_at = 0.0
        self._omni_last_requested_text = ""
        self._omni_last_requested_at = 0.0
        self._omni_sidecar_asr_active = False
        self._omni_transcription_defer_generation = 0
        self._omni_transcription_defer_pending = False
        self._human_greeting_fallback_generation = 0

    def run(self) -> None:
        self.conn.settimeout(1.0)
        self.logger.emit(
            "socket_connected",
            peer=f"{self.peer[0]}:{self.peer[1]}",
            voice=self.config.omni_voice,
            mode="omni",
        )
        try:
            if not self._await_call_uuid():
                return
            self.logger.emit(
                "call_connected",
                callId=self.call_id,
                peer=f"{self.peer[0]}:{self.peer[1]}",
                voice=self.config.omni_voice,
                mode="omni",
            )
            self._start_startup_keepalive()
            requested_route = self._context_conversation_route()
            if requested_route == "pipeline":
                self._enable_omni_pipeline_fallback(
                    "requested_pipeline_route",
                    RuntimeError("本通电话在前端选择稳定分段语音 Pipeline。"),
                )
            else:
                circuit_reason = omni_route_unavailable_reason()
                if circuit_reason:
                    self._enable_omni_pipeline_fallback("omni_circuit_open", RuntimeError(circuit_reason))
                else:
                    try:
                        self._start_omni()
                    except Exception as exc:  # noqa: BLE001
                        mark_omni_route_unavailable(str(exc))
                        self._enable_omni_pipeline_fallback("omni_start", exc)
            self._start_omni_sidecar_asr()
            threading.Thread(target=self._speak_opening_after_grace, daemon=True).start()
            self._read_loop()
        except Exception as exc:  # noqa: BLE001
            if self._is_intentional_socket_close(exc):
                self._emit_call_closed_once(
                    self._intentional_close_reason,
                    detail="客户明确结束后系统主动关闭 AudioSocket。",
                    source="intentional_close",
                )
            elif _is_socket_closed_error(exc):
                self._emit_call_closed_once(
                    "remote_hangup",
                    detail="远端关闭 AudioSocket，按正常挂断收口。",
                    source="audiosocket_closed",
                )
            else:
                self.logger.emit("call_error", callId=self.call_id, error=str(exc), mode="omni")
        finally:
            self.stop_event.set()
            self.interrupt_event.set()
            self._record_learning_summary()
            self._stop_startup_keepalive()
            self._stop_asr()
            self._stop_omni()
            self._stop_audio_capture()
            try:
                self.conn.close()
            except OSError:
                pass
            self.logger.emit("call_disconnected", callId=self.call_id, mode="omni")

    def _start_omni(self) -> None:
        runtime_config = get_runtime_ai_config()
        if not runtime_config.dashscope_api_key:
            raise AudioSocketProtocolError("缺少 DASHSCOPE_API_KEY，不能启动 Qwen Omni Realtime。")
        dashscope.api_key = runtime_config.dashscope_api_key
        callback = CallOmniCallback(self)
        self._omni = OmniRealtimeConversation(
            model=self.config.omni_model,
            callback=callback,
            url=self.config.omni_url,
            workspace=self.config.workspace,
        )
        self._omni.connect()
        self._omni_closed = False
        self._omni.update_session(
            output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],
            voice=self.config.omni_voice,
            enable_input_audio_transcription=True,
            input_audio_transcription_model=self.config.omni_input_transcription_model,
            enable_turn_detection=True,
            turn_detection_type="semantic_vad",
            turn_detection_threshold=0.5,
            turn_detection_silence_duration_ms=650,
            turn_detection_param={"interrupt_response": True, "create_response": False},
            instructions=build_video_group_buying_sales_instructions(self._merchant_name()),
        )

    def _enable_omni_pipeline_fallback(self, source: str, exc: Exception) -> None:
        with self._omni_lock:
            if self._omni_pipeline_fallback:
                return
            self._omni_pipeline_fallback = True
            self._omni = None
            self._omni_closed = True
        self.logger.emit(
            "omni_start_failed_fallback",
            callId=self.call_id,
            source=source,
            error=str(exc),
            mode="omni",
            fallbackMode="pipeline",
            detail=(
                "本通电话前端选择稳定分段语音 Pipeline，当前 Omni bridge 已按单通话切到本地 ASR+LLM+TTS pipeline。"
                if source == "requested_pipeline_route"
                else "Omni 实时连接运行中关闭，本通电话已自动降级到本地 ASR+LLM+TTS pipeline，保持通话继续。"
                if source == "omni_runtime_closed"
                else "Omni 实时连接启动失败，本通电话自动降级到本地 ASR+LLM+TTS pipeline，避免接通后直接挂断。"
            ),
        )
        try:
            if not self._turn_thread.is_alive():
                self._turn_thread.start()
        except RuntimeError:
            pass

    def _context_conversation_route(self) -> str:
        value = str(
            self._call_context.get("effectiveRoute")
            or self._call_context.get("requestedRoute")
            or ""
        ).strip().lower()
        if value in {"pipeline", "omni"}:
            return value
        return ""

    def _is_omni_pipeline_fallback(self) -> bool:
        with self._omni_lock:
            return self._omni_pipeline_fallback

    def _start_omni_sidecar_asr(self) -> None:
        try:
            self._start_asr()
        except Exception as exc:  # noqa: BLE001
            self._omni_sidecar_asr_active = False
            self.logger.emit(
                "omni_sidecar_asr_error",
                callId=self.call_id,
                error=str(exc),
                detail="Omni 旁路实时 ASR 启动失败，将退回仅等待 Omni final 转写。",
            )
            return
        self._omni_sidecar_asr_active = True
        self.logger.emit(
            "omni_sidecar_asr_started",
            callId=self.call_id,
            model=self.config.asr_model,
            detail="已启动旁路实时 ASR，用于快速断句和低延迟回复兜底。",
        )

    def _stop_omni(self) -> None:
        if not self._omni:
            return
        try:
            self._omni.close()
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("omni_close_error", callId=self.call_id, error=str(exc))
        self._omni = None

    def handle_omni_closed(self, close_status_code: object, close_msg: object) -> None:
        with self._omni_lock:
            self._omni_closed = True
            self._omni = None
            already_closing = self._omni_unavailable_closing
            self._omni_unavailable_closing = True
        if self.stop_event.is_set() or already_closing:
            return
        reason = f"Omni 实时连接已关闭：code={close_status_code}, message={close_msg}"
        self.logger.emit(
            "omni_unavailable",
            callId=self.call_id,
            code=str(close_status_code),
            message=str(close_msg),
            detail="Omni 实时连接已关闭，当前通话自动降级到本地 ASR+LLM+TTS pipeline，继续保持通话。",
        )
        self._enable_omni_pipeline_fallback("omni_runtime_closed", RuntimeError(reason))

    def _close_after_omni_unavailable(self) -> None:
        with self.generation_lock:
            self.speech_generation += 1
            generation = self.speech_generation
        self.interrupt_event.set()
        self._speak("这边线路有点不稳，我稍后再联系您。", "omni_unavailable", generation, close_after=True)

    def _speak_opening_after_grace(self) -> None:
        if self._is_omni_pipeline_fallback():
            super()._speak_opening_after_grace()
            return
        grace = max(0.0, self.config.opening_grace_seconds)
        if grace and self.customer_activity_event.wait(grace):
            self.logger.emit("opening_deferred", callId=self.call_id, reason="remote_audio_detected", mode="omni")
            if not self._wait_for_remote_classification_before_opening("omni"):
                return
        if self._mark_opening_started():
            cached_voice_match = get_cached_opening_voice_match()
            opening_text = cached_voice_match.reply_text if cached_voice_match else self._opening_text_for_call()
            with self.generation_lock:
                generation = self.speech_generation
            self.logger.emit(
                "opening_start",
                callId=self.call_id,
                mode="omni",
                text=opening_text,
                merchantName=self._merchant_name(),
                source="voice_cache" if cached_voice_match else "local_tts",
                detail=(
                    "Omni 模式开场命中外呼语音包，直接播放预生成音频。"
                    if cached_voice_match
                    else "Omni 模式开场统一走本地发声链路，避免第一句和后续回复出现不同音色。"
                ),
            )
            self._record_omni_local_reply("", opening_text, source="omni_opening_local")
            threading.Thread(
                target=self._speak,
                args=(opening_text, "omni_opening_local", generation, False, cached_voice_match),
                daemon=True,
            ).start()

    def mark_omni_session_ready(self) -> None:
        with self._omni_lock:
            self._omni_session_ready = True

    def _is_omni_session_ready(self) -> bool:
        with self._omni_lock:
            return self._omni_session_ready

    def _request_omni_response(self, instruction: str) -> bool:
        if not self._omni or self.stop_event.is_set():
            return False
        instructions = (
            f"{build_video_group_buying_sales_instructions(self._merchant_name())}\n"
            f"{self._merchant_context_instruction()}\n{instruction}"
        )
        for attempt in range(2):
            with self._omni_lock:
                self._omni_response_request_active = True
                self._omni_response_request_started_at = time.monotonic()
            try:
                self._omni.create_response(
                    instructions=instructions,
                    output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],
                )
                return True
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                with self._omni_lock:
                    self._omni_response_request_active = False
                if "active response" in error.lower() and attempt == 0 and self._omni:
                    self.logger.emit(
                        "omni_response_active_conflict_retry",
                        callId=self.call_id,
                        error=error,
                        detail="实时模型仍有旧回复未关闭，已取消旧回复并重试本轮请求。",
                    )
                    try:
                        self._omni.cancel_response()
                    except Exception as cancel_exc:  # noqa: BLE001
                        if "none active response" not in str(cancel_exc):
                            self.logger.emit(
                                "omni_cancel_error",
                                callId=self.call_id,
                                error=str(cancel_exc),
                                source="active_conflict_retry",
                            )
                    time.sleep(0.12)
                    continue
                self.logger.emit("omni_response_request_error", callId=self.call_id, error=error)
                return False
        return False

    def _request_forced_omni_reply(self, customer_text: str, signal: str, reply: str, *, source: str, action: str) -> None:
        clean_reply = " ".join(reply.strip().split())
        if not clean_reply:
            return
        history_rows: list[str] = []
        for turn in self._conversation_history[-6:]:
            role = (turn.get("role") or "").strip().lower()
            content = " ".join(str(turn.get("content") or "").strip().split())
            if content:
                history_rows.append(f"{'客户' if role == 'user' else 'AI'}：{content[:70]}")
        history = "\n".join(history_rows)
        instruction = "\n".join(
            [
                "这是微信收口确认流程，必须保持单一音色并只输出指定句子。",
                f"客户刚说：{customer_text}",
                f"最近对话：\n{history or '无'}",
                f"只说这句：{clean_reply}",
                "不要补充解释，不要重复前面话术，不要问其他问题，只用普通话。",
            ]
        )
        with self._omni_lock:
            self._omni_pending_customer_text = customer_text
            self._omni_pending_signal = signal
            self._omni_pending_forced_reply = clean_reply
            self._omni_last_requested_text = customer_text
            self._omni_last_requested_at = time.monotonic()
        self.logger.emit(
            "wechat_closing_forced_reply",
            callId=self.call_id,
            text=customer_text,
            reply=clean_reply,
            action=action,
            source=source,
            detail="微信收口进入强制单句回复，避免模型重复普通发资料话术。",
        )
        if not self._request_omni_response(instruction):
            with self.generation_lock:
                self.speech_generation += 1
                generation = self.speech_generation
            fallback_source = f"wechat_closing_local_fallback_{action}"
            self._record_omni_local_reply(
                customer_text,
                clean_reply,
                pending_signal=signal,
                source=fallback_source,
            )
            threading.Thread(
                target=self._speak,
                args=(clean_reply, fallback_source, generation),
                daemon=True,
            ).start()

    def _respond_to_call_screening(self, text: str, *, source: str) -> None:
        self._call_screening_seen = True
        if self._call_screening_answered or self.stop_event.is_set():
            return
        self._call_screening_answered = True
        self.logger.emit(
            "call_screening_detected",
            callId=self.call_id,
            text=text,
            source=source,
            detail="Omni 识别到电话助理/秘书提示，只说明身份和来电原因，等待真人转接。",
        )
        with self._omni_lock:
            self._omni_pending_customer_text = text
            self._omni_pending_signal = "call_screening"
        self._request_omni_response(build_omni_turn_instruction(text, "call_screening", merchant_name=self._merchant_name()))
        self._schedule_call_screening_hangup(source)

    def _confirm_human_speech(self, text: str, *, detail: str) -> None:
        already_confirmed = self._human_speech_confirmed
        super()._confirm_human_speech(text, detail=detail)
        if already_confirmed or text.strip() or self.stop_event.is_set():
            return
        self.logger.emit(
            "opening_human_confirmed_without_text",
            callId=self.call_id,
            openingActive=self._opening_playback_active,
            speaking=self.speaking_event.is_set(),
            detail="真人接听只完成了音量/节奏确认，但还没有 ASR 文本；不再停止开场，避免第一句被切断后直接跳到下一段。",
        )
        self._human_greeting_fallback_generation += 1

    def _commit_human_greeting_fallback_after_delay(self, generation: int) -> None:
        time.sleep(1.6)
        if self.stop_event.is_set() or generation != self._human_greeting_fallback_generation:
            return
        with self.asr_partial_lock:
            if self._last_committed_customer_text:
                return
        if self.speaking_event.is_set():
            return
        self.logger.emit(
            "human_greeting_fallback_turn",
            callId=self.call_id,
            text="",
            reply=INTERRUPTED_OPENING_SHORT_FALLBACK_REPLY,
            detail="已确认真人接听但没有稳定转写，使用本地短句接住开场打断，避免 Omni 重复生成开场白。",
        )
        self._record_omni_local_reply("", INTERRUPTED_OPENING_SHORT_FALLBACK_REPLY, source="human_greeting_fallback_local")
        with self.generation_lock:
            self.speech_generation += 1
            speech_generation = self.speech_generation
        threading.Thread(
            target=self._speak,
            args=(INTERRUPTED_OPENING_SHORT_FALLBACK_REPLY, "human_greeting_fallback", speech_generation),
            daemon=True,
        ).start()

    def note_asr_partial_text(self, text: str) -> None:
        if self._is_omni_pipeline_fallback():
            super().note_asr_partial_text(text)
            return
        clean = " ".join(text.strip().split())
        if not clean:
            return
        self._note_customer_activity("omni_sidecar_asr_partial", text=clean)
        with self._omni_lock:
            if self._omni_barge_collecting:
                self._omni_barge_last_text = clean
        candidate = _stable_asr_partial_turn_text(clean)
        if not candidate or not should_commit_stable_asr_partial(candidate):
            with self.asr_partial_lock:
                if self._asr_partial_text and clean != self._asr_partial_text:
                    self._asr_partial_generation += 1
                    self._asr_partial_text = ""
            self.logger.emit(
                "turn_waiting_final",
                callId=self.call_id,
                text=clean,
                provider="qwen_asr_sidecar",
                reason="incomplete_or_nonactionable_partial",
                detail="旁路 ASR partial 还不够完整，继续等 final 或更稳定的短句。",
            )
            return
        with self.asr_partial_lock:
            self._asr_partial_generation += 1
            generation = self._asr_partial_generation
            self._asr_partial_text = candidate
        delay = _asr_partial_stable_delay_seconds(candidate)
        extra_fields = {"rawText": clean} if candidate != clean else {}
        self.logger.emit(
            "turn_endpoint_candidate",
            callId=self.call_id,
            text=candidate,
            provider="qwen_asr_sidecar",
            waitMs=int(delay * 1000),
            detail="旁路 ASR 已拿到可回答短句；若 Omni final 未到，将先触发回复。",
            **extra_fields,
        )
        threading.Thread(
            target=self._commit_omni_sidecar_asr_partial_after_delay,
            args=(generation, candidate, delay),
            name="ai-acq-omni-sidecar-asr-partial-turn",
            daemon=True,
        ).start()

    def commit_asr_final_text(self, text: str) -> None:
        if self._is_omni_pipeline_fallback():
            super().commit_asr_final_text(text)
            return
        self._cancel_pending_asr_partial_turn("omni_sidecar_asr_final")
        self._cancel_deferred_omni_transcription("omni_sidecar_asr_final", text=text)
        self.logger.emit(
            "turn_endpoint_final",
            callId=self.call_id,
            text=text,
            provider="qwen_asr_sidecar",
            detail="旁路 ASR final 已到达，先触发 Omni 回复，避免等待 Omni 自身 final。",
        )
        self.handle_omni_transcription(text, provider="qwen_asr_sidecar", source="omni_sidecar_asr_final")

    def _commit_omni_sidecar_asr_partial_after_delay(self, generation: int, text: str, delay: float) -> None:
        time.sleep(delay)
        if self.stop_event.is_set():
            return
        with self.asr_partial_lock:
            if generation != self._asr_partial_generation or text != self._asr_partial_text:
                return
        if not should_commit_stable_asr_partial(text):
            return
        self.logger.emit(
            "asr_partial_stable",
            callId=self.call_id,
            text=text,
            provider="qwen_asr_sidecar",
            waitMs=int(delay * 1000),
            detail="Omni final 尚未到达，旁路 ASR 短句已稳定，先接话避免客户空等。",
        )
        self._cancel_deferred_omni_transcription("omni_sidecar_asr_partial_stable", text=text)
        self.handle_omni_transcription(text, provider="qwen_asr_sidecar", source="omni_sidecar_asr_partial_stable")

    def handle_omni_speech_started(self) -> None:
        now = time.monotonic()
        self._note_customer_activity("omni_speech_started", now=now)
        if self.speaking_event.is_set():
            self.cancel_pending_speech("Omni 检测到客户插话，停止当前语音回复。", source="omni_vad")
            self._release_omni_playback_after_barge("omni_vad", now=now)
            return
        if now - self._last_remote_speech_started_at > 1.5:
            self._last_remote_speech_started_at = now
            self.logger.emit(
                "remote_speech_started",
                callId=self.call_id,
                detail="线路已接通并检测到对端声音，等待最终识别文本确认是真人还是电话助理。",
                provider="qwen_omni",
            )

    def handle_omni_input_buffer_event(self, event_type: str, response: dict[str, Any]) -> None:
        fields: dict[str, Any] = {"callId": self.call_id, "event": event_type, "provider": "qwen_omni"}
        item_id = response.get("item_id")
        if item_id:
            fields["itemId"] = item_id
        with self._omni_lock:
            if self._omni_barge_collecting:
                if event_type == "input_audio_buffer.speech_stopped":
                    self._omni_barge_server_stopped = True
                if event_type == "input_audio_buffer.committed":
                    self._omni_barge_server_committed = True
        self.logger.emit("omni_input_buffer_event", **fields)

    def _cancel_deferred_omni_transcription(self, source: str, *, text: str = "") -> None:
        with self._omni_lock:
            was_pending = self._omni_transcription_defer_pending
            self._omni_transcription_defer_pending = False
            self._omni_transcription_defer_generation += 1
        if was_pending:
            self.logger.emit(
                "omni_transcription_deferred_cancelled",
                callId=self.call_id,
                source=source,
                text=text[:100],
                detail="旁路 ASR 已提交本轮客户语音，取消 Omni 自带转写兜底，避免重复回复。",
            )

    def _defer_omni_transcription(self, text: str, *, signal: str, provider: str, source: str) -> None:
        with self._omni_lock:
            self._omni_transcription_defer_generation += 1
            generation = self._omni_transcription_defer_generation
            self._omni_transcription_defer_pending = True
        delay = OMNI_TRANSCRIPTION_FALLBACK_DELAY_SECONDS
        self.logger.emit(
            "omni_transcription_deferred",
            callId=self.call_id,
            text=text,
            provider=provider,
            source=source,
            signal=signal,
            waitMs=int(delay * 1000),
            detail="旁路实时 ASR 已启用，Omni 自带转写短暂等待旁路 ASR；若旁路未提交，将用该文本兜底接话。",
        )
        threading.Thread(
            target=self._commit_deferred_omni_transcription,
            args=(generation, text, delay),
            name="ai-acq-omni-transcription-fallback",
            daemon=True,
        ).start()

    def _commit_deferred_omni_transcription(self, generation: int, text: str, delay: float) -> None:
        time.sleep(delay)
        if self.stop_event.is_set():
            return
        with self._omni_lock:
            if generation != self._omni_transcription_defer_generation or not self._omni_transcription_defer_pending:
                return
            self._omni_transcription_defer_pending = False
        if self._is_recent_committed_customer_text(text):
            self.logger.emit(
                "omni_transcription_deferred_ignored",
                callId=self.call_id,
                text=text,
                provider="qwen_omni",
                source="omni_transcription_deferred",
                detail="Omni 自带转写兜底触发前，本轮客户语音已由旁路 ASR 处理，已忽略。",
            )
            return
        self.logger.emit(
            "omni_transcription_deferred_commit",
            callId=self.call_id,
            text=text,
            provider="qwen_omni",
            waitMs=int(delay * 1000),
            detail="旁路 ASR 未及时提交，使用 Omni 自带转写兜底回复，避免客户长时间空等。",
        )
        self.handle_omni_transcription(text, provider="qwen_omni", source="omni_transcription_deferred")

    def handle_omni_transcription(
        self,
        text: str,
        *,
        provider: str = "qwen_omni",
        source: str = "omni_transcription",
    ) -> None:
        clean = " ".join(text.strip().split())
        if not clean:
            return
        raw_clean = clean
        signal = classify_realtime_call_input(clean)
        if signal == "system_prompt":
            human_tail = extract_human_text_after_system_prompt(clean)
            if human_tail:
                self.logger.emit(
                    "system_prompt_stripped",
                    callId=self.call_id,
                    text=raw_clean,
                    strippedText=human_tail,
                    provider=provider,
                    detail="ASR 同一句里包含系统提示和真人客户语音，已只剥离系统提示并继续回复真人内容。",
                )
                clean = human_tail
                signal = classify_realtime_call_input(clean)
                if signal == "system_prompt":
                    signal = "human_speech"
        compacted_clean = _latest_actionable_omni_turn_text(clean)
        if compacted_clean and compacted_clean != clean:
            self.logger.emit(
                "omni_cumulative_transcription_compacted",
                callId=self.call_id,
                text=clean,
                selectedText=compacted_clean,
                provider=provider,
                source=source,
                detail="ASR 返回了累计长句，只取最后一个有效客户问题，避免重复排队回复。",
            )
            clean = compacted_clean
            signal = classify_realtime_call_input(clean)
        self._note_customer_activity(source, text=clean)
        if provider == "qwen_omni" and self._omni_sidecar_asr_active and source == "omni_transcription":
            self._defer_omni_transcription(clean, signal=signal, provider=provider, source=source)
            return
        human_confirmed_before = self._human_speech_confirmed
        self.handle_answer_text(clean, is_final=True)
        early_scripted_reply, _early_scripted_close_after = self._scripted_demo_reply(clean)
        with self._omni_lock:
            last_scripted_reply = self._last_omni_reply
        scripted_reply_already_spoken = bool(
            early_scripted_reply
            and _compact_customer_text(early_scripted_reply) == _compact_customer_text(last_scripted_reply)
        )
        duplicate_turn = self._is_recent_committed_customer_text(clean) and not (
            early_scripted_reply and not scripted_reply_already_spoken
        )
        with self._omni_lock:
            barge_collecting = self._omni_barge_collecting
        if duplicate_turn:
            if barge_collecting:
                with self._omni_lock:
                    self._omni_barge_last_text = clean
                    self._omni_barge_last_voice_at = time.monotonic()
                self.logger.emit(
                    "customer_turn_duplicate_ignored",
                    callId=self.call_id,
                    text=clean,
                    provider=provider,
                    source=source,
                    detail="打断恢复期间只收到重复转写，继续等待恢复兜底，不能让 AI 静默。",
                )
                return
            self.logger.emit(
                "customer_turn_duplicate_ignored",
                callId=self.call_id,
                text=clean,
                provider=provider,
                source=source,
                detail="同一句客户话已经由更快的 ASR/Omni 通道触发过回复，避免重复回答。",
            )
            return
        skip_response_after_forced_barge = False
        replace_forced_barge_response = False
        with self._omni_lock:
            self._omni_barge_collecting = False
            if self._omni_barge_forced_response_until > time.monotonic():
                if self._omni_barge_forced_audio_started:
                    skip_response_after_forced_barge = True
                else:
                    replace_forced_barge_response = True
        asr_fields: dict[str, Any] = {"callId": self.call_id, "text": clean, "provider": provider, "signal": signal}
        if source != "omni_transcription":
            asr_fields["source"] = source
        if raw_clean != clean:
            asr_fields["rawText"] = raw_clean
        self.logger.emit("asr_final", **asr_fields)
        self.logger.emit(
            "turn_endpoint_final",
            callId=self.call_id,
            text=clean,
            provider=provider,
            source=source,
            detail="客户本轮说话已由实时 ASR 端点提交，可以触发回复。",
        )
        if signal == "system_prompt":
            if classify_answer_text(clean) == CallAnswerType.VOICEMAIL:
                self.logger.emit(
                    "voicemail_detected",
                    callId=self.call_id,
                    text=clean,
                    detail="识别到语音信箱/留言提示，直接挂断不留言。",
                )
                self.stop_event.set()
                return
            self._system_prompt_seen = True
            self.logger.emit(
                "system_prompt_ignored",
                callId=self.call_id,
                text=clean,
                detail="识别到运营商或手机系统提示，已忽略，不触发销售回复。",
            )
            return
        normalization = normalize_realtime_sales_text(clean)
        routed_clean = normalization.normalized_text
        if normalization.changed:
            self.logger.emit(
                "asr_sales_text_normalized",
                callId=self.call_id,
                text=clean,
                normalizedText=routed_clean,
                provider=provider,
                fixes=list(normalization.fixes),
                detail="实时 ASR 文本进入销售脑前已做高置信语境纠错，原始转写仍保留在 ASR 事件中。",
            )
        intent, _node = _classify_intent(routed_clean)
        stage = self._sales_fsm.update(routed_clean, intent, signal)
        stage_instruction = self._sales_fsm.get_stage_instruction()
        if signal in {"terminal_close", "rejection"} and not _is_strong_terminal_close_text(routed_clean):
            guarded_signal = signal
            signal = "human_speech"
            if intent in {"明确拒绝", "礼貌结束"}:
                intent = "稍后联系" if _is_soft_busy_customer_text(routed_clean) else "低信息确认"
            stage = self._sales_fsm.update(routed_clean, intent, signal)
            stage_instruction = self._sales_fsm.get_stage_instruction()
            self.logger.emit(
                "terminal_close_guarded",
                callId=self.call_id,
                text=clean,
                normalizedText=routed_clean,
                originalSignal=guarded_signal,
                reroutedSignal=signal,
                reroutedIntent=intent,
                salesStage=stage.value,
                detail="客户文本不是明确挂断语，已拦截 Omni 自动挂断并继续进入回复。",
            )
        if signal in {"terminal_close", "rejection"}:
            if self._omni:
                try:
                    self._omni.cancel_response()
                except Exception as exc:  # noqa: BLE001
                    self.logger.emit("omni_cancel_error", callId=self.call_id, error=str(exc), source=signal)
            self.logger.emit(
                "terminal_close_detected",
                callId=self.call_id,
                text=clean,
                signal=signal,
                salesStage=stage.value,
                detail="客户已明确结束通话，直接短句收口并关闭电话。",
            )
            with self.generation_lock:
                self.speech_generation += 1
                generation = self.speech_generation
            self.interrupt_event.set()
            threading.Thread(target=self._speak, args=("好的，不打扰了，再见。", "terminal_close", generation, True), daemon=True).start()
            return
        first_human_after_screening = False
        if signal == "call_screening":
            self._call_screening_seen = True
            if self._call_screening_answered:
                self.logger.emit(
                    "call_screening_followup_ignored",
                    callId=self.call_id,
                    text=clean,
                    detail="电话助理后续等待提示已忽略，避免重复说明身份和来电原因。",
                )
                return
            self._call_screening_answered = True
            self.logger.emit(
                "call_screening_detected",
                callId=self.call_id,
                text=clean,
                detail="识别到电话助理/秘书提示，先说明身份和来电原因，等待真人转接。",
            )
            self._schedule_call_screening_hangup("omni_transcription")
        elif not human_confirmed_before:
            first_human_after_screening = self._call_screening_seen
            if not self._human_speech_confirmed:
                self._confirm_human_speech(clean, detail="已识别到真人客户语音，可以进入实时对话。")
        if signal != "call_screening":
            self._record_realtime_intent_signal(routed_clean, intent, signal, source)
            wechat_result = self._sales_fsm.handle_wechat_closing_turn(routed_clean, intent, phone=self._call_phone())
            scripted_reply, scripted_close_after = self._scripted_demo_reply(routed_clean)
            if scripted_reply:
                if _is_business_category_signal(routed_clean):
                    self._record_realtime_intent_signal(
                        routed_clean,
                        "品类确认",
                        signal,
                        "scripted_business_category",
                        force=True,
                        evidence="客户主动说明门店品类，已进入可跟进意向。",
                        latest_signal=f"客户主动说明门店品类：{routed_clean}",
                        intent_level="B",
                        intent_score=78,
                        need_handoff=True,
                    )
                if wechat_result and wechat_result.record:
                    self._record_realtime_wechat_signal(
                        routed_clean,
                        signal,
                        "scripted_demo_wechat_closing",
                        wechat_id=wechat_result.wechat_id,
                        wechat_is_phone=wechat_result.wechat_is_phone,
                        summary=wechat_result.summary,
                    )
                self._log_omni_cached_voice_skip(routed_clean, signal=signal, intent=intent, stage=stage.value)
                self._speak_scripted_demo_reply(
                    routed_clean,
                    scripted_reply,
                    signal=signal,
                    source=source,
                    close_after=scripted_close_after,
                )
                return
            if wechat_result:
                if wechat_result.record:
                    self._record_realtime_wechat_signal(
                        routed_clean,
                        signal,
                        "omni_wechat_closing",
                        wechat_id=wechat_result.wechat_id,
                        wechat_is_phone=wechat_result.wechat_is_phone,
                        summary=wechat_result.summary,
                    )
                if not wechat_result.reply:
                    self.logger.emit(
                        "wechat_closing_waiting_more_text",
                        callId=self.call_id,
                        text=routed_clean,
                        provider=provider,
                        source=source,
                        action=wechat_result.action,
                        detail="客户的手机号微信确认还没说完整，先不回复也不记入去重，继续听下一段。",
                    )
                    return
                wechat_close_after = wechat_result.action in {
                    "phone_is_wechat_confirmed",
                    "wechat_already_confirmed",
                    "wechat_id_captured",
                }
                self._remember_committed_customer_text(clean)
                self._cancel_active_omni_response_for_new_turn(clean, source=source)
                self._log_omni_cached_voice_skip(routed_clean, signal=signal, intent=intent, stage=stage.value)
                if wechat_close_after:
                    self._record_omni_local_reply(
                        clean,
                        wechat_result.reply,
                        pending_signal=signal,
                        source=f"wechat_closing_{wechat_result.action}",
                    )
                    with self.generation_lock:
                        self.speech_generation += 1
                        generation = self.speech_generation
                    self.logger.emit(
                        "wechat_closing_terminal_reply",
                        callId=self.call_id,
                        text=routed_clean,
                        action=wechat_result.action,
                        generation=generation,
                        detail="客户已确认微信，直接播放礼貌收口并主动结束通话。",
                    )
                    threading.Thread(
                        target=self._speak,
                        args=(wechat_result.reply, "wechat_closing", generation, True),
                        daemon=True,
                    ).start()
                elif self._omni and not self.stop_event.is_set():
                    self._request_forced_omni_reply(
                        clean,
                        signal,
                        wechat_result.reply,
                        source=source,
                        action=wechat_result.action,
                    )
                else:
                    with self.generation_lock:
                        self.speech_generation += 1
                        generation = self.speech_generation
                    self._record_omni_local_reply(
                        clean,
                        wechat_result.reply,
                        pending_signal=signal,
                        source=f"wechat_closing_{wechat_result.action}",
                    )
                    threading.Thread(
                        target=self._speak,
                        args=(wechat_result.reply, "wechat_closing", generation),
                        daemon=True,
                    ).start()
                return
        if skip_response_after_forced_barge:
            self.logger.emit(
                "barge_transcription_after_forced_response",
                callId=self.call_id,
                text=clean,
                detail="打断后已用提交的音频创建回复，这条转写只记录，不重复触发回复。",
            )
            return
        if replace_forced_barge_response and self._omni:
            try:
                self._omni.cancel_response()
            except Exception as exc:  # noqa: BLE001
                self.logger.emit("omni_cancel_error", callId=self.call_id, error=str(exc), source="barge_transcription")
            self.logger.emit(
                "barge_transcription_replaces_forced_response",
                callId=self.call_id,
                text=clean,
                detail="打断后的文字转写先于强制回复音频到达，改用文字转写生成更准确回复。",
            )
        self._log_omni_cached_voice_skip(routed_clean, signal=signal, intent=intent, stage=stage.value)
        history_snapshot = list(self._conversation_history)
        self._remember_committed_customer_text(clean)
        self._cancel_active_omni_response_for_new_turn(clean, source=source)
        self.logger.emit(
            "turn_reply_preparing",
            callId=self.call_id,
            text=routed_clean,
            source=source,
            detail="客户本轮已提交给实时语音模型，准备生成回复。",
        )
        self.logger.emit(
            "turn_llm_start",
            callId=self.call_id,
            text=routed_clean,
            intent=intent,
            signal=signal,
            salesStage=stage.value,
            historyTurns=len(history_snapshot),
            provider=provider,
            detail="客户本轮已进入 Omni 回复生成，等待首个音频块。",
        )
        with self._omni_lock:
            self._omni_pending_customer_text = clean
            self._omni_pending_signal = signal
            self._omni_pending_forced_reply = ""
            last_reply = self._last_omni_reply
            self._omni_last_requested_text = clean
            self._omni_last_requested_at = time.monotonic()
        instruction = build_omni_turn_instruction(
            clean,
            signal,
            recent_history=history_snapshot,
            first_human_after_screening=first_human_after_screening,
            last_reply=last_reply,
            stage_instruction=stage_instruction,
            merchant_name=self._merchant_name(),
        )
        if not self._request_omni_response(instruction):
            fallback_text = self._local_omni_timeout_reply(clean, signal)
            self._record_omni_local_reply(
                clean,
                fallback_text,
                pending_signal=signal,
                source="omni_request_local_fallback",
            )
            with self.generation_lock:
                self.speech_generation += 1
                generation = self.speech_generation
            self.logger.emit(
                "omni_request_local_fallback",
                callId=self.call_id,
                text=clean,
                signal=signal,
                fallbackText=fallback_text,
                generation=generation,
                detail="实时模型回复请求失败，已立即切换本地短句，避免电话里空等。",
            )
            threading.Thread(
                target=self._speak,
                args=(fallback_text, "omni_request_local_fallback", generation),
                daemon=True,
            ).start()

    def _log_omni_cached_voice_skip(
        self,
        text: str,
        *,
        signal: str,
        intent: str,
        stage: str,
    ) -> None:
        if signal == "call_screening":
            return
        cached_voice_match = match_cached_voice_reply(text)
        if cached_voice_match:
            self.logger.emit(
                "voice_cache_candidate",
                callId=self.call_id,
                text=text,
                intent=intent,
                intentId=cached_voice_match.intent_id,
                sceneTitle=cached_voice_match.scene_title,
                seqs=list(cached_voice_match.seqs),
                confidence=cached_voice_match.confidence,
                matchedTrigger=cached_voice_match.matched_trigger,
                voiceProfile=cached_voice_match.voice_profile,
                omniVoice=self.config.omni_voice,
                salesStage=stage,
                reason="scripted_voice_cache_available",
                detail="当前客户话术可命中外呼语音包；若固定分支接管，将优先播放预生成音频。",
            )

    def _scripted_demo_reply(self, text: str) -> tuple[str, bool]:
        clean = normalize_realtime_sales_text(text or "").normalized_text
        compact = _compact_customer_text(clean)
        if not compact:
            return "", False
        with self._omni_lock:
            last_reply = self._last_omni_reply
        phone_confirming = any(keyword in last_reply for keyword in ("这个手机号就是您的微信吗", "手机号就是您的微信"))
        asking_wechat = any(keyword in last_reply for keyword in ("方便加个微信吗", "微信上把案例", "加您微信"))
        has_solution_intro = _reply_has_solution_intro(last_reply)
        if phone_confirming and (
            _is_wechat_affirmative_text(clean)
            or compact in {"就是", "是我是我的"}
            or any(keyword in compact for keyword in ("是我的微信", "就是我的微信", "手机号就是微信", "这个号就是微信"))
        ):
            return "好的，我稍后按这个手机号添加您，您通过后我把案例和费用区间发过去。感谢您接听，先不多打扰了。", True
        if any(keyword in compact for keyword in ("是我的微信", "就是我的微信", "手机号就是微信", "这个号就是微信")):
            return "好的，我稍后按这个手机号添加您，您通过后我把案例和费用区间发过去。感谢您接听，先不多打扰了。", True
        if any(keyword in compact for keyword in ("不方便", "挂电话", "挂了", "再见", "拜拜", "不聊了", "不说了")):
            return "好的，不打扰了，再见。", True
        if compact == "不要":
            return "我确认一下，您是想先了解资料，还是暂时不需要？", False
        if asking_wechat and _is_wechat_affirmative_text(clean):
            return "可以，我加您微信，把案例、流程和费用区间发您。这个手机号就是您的微信吗？", False
        if compact in {"喂", "喂喂", "你好", "您好"} and self._opening_started:
            return "嗯，不是卖课，也不是平台招商，就是看你们店应该能做到店套餐，想问下你有没有了解过视频号团购这块。", False

        cached_voice_match = match_cached_voice_reply(clean)
        if cached_voice_match:
            return cached_voice_match.reply_text, False

        if compact in {"喂", "喂喂", "你好", "您好"}:
            return "喂，老板你好，是你们店吧？我这边跟你确认个事，占你二十秒就行。", False
        if _is_identity_question_text(compact):
            return "我这边是视频号服务商，主要帮线下实体商家开通团购业务。开通后直播、短视频这些，都可以往团购套餐上挂。 简单说，就是帮商家把视频号里的定位、电话、团购套餐，还有核销流程弄起来。", False
        if _is_no_videohao_prior_knowledge(compact) and any(
            marker in _compact_customer_text(last_reply)
            for marker in ("有没有了解过视频号团购", "有没有了解视频号团购", "想问下你有没有了解")
        ):
            return "你可以简单理解成，给门店多开一个微信视频号里的本地团购入口。 客户在微信和视频号里看到你，可以看到门店位置、电话、团购套餐，然后再决定要不要到店。", False
        if compact in {"什么", "什么鬼", "啥意思", "什么意思", "什么东西"} or any(
            keyword in compact for keyword in ("什么鬼", "啥意思", "什么意思")
        ):
            return "我短说：我们帮门店做视频号团购套餐和微信同城曝光，把附近客户引到店。", False
        if any(keyword in compact for keyword in ("听不清", "没听清", "听不懂", "没听懂", "不太懂", "再说一遍", "重新说")):
            return "我短说：我们帮门店做视频号团购套餐和微信同城曝光，把附近客户引到店。", False
        if _is_interest_to_learn_signal(clean):
            if has_solution_intro:
                return SOFT_WECHAT_OFFER_REPLY, False
            return SOLUTION_INTRO_REPLY, False
        if any(keyword in compact for keyword in ("美团", "抖音", "大众点评", "点评", "有什么区别", "啥区别", "什么区别")):
            return "美团偏搜索下单，视频号偏微信同城曝光和私域沉淀，是补充，不是替代。", False
        if any(keyword in compact for keyword in ("效果能保证", "能保证吗", "保证吗", "保底", "效果")):
            return "不能空口保证成交，只能先用小范围测试看真实曝光、咨询和到店数据，再决定要不要放大。", False
        if any(keyword in compact for keyword in ("费用怎么算", "费用", "价格", "收费", "多少钱", "报价")):
            return "费用要看门店品类、套餐数量和投放节奏，我这边先判断适不适合，不合适就不建议做。", False
        if any(keyword in compact for keyword in ("具体怎么做", "具体做", "怎么做", "流程", "怎么合作")):
            return SOFT_WECHAT_OFFER_REPLY if has_solution_intro else SOLUTION_INTRO_REPLY, False
        if _is_business_category_signal(clean):
            return BUSINESS_CATEGORY_REPLY, False
        if compact in {
            "你说",
            "您说",
            "说你说",
            "说您说",
            "方便你说",
            "方便您说",
            "方便说",
            "你方便说",
            "您方便说",
            "那你说",
            "那您说",
            "你讲",
            "您讲",
            "继续",
            "继续说",
            "继续讲",
            "你继续",
            "您继续",
            "说吧",
            "讲吧",
            "往下说",
            "往下讲",
            "接着说",
            "接着讲",
        }:
            return SOFT_WECHAT_OFFER_REPLY if has_solution_intro else SOLUTION_INTRO_REPLY, False
        return "", False

    def _should_suppress_repeated_scripted_reply(self, text: str, reply: str) -> bool:
        reply_compact = _compact_customer_text(reply)
        if not reply_compact:
            return False
        with self._omni_lock:
            last_reply = self._last_omni_reply
            last_reply_at = self._last_omni_reply_at
        if reply_compact != _compact_customer_text(last_reply):
            return False
        recent_same_reply = last_reply_at and time.monotonic() - last_reply_at <= SCRIPTED_REPLY_SUPPRESS_SECONDS
        if not recent_same_reply and not self.speaking_event.is_set():
            return False
        self._remember_committed_customer_text(text)
        self.logger.emit(
            "scripted_demo_reply_suppressed",
            callId=self.call_id,
            text=text,
            reply=reply,
            secondsSinceLastReply=round(time.monotonic() - last_reply_at, 3) if last_reply_at else None,
            speaking=self.speaking_event.is_set(),
            detail="同一个固定话术正在播放或刚播完，忽略 ASR 重复提交，避免打断后重播造成卡顿。",
        )
        return True

    def _speak_scripted_demo_reply(
        self,
        text: str,
        reply: str,
        *,
        signal: str,
        source: str,
        close_after: bool = False,
    ) -> None:
        cached_voice_match = match_cached_voice_reply(text) or match_cached_voice_reply(reply)
        reply_to_play = cached_voice_match.reply_text if cached_voice_match else reply
        if self._should_suppress_repeated_scripted_reply(text, reply_to_play):
            return
        self._remember_committed_customer_text(text)
        self._cancel_active_omni_response_for_new_turn(text, source=source)
        self._record_omni_local_reply(text, reply_to_play, pending_signal=signal, source="scripted_demo_reply")
        with self.generation_lock:
            self.speech_generation += 1
            generation = self.speech_generation
        self.logger.emit(
            "scripted_demo_reply",
            callId=self.call_id,
            text=text,
            reply=reply_to_play,
            source=source,
            generation=generation,
            closeAfter=close_after,
            voiceCacheIntentId=cached_voice_match.intent_id if cached_voice_match else "",
            voiceCacheSeqs=list(cached_voice_match.seqs) if cached_voice_match else [],
            voiceCacheProfile=cached_voice_match.voice_profile if cached_voice_match else "",
            detail=(
                "命中演示主线话术和外呼语音包，直接播放预生成固定话术音频。"
                if cached_voice_match
                else "命中演示主线话术，直接用本地实时 TTS 播放固定句，避免等待 Omni 自由生成。"
            ),
        )
        threading.Thread(
            target=self._speak,
            args=(reply_to_play, "scripted_demo_reply", generation, close_after, cached_voice_match),
            daemon=True,
        ).start()

    def _cancel_active_omni_response_for_new_turn(self, text: str, *, source: str) -> None:
        now = time.monotonic()
        with self._omni_lock:
            response_id = self._omni_response_id
            pending_text = self._omni_pending_customer_text
            recent_pending = bool(
                pending_text
                and self._omni_last_requested_at
                and now - self._omni_last_requested_at <= OMNI_FIRST_AUDIO_DEADLINE_SECONDS + 1.0
            )
            request_active = bool(
                self._omni_response_request_active
                and self._omni_response_request_started_at
                and now - self._omni_response_request_started_at <= OMNI_FIRST_AUDIO_DEADLINE_SECONDS + 1.0
            )
            active = bool(response_id or recent_pending or request_active or self.speaking_event.is_set())
            if not active:
                return
            if response_id:
                self._omni_cancelled_response_ids.add(response_id)
            self._omni_response_id = ""
            self._omni_response_request_active = False
            self._omni_reply_parts = []
            self._omni_pending_audio = b""
            self._omni_next_frame_at = None
            self._omni_playback_lag_events = 0
            self._omni_pending_forced_reply = ""
        if self._omni:
            try:
                self._omni.cancel_response()
            except Exception as exc:  # noqa: BLE001
                if "none active response" not in str(exc):
                    self.logger.emit("omni_cancel_error", callId=self.call_id, error=str(exc), source="new_customer_turn")
        generation = self.cancel_pending_speech(
            "客户新问题到达，停止旧的 Omni 回复并改答最新问题。",
            source="omni_text_interrupt",
        )
        self.logger.emit(
            "omni_active_response_replaced",
            callId=self.call_id,
            text=text,
            previousText=pending_text,
            responseId=response_id,
            source=source,
            generation=generation,
            detail="新客户问题到达时已取消旧回复，避免旧答案和新答案排队或重复播放。",
        )

    def _handle_audio(self, payload: bytes) -> None:
        if self._is_omni_pipeline_fallback():
            super()._handle_audio(payload)
            return
        if self._audio_capture:
            self._audio_capture.write_inbound(payload)
        rms = _pcm_rms(payload)
        now = time.monotonic()
        self._emit_remote_audio_sample(rms, now)
        self._handle_answer_audio(rms, now)
        barge_threshold = self._omni_effective_barge_rms_threshold()
        if rms >= barge_threshold:
            self._note_customer_activity("omni_remote_audio", now=now)
        opening_barge_ready = self._omni_opening_barge_ready()
        if self.speaking_event.is_set() and (self._omni_local_barge_ready() or opening_barge_ready):
            if rms >= barge_threshold:
                self._loud_frames += 1
            else:
                self._loud_frames = 0
            if self._loud_frames >= self.config.barge_frames and now - self._last_barge_at > 0.8:
                if opening_barge_ready:
                    self.cancel_pending_speech("客户接听或插话，停止 Omni 开场。", source="omni_opening_rms", rms=rms)
                    self._barge_forward_until = now + BARGE_AUDIO_FORWARD_SECONDS
                    self.logger.emit(
                        "opening_interrupted_by_remote_audio",
                        callId=self.call_id,
                        rms=rms,
                        threshold=barge_threshold,
                        detail="开场播放期间检测到真人语音，已停止开场并继续等待客户转写。",
                    )
                else:
                    self.cancel_pending_speech("客户插话，停止 Omni 语音回复。", source="omni_rms", rms=rms)
                    self._release_omni_playback_after_barge("omni_rms", now=now)
        else:
            self._loud_frames = 0
        if self._omni and not self._omni_closed and payload:
            try:
                self._omni.append_audio(base64.b64encode(_upsample_pcm_8k_to_16k(payload)).decode("ascii"))
            except Exception as exc:  # noqa: BLE001
                if "already closed" in str(exc).lower():
                    self.handle_omni_closed("append_error", exc)
                else:
                    self.logger.emit("omni_audio_append_error", callId=self.call_id, error=str(exc))
        if self._recognition and payload:
            try:
                self._recognition.send_audio_frame(payload)
            except Exception as exc:  # noqa: BLE001
                self.logger.emit("omni_sidecar_asr_audio_error", callId=self.call_id, error=str(exc))
        self._maybe_commit_omni_barge_turn(now, rms, barge_threshold)

    def _omni_local_barge_ready(self) -> bool:
        with self._omni_lock:
            return self._omni_tts_started and self._omni_audio_sent >= OMNI_LOCAL_BARGE_MIN_SENT_BYTES

    def _omni_opening_barge_ready(self) -> bool:
        # Do not stop the first cached opening only because inbound RMS is loud.
        # Gateway echo and answer noise often look like speech here, which cuts
        # "我这边跟你确认个事..." in half and leaves a long ASR wait. A real
        # customer turn can still interrupt through ASR final/text handling.
        return False

    def _omni_effective_barge_rms_threshold(self) -> int:
        if self._omni_opening_barge_ready():
            return max(900, min(self.config.barge_rms_threshold, int(self.config.barge_rms_threshold * 0.65)))
        return self.config.barge_rms_threshold

    def _release_omni_playback_after_barge(self, source: str, now: float | None = None) -> None:
        now = now or time.monotonic()
        with self.speech_state_lock:
            self.speech_jobs = 0
            self.speaking_event.clear()
        cancelled_response_id = ""
        with self._omni_lock:
            cancelled_response_id = self._omni_response_id
            if cancelled_response_id:
                self._omni_cancelled_response_ids.add(cancelled_response_id)
                self._omni_response_id = ""
            self._omni_pending_audio = b""
            self._omni_next_frame_at = None
            self._omni_barge_collecting = True
            self._omni_barge_started_at = now
            self._omni_barge_last_voice_at = now
            self._omni_barge_forced_requested = False
            self._omni_barge_server_stopped = False
            self._omni_barge_server_committed = False
            self._omni_barge_last_text = ""
            self._omni_barge_recovery_generation += 1
            recovery_generation = self._omni_barge_recovery_generation
        if self._omni:
            try:
                self._omni.cancel_response()
            except Exception as exc:  # noqa: BLE001
                self.logger.emit("omni_cancel_error", callId=self.call_id, error=str(exc), source=source)
        self._loud_frames = 0
        self.logger.emit(
            "barge_recovery_ready",
            callId=self.call_id,
            source=source,
            cancelledResponseId=cancelled_response_id,
            detail="已停止本地播放并恢复监听，等待客户本轮语音最终识别后再回复。",
        )
        threading.Thread(
            target=self._omni_barge_recovery_watchdog,
            args=(recovery_generation,),
            name="ai-acq-omni-barge-recovery-watchdog",
            daemon=True,
        ).start()

    def _maybe_commit_omni_barge_turn(self, now: float, rms: int, barge_threshold: int | None = None) -> None:
        threshold = barge_threshold or self.config.barge_rms_threshold
        if rms >= threshold:
            with self._omni_lock:
                if self._omni_barge_collecting:
                    self._omni_barge_last_voice_at = now
        self._commit_omni_barge_recovery("omni_rms_recovery", now=now)

    def _omni_barge_recovery_watchdog(self, generation: int) -> None:
        time.sleep(OMNI_BARGE_RECOVERY_WATCHDOG_SECONDS)
        if self.stop_event.is_set():
            return
        self._commit_omni_barge_recovery(
            "barge_recovery_watchdog",
            now=time.monotonic(),
            recovery_generation=generation,
        )

    def _commit_omni_barge_recovery(
        self,
        source: str,
        *,
        now: float,
        recovery_generation: int | None = None,
    ) -> bool:
        with self._omni_lock:
            collecting = self._omni_barge_collecting
            started_at = self._omni_barge_started_at
            last_voice_at = self._omni_barge_last_voice_at
            forced_requested = self._omni_barge_forced_requested
            current_generation = self._omni_barge_recovery_generation
            if recovery_generation is not None and recovery_generation != current_generation:
                return False
            if not collecting or forced_requested:
                return False
            elapsed = now - started_at
            silence = now - last_voice_at
            should_commit = elapsed >= OMNI_BARGE_RECOVERY_MIN_SECONDS and (
                silence >= OMNI_BARGE_RECOVERY_SILENCE_SECONDS
                or elapsed >= OMNI_BARGE_RECOVERY_MAX_SECONDS
            )
            if not should_commit:
                return False
            self._omni_barge_collecting = False
            self._omni_barge_forced_requested = True
            self._omni_barge_forced_response_until = 0.0
            self._omni_barge_forced_audio_started = False
        self.logger.emit(
            "barge_recovery_waiting_final",
            callId=self.call_id,
            source=source,
            elapsedMs=int(elapsed * 1000),
            silenceMs=int(silence * 1000),
            detail="客户打断后已停止旧回复并继续等待 ASR 终稿或稳定完整句，避免抢半句话造成重复和卡顿。",
        )
        return False

    def start_omni_response(self, response_id: str) -> None:
        with self._omni_lock:
            if response_id and response_id in self._omni_cancelled_response_ids:
                self._omni_response_request_active = False
                self.logger.emit("omni_stale_response_start_ignored", callId=self.call_id, responseId=response_id)
                return
        with self.generation_lock:
            self.speech_generation += 1
            generation = self.speech_generation
        with self._omni_lock:
            self._omni_generation = generation
            self._omni_response_id = response_id
            self._omni_response_request_active = False
            self._omni_reply_parts = []
            self._omni_pending_audio = b""
            self._omni_next_frame_at = None
            self._omni_playback_lag_events = 0
            self._omni_first_audio_ms = 0
            self._omni_audio_sent = 0
            self._omni_audio_total = 0
            self._omni_response_started_at = time.perf_counter()
            self._omni_tts_started = False
        self.interrupt_event.clear()
        self._mark_speech_job_started()
        self.logger.emit("omni_response_start", callId=self.call_id, responseId=response_id, generation=generation)
        threading.Thread(
            target=self._omni_response_audio_watchdog,
            args=(generation, response_id),
            daemon=True,
        ).start()

    def _omni_response_audio_watchdog(self, generation: int, response_id: str) -> None:
        time.sleep(OMNI_FIRST_AUDIO_DEADLINE_SECONDS)
        with self._omni_lock:
            should_fallback = (
                self._omni_generation == generation
                and self._omni_response_id == response_id
                and not self._omni_tts_started
                and not self._omni_closed
            )
            pending_text = self._omni_pending_customer_text
            pending_signal = self._omni_pending_signal
        if not should_fallback or self.stop_event.is_set() or self._speech_is_obsolete(generation):
            return
        fallback_text = self._local_omni_timeout_reply(pending_text, pending_signal)
        if self._omni:
            try:
                self._omni.cancel_response()
            except Exception as exc:  # noqa: BLE001
                self.logger.emit("omni_cancel_error", callId=self.call_id, error=str(exc), source="first_audio_watchdog")
        with self._omni_lock:
            if response_id:
                self._omni_cancelled_response_ids.add(response_id)
            if self._omni_response_id == response_id:
                self._omni_response_id = ""
                self._omni_response_request_active = False
                self._omni_reply_parts = []
                self._omni_pending_audio = b""
                self._omni_next_frame_at = None
        self._mark_speech_job_finished()
        with self.generation_lock:
            if self.speech_generation != generation:
                return
            self.speech_generation += 1
            fallback_generation = self.speech_generation
        self.interrupt_event.set()
        self._record_omni_local_reply(
            pending_text,
            fallback_text,
            pending_signal=pending_signal,
            source="omni_response_slow_fallback",
        )
        self.logger.emit(
            "omni_response_slow_fallback",
            callId=self.call_id,
            responseId=response_id,
            text=pending_text,
            signal=pending_signal,
            fallbackText=fallback_text,
            deadlineMs=int(OMNI_FIRST_AUDIO_DEADLINE_SECONDS * 1000),
            generation=fallback_generation,
            detail="实时模型超过首音频预算，已切到本地短句，避免电话里长时间沉默。",
        )
        threading.Thread(
            target=self._speak,
            args=(fallback_text, "omni_response_slow_fallback", fallback_generation),
            daemon=True,
        ).start()

    def _local_omni_timeout_reply(self, pending_text: str, pending_signal: str) -> str:
        with self._omni_lock:
            forced_reply = self._omni_pending_forced_reply
        if forced_reply:
            return forced_reply
        signal = (pending_signal or "").strip()
        normalization = normalize_realtime_sales_text(pending_text or "")
        text = normalization.normalized_text
        if signal == "call_screening":
            return self._screening_handoff_reply()
        if signal == "continue_prompt":
            with self._omni_lock:
                last_reply = self._last_omni_reply
            if _reply_has_solution_intro(last_reply):
                return SOFT_WECHAT_OFFER_REPLY
            return SOLUTION_INTRO_REPLY
        if signal in {"identity_handoff", "human_greeting"}:
            return self._identity_opening_reply()
        if signal == "audio_issue":
            return "我短说：我是做视频号团购到店获客的，帮门店做套餐和微信同城曝光。"
        if signal == "repetition_complaint":
            return "我不重复。您想听费用、效果，还是和美团区别？"
        if signal == "direct_answer_only":
            return "不推资料。您直接问费用、效果或流程，我按问题答。"
        if signal in {"terminal_close", "rejection"}:
            if not _is_strong_terminal_close_text(text):
                if _is_soft_busy_customer_text(text):
                    return "那我短说一句：我们是帮门店做视频号团购曝光和到店获客的。"
                return OMNI_NO_AUDIO_FALLBACK_TEXT
            return "好的，不打扰了，再见。"
        if normalization.has_fix("group_buying_package"):
            return "不是4G套餐，是团购套餐，就是客户线上下单、到店核销的优惠套餐。"
        if _is_business_category_signal(text):
            return BUSINESS_CATEGORY_REPLY
        if _is_interest_to_learn_signal(text):
            with self._omni_lock:
                last_reply = self._last_omni_reply
            return SOFT_WECHAT_OFFER_REPLY if _reply_has_solution_intro(last_reply) else SOLUTION_INTRO_REPLY
        if any(keyword in text for keyword in ["具体怎么做", "怎么做", "套餐", "介绍", "流程", "怎么合作", "说一下", "讲一下"]):
            with self._omni_lock:
                last_reply = self._last_omni_reply
            return SOFT_WECHAT_OFFER_REPLY if _reply_has_solution_intro(last_reply) else SOLUTION_INTRO_REPLY
        if any(keyword in text for keyword in ["费用", "价格", "收费", "要钱", "付费"]):
            return "费用要看门店品类、套餐数量和投放节奏，我这边先判断适不适合，不合适就不建议做。"
        if any(keyword in text for keyword in ["美团", "抖音", "大众点评"]):
            return "美团偏搜索成交，视频号偏微信同城曝光和私域沉淀，是补充。"
        if any(keyword in text for keyword in ["效果", "客流", "到店", "保证", "保底"]):
            return "不能空口保证成交，只能先用小范围测试看真实曝光、咨询和到店数据，再决定要不要放大。"
        return OMNI_NO_AUDIO_FALLBACK_TEXT

    def _record_omni_local_reply(
        self,
        customer_text: str,
        assistant_reply: str,
        *,
        pending_signal: str = "",
        source: str,
    ) -> None:
        reply = " ".join(assistant_reply.strip().split())
        if not reply:
            return
        clean_customer = " ".join(customer_text.strip().split())
        if clean_customer and pending_signal != "call_screening":
            self._append_conversation_turn(clean_customer, reply)
        elif source in {"omni_opening_local", "human_greeting_fallback_local"}:
            self._call_history.append({"role": "assistant", "content": reply})
            self._conversation_history.append({"role": "assistant", "content": reply})
            if len(self._conversation_history) > 12:
                del self._conversation_history[: len(self._conversation_history) - 12]
        self._sales_fsm.record_assistant_reply(reply)
        with self._omni_lock:
            self._last_omni_reply = reply
            self._last_omni_reply_at = time.monotonic()
            if self._omni_pending_customer_text == clean_customer:
                self._omni_pending_customer_text = ""
                self._omni_pending_signal = ""
                self._omni_pending_forced_reply = ""
        self.logger.emit(
            "omni_local_reply_recorded",
            callId=self.call_id,
            source=source,
            text=clean_customer,
            reply=reply,
            historyTurns=len(self._conversation_history),
            detail="本地兜底话术已写入对话历史，避免下一轮实时模型重复上一句。",
        )

    def _is_omni_response_stale_locked(self, response_id: str) -> bool:
        if response_id and response_id in self._omni_cancelled_response_ids:
            return True
        return bool(response_id and self._omni_response_id and response_id != self._omni_response_id)

    def append_omni_transcript_delta(self, delta: str, response_id: str = "") -> None:
        if not delta:
            return
        with self._omni_lock:
            if self._is_omni_response_stale_locked(response_id):
                self.logger.emit(
                    "omni_stale_transcript_delta_dropped",
                    callId=self.call_id,
                    responseId=response_id,
                    currentResponseId=self._omni_response_id,
                )
                return
            self._omni_reply_parts.append(delta)

    def finish_omni_transcript(self, transcript: str, response_id: str = "") -> None:
        with self._omni_lock:
            if self._is_omni_response_stale_locked(response_id):
                self.logger.emit(
                    "omni_stale_transcript_done_dropped",
                    callId=self.call_id,
                    responseId=response_id,
                    currentResponseId=self._omni_response_id,
                )
                return
            reply = transcript.strip() or "".join(self._omni_reply_parts).strip()
            pending_text = self._omni_pending_customer_text
            pending_signal = self._omni_pending_signal
        if reply:
            if pending_text and pending_signal != "call_screening":
                self._append_conversation_turn(pending_text, reply)
            self._sales_fsm.record_assistant_reply(reply)
            history_turns = len(self._conversation_history)
            with self._omni_lock:
                self._last_omni_reply = reply
                self._last_omni_reply_at = time.monotonic()
                if self._omni_pending_customer_text == pending_text:
                    self._omni_pending_customer_text = ""
                    self._omni_pending_signal = ""
                    self._omni_pending_forced_reply = ""
            self.logger.emit(
                "llm_reply",
                callId=self.call_id,
                reply=reply,
                strategy="qwen_omni_realtime",
                latencyMs=0,
                fallbackUsed=False,
                historyTurns=history_turns,
                error=None,
            )

    def play_omni_audio_delta(self, delta: str, response_id: str = "") -> None:
        if not delta:
            return
        try:
            audio = base64.b64decode(delta)
        except Exception as exc:  # noqa: BLE001
            self.logger.emit("omni_audio_decode_error", callId=self.call_id, error=str(exc))
            return
        with self.playback_lock:
            with self._omni_lock:
                if self._omni_barge_collecting or self._is_omni_response_stale_locked(response_id):
                    self.logger.emit(
                        "omni_audio_delta_dropped",
                        callId=self.call_id,
                        responseId=response_id,
                        currentResponseId=self._omni_response_id,
                        bytes=len(audio),
                        collecting=self._omni_barge_collecting,
                        detail="打断恢复期间或旧 response 的音频已丢弃，避免串音。",
                    )
                    return
                generation = self._omni_generation
                self._omni_audio_total += len(audio)
                pcm_8k = _downsample_pcm_24k_to_8k(audio, self._omni_downsample_state)
                if not pcm_8k or self._speech_is_obsolete(generation):
                    return
                if not self._omni_tts_started:
                    self._omni_first_audio_ms = int((time.perf_counter() - self._omni_response_started_at) * 1000)
                    self._omni_tts_started = True
                    if self._omni_barge_forced_response_until > time.monotonic():
                        self._omni_barge_forced_audio_started = True
                    self.logger.emit(
                        "tts_start",
                        callId=self.call_id,
                        reason="omni_response",
                        text="",
                        bytes=len(pcm_8k),
                        synthMs=self._omni_first_audio_ms,
                        firstAudioMs=self._omni_first_audio_ms,
                        voice=self.config.omni_voice,
                        voiceType="omni",
                        model=self.config.omni_model,
                        streaming=True,
                        generation=generation,
                    )
                self._omni_pending_audio += pcm_8k
                pending = self._omni_pending_audio
                next_frame_at = self._omni_next_frame_at
                lag_events = self._omni_playback_lag_events
            while len(pending) >= PCM_FRAME_BYTES:
                if self.stop_event.is_set() or self._speech_is_obsolete(generation):
                    break
                frame = pending[:PCM_FRAME_BYTES]
                pending = pending[PCM_FRAME_BYTES:]
                next_frame_at, lag_events = self._send_audio_frame_at_cadence(
                    frame,
                    next_frame_at,
                    lag_events,
                    "omni_response",
                    generation,
                )
                with self._omni_lock:
                    self._omni_audio_sent += len(frame)
            with self._omni_lock:
                self._omni_pending_audio = pending
                self._omni_next_frame_at = next_frame_at
                self._omni_playback_lag_events = lag_events

    def finish_omni_response(self, response_id: str = "") -> None:
        with self._omni_lock:
            current_response_id = self._omni_response_id
        if response_id and current_response_id and response_id != current_response_id:
            self.logger.emit(
                "omni_stale_response_done",
                callId=self.call_id,
                responseId=response_id,
                currentResponseId=current_response_id,
            )
            return
        with self.playback_lock:
            with self._omni_lock:
                generation = self._omni_generation
                pending = self._omni_pending_audio
                next_frame_at = self._omni_next_frame_at
                lag_events = self._omni_playback_lag_events
            if pending and not self.stop_event.is_set() and not self._speech_is_obsolete(generation):
                padded = pending.ljust(PCM_FRAME_BYTES, b"\x00")
                next_frame_at, lag_events = self._send_audio_frame_at_cadence(
                    padded,
                    next_frame_at,
                    lag_events,
                    "omni_response",
                    generation,
                )
                with self._omni_lock:
                    self._omni_audio_sent += len(pending)
                    self._omni_pending_audio = b""
                    self._omni_next_frame_at = next_frame_at
                    self._omni_playback_lag_events = lag_events
        with self._omni_lock:
            generation = self._omni_generation
            audio_sent = self._omni_audio_sent
            audio_total = self._omni_audio_total
            first_audio_ms = self._omni_first_audio_ms
            reply = "".join(self._omni_reply_parts).strip()
            if not response_id or self._omni_response_id == response_id:
                self._omni_response_id = ""
                self._omni_response_request_active = False
        interrupted = self._speech_is_obsolete(generation)
        self._mark_speech_job_finished()
        if not interrupted and audio_sent == 0 and audio_total == 0:
            fallback_text = reply or OMNI_NO_AUDIO_FALLBACK_TEXT
            with self._omni_lock:
                self._omni_barge_forced_response_until = 0.0
                self._omni_barge_forced_audio_started = False
            self.logger.emit(
                "omni_no_audio_response",
                callId=self.call_id,
                responseId=response_id,
                fallbackText=fallback_text,
                generation=generation,
                detail="Omni 完成了回复但没有返回可播放音频，改用本地实时 TTS 播放兜底句。",
            )
            threading.Thread(
                target=self._speak,
                args=(fallback_text, "omni_no_audio_fallback", generation),
                daemon=True,
            ).start()
            return
        if not interrupted:
            with self._omni_lock:
                self._omni_barge_forced_response_until = 0.0
                self._omni_barge_forced_audio_started = False
        self.logger.emit(
            "tts_interrupted" if interrupted else "tts_done",
            callId=self.call_id,
            reason="omni_response",
            phase="playback",
            sentBytes=audio_sent,
            totalBytes=audio_total,
            firstAudioMs=first_audio_ms,
            generation=generation,
        )
        if not interrupted:
            self._schedule_no_response_hangup("omni_response")


def synthesize_tts_pcm(text: str, config: BridgeConfig) -> bytes:
    runtime_config = get_runtime_ai_config()
    dashscope.api_key = runtime_config.dashscope_api_key
    synthesizer = SpeechSynthesizer(
        model=config.tts_model,
        voice=config.tts_voice_id,
        format=CosyAudioFormat.PCM_8000HZ_MONO_16BIT,
        workspace=config.workspace,
    )
    audio = synthesizer.call(text, timeout_millis=20000)
    if not audio:
        raise RuntimeError("DashScope TTS 未返回音频。")
    return bytes(audio)


def iter_tts_pcm_chunks(text: str, config: BridgeConfig, cached_voice_match: CachedVoiceMatch | None = None):
    if cached_voice_match:
        try:
            yield from iter_cached_voice_pcm_chunks(cached_voice_match, chunk_size=PCM_FRAME_BYTES)
            return
        except Exception:
            pass
    if _is_qwen_realtime_model(config.tts_model):
        yield from stream_qwen_realtime_tts_pcm(text, config)
        return
    yield synthesize_tts_pcm(text, config)


@dataclass
class _PcmDownsampleState:
    leftover: bytes = b""
    history: list[int] = field(default_factory=list)
    phase: int = 0


def stream_qwen_realtime_tts_pcm(text: str, config: BridgeConfig):
    runtime_config = get_runtime_ai_config()
    if not runtime_config.dashscope_api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，不能启动 Qwen 实时 TTS。")

    from dashscope.audio.qwen_tts_realtime import AudioFormat as QwenAudioFormat
    from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback

    class Callback(QwenTtsRealtimeCallback):
        def __init__(self) -> None:
            self.items: queue.Queue[tuple[str, bytes | str | None]] = queue.Queue()
            self.closed = False
            self.received_audio = False

        def on_event(self, response: object) -> None:
            payload = _qwen_event_payload(response)
            event_type = str(payload.get("type") or "")
            if event_type == "response.audio.delta":
                delta = str(payload.get("delta") or "")
                if delta:
                    try:
                        audio = base64.b64decode(delta)
                    except Exception as exc:  # noqa: BLE001
                        self.items.put(("error", f"Qwen 实时 TTS 音频解码失败：{exc}"))
                        return
                    self.received_audio = True
                    self.items.put(("audio", audio))
                return
            if event_type in {"response.done", "session.finished"}:
                self.closed = True
                self.items.put(("done", None))
                return
            if event_type == "error" or payload.get("error"):
                self.items.put(("error", json.dumps(payload, ensure_ascii=False)[:400]))

        def on_close(self, close_status_code: object, close_msg: object) -> None:
            self.closed = True
            self.items.put(("done", None))

    dashscope.api_key = runtime_config.dashscope_api_key
    callback = Callback()
    tts = QwenTtsRealtime(model=config.tts_model, callback=callback, workspace=config.workspace)
    downsample_state = _PcmDownsampleState()
    try:
        tts.connect()
        tts.update_session(
            voice=config.tts_voice_id,
            response_format=QwenAudioFormat.PCM_24000HZ_MONO_16BIT,
            mode="commit",
            language_type=runtime_config.dashscope_system_tts_language_type,
        )
        tts.append_text(text)
        tts.commit()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                item_type, item = callback.items.get(timeout=0.2)
            except queue.Empty:
                if callback.closed:
                    break
                continue
            if item_type == "done":
                break
            if item_type == "error":
                raise RuntimeError(str(item))
            if item_type == "audio" and isinstance(item, bytes):
                pcm_8k = _downsample_pcm_24k_to_8k(item, downsample_state)
                if pcm_8k:
                    yield pcm_8k
        if not callback.received_audio:
            raise RuntimeError("Qwen 实时 TTS 未返回音频。")
    finally:
        try:
            tts.close()
        except Exception:
            pass


def _qwen_event_payload(response: object) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if isinstance(response, str):
        try:
            payload = json.loads(response)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _downsample_pcm_24k_to_8k(chunk: bytes, state: _PcmDownsampleState) -> bytes:
    data = state.leftover + chunk
    usable = (len(data) // 2) * 2
    state.leftover = data[usable:]
    if usable <= 0:
        return b""
    output = bytearray()
    # Qwen realtime emits 24 kHz PCM, while Asterisk AudioSocket expects 8 kHz.
    # A small FIR low-pass before decimation avoids trembly/metallic artifacts
    # caused by dropping or averaging isolated 3-sample groups.
    taps_len = len(_DOWNSAMPLE_TAPS)
    for offset in range(0, usable, 2):
        sample = int.from_bytes(data[offset : offset + 2], "little", signed=True)
        state.history.append(sample)
        if len(state.history) > taps_len:
            del state.history[: len(state.history) - taps_len]
        if state.phase == 0:
            if len(state.history) < taps_len:
                padded_history = [0] * (taps_len - len(state.history)) + state.history
            else:
                padded_history = state.history
            filtered = sum(sample_value * tap for sample_value, tap in zip(reversed(padded_history), _DOWNSAMPLE_TAPS))
            output.extend(max(-32768, min(32767, int(round(filtered)))).to_bytes(2, "little", signed=True))
        state.phase = (state.phase + 1) % _DOWNSAMPLE_FACTOR
    return bytes(output)


def _upsample_pcm_8k_to_16k(chunk: bytes) -> bytes:
    usable = (len(chunk) // 2) * 2
    if usable <= 0:
        return b""
    output = bytearray(usable * 2)
    output.clear()
    for (sample,) in struct.iter_unpack("<h", chunk[:usable]):
        encoded = sample.to_bytes(2, "little", signed=True)
        output.extend(encoded)
        output.extend(encoded)
    return bytes(output)


def build_config(args: argparse.Namespace) -> BridgeConfig:
    runtime_config = get_runtime_ai_config()
    voice = resolve_tts_voice(args.voice_id, args.voice_name)
    workspace = runtime_config.dashscope_workspace.strip() or None
    omni_model = (args.omni_model or runtime_config.dashscope_omni_realtime_model).strip()
    return BridgeConfig(
        bind_host=args.host or settings.asterisk_audio_socket_bind_host,
        port=int(args.port or settings.asterisk_audio_socket_port),
        asr_model=args.asr_model or runtime_config.realtime_asr_model,
        tts_model=args.tts_model or voice.tts_model,
        tts_voice_id=voice.voice_id,
        tts_voice_name=voice.voice_name,
        tts_voice_type=voice.voice_type,
        conversation_mode=(args.conversation_mode or runtime_config.realtime_conversation_mode or "pipeline").strip().lower(),
        omni_model=omni_model,
        omni_url=(args.omni_url or runtime_config.dashscope_omni_realtime_url).strip(),
        omni_voice=_resolve_omni_voice(args.omni_voice, runtime_config, voice, model=omni_model),
        omni_input_transcription_model=(
            args.omni_input_transcription_model or runtime_config.dashscope_omni_input_transcription_model
        ).strip(),
        opening_text=args.opening_text or settings.realtime_call_opening_text,
        log_path=Path(args.log_path or settings.realtime_call_event_log_path).expanduser(),
        workspace=workspace,
        barge_rms_threshold=max(1, settings.realtime_barge_rms_threshold),
        barge_frames=max(1, settings.realtime_barge_frames),
        tts_gain=max(0.1, min(3.0, settings.realtime_tts_gain)),
        opening_grace_seconds=max(0.0, min(5.0, settings.realtime_opening_grace_seconds)),
        debug_audio_capture_enabled=settings.realtime_debug_audio_capture_enabled,
        debug_audio_capture_dir=Path(settings.realtime_debug_audio_capture_dir).expanduser(),
        audio_quality_enabled=settings.realtime_audio_quality_enabled,
        answer_classification_seconds=max(0.5, min(10.0, settings.realtime_answer_classification_seconds)),
        call_screening_hangup_seconds=max(0.0, min(45.0, settings.realtime_call_screening_hangup_seconds)),
        no_response_hangup_seconds=max(0.0, min(90.0, settings.realtime_no_response_hangup_seconds)),
    )


@dataclass(frozen=True)
class ResolvedTtsVoice:
    voice_id: str
    voice_name: str
    voice_type: str
    tts_model: str


def resolve_tts_voice(explicit_voice_id: str | None = None, explicit_voice_name: str | None = None) -> ResolvedTtsVoice:
    runtime_config = get_runtime_ai_config()
    voice_id = (
        explicit_voice_id
        or os.environ.get("AI_ACQ_REALTIME_TTS_VOICE_ID")
        or os.environ.get("REALTIME_TTS_VOICE_ID")
        or runtime_config.realtime_tts_voice_id
        or settings.realtime_tts_voice_id
    ).strip()
    voice_type = (
        os.environ.get("AI_ACQ_REALTIME_TTS_VOICE_TYPE")
        or os.environ.get("REALTIME_TTS_VOICE_TYPE")
        or runtime_config.realtime_tts_voice_type
        or settings.realtime_tts_voice_type
        or "system"
    ).strip().lower()
    voice_name = (explicit_voice_name or runtime_config.realtime_tts_voice_name or settings.realtime_tts_voice_name or "").strip()
    if voice_id:
        if voice_type in {"clone", "cloned", "voice_clone"} or voice_id.lower().startswith("cosyvoice"):
            return ResolvedTtsVoice(
                voice_id=voice_id,
                voice_name=voice_name or voice_id,
                voice_type="clone",
                tts_model=runtime_config.dashscope_tts_model,
            )
        voice_param = _qwen_voice_param(voice_id)
        return ResolvedTtsVoice(
            voice_id=voice_param,
            voice_name=voice_name or _qwen_voice_display_name(voice_param),
            voice_type="system",
            tts_model=runtime_config.dashscope_realtime_tts_model,
        )

    if voice_type in {"clone", "cloned", "voice_clone"}:
        with SessionLocal() as db:
            record = db.scalar(
                select(VoiceCloneRecord)
                .where(VoiceCloneRecord.status == "可用", VoiceCloneRecord.external_voice_id != "")
                .order_by(VoiceCloneRecord.completed_at.desc(), VoiceCloneRecord.created_at.desc())
            )
            if record and record.external_voice_id:
                return ResolvedTtsVoice(
                    voice_id=record.external_voice_id,
                    voice_name=record.cloned_voice_name or record.external_voice_id,
                    voice_type="clone",
                    tts_model=runtime_config.dashscope_tts_model,
                )
        raise RuntimeError("没有可用于实时电话 TTS 的复刻 voice_id，请先在声音档案训练可用音色或设置 REALTIME_TTS_VOICE_ID。")

    default_voice = _qwen_voice_param(runtime_config.dashscope_realtime_tts_voice or "Ethan")
    return ResolvedTtsVoice(
        voice_id=default_voice,
        voice_name=voice_name or _qwen_voice_display_name(default_voice),
        voice_type="system",
        tts_model=runtime_config.dashscope_realtime_tts_model,
    )


def _is_qwen_realtime_model(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith("qwen") and "realtime" in normalized


def _qwen_voice_param(voice_id: str) -> str:
    value = voice_id.strip()
    lower = value.lower()
    if lower.startswith("qwen_tts_"):
        value = value[len("qwen_tts_") :]
        return " ".join(part.capitalize() for part in value.replace("-", "_").split("_") if part)
    return value or "Ethan"


def _is_qwen35_omni_model(model: str) -> bool:
    return "qwen3.5-omni" in model.strip().lower()


def _qwen_omni_default_voice(model: str) -> str:
    return "Tina" if _is_qwen35_omni_model(model) else "Serena"


def _is_supported_omni_voice(model: str, voice_param: str) -> bool:
    if not voice_param:
        return False
    if _is_qwen35_omni_model(model) and voice_param == "Cherry":
        return False
    return True


def _resolve_omni_voice(
    explicit_voice: str | None,
    runtime_config: Any,
    voice: ResolvedTtsVoice,
    *,
    fallback: str = "Serena",
    model: str = "",
) -> str:
    candidates = [
        explicit_voice,
        runtime_config.dashscope_omni_realtime_voice,
        voice.voice_id if voice.voice_type == "system" else "",
        fallback,
    ]
    for candidate in candidates:
        raw_voice = str(candidate or "").strip()
        if not raw_voice:
            continue
        voice_param = _qwen_voice_param(raw_voice)
        if _is_supported_omni_voice(model, voice_param):
            return voice_param
    return _qwen_omni_default_voice(model)


def _qwen_voice_display_name(voice_param: str) -> str:
    names = {
        "Cherry": "芊悦（Cherry）",
        "Serena": "苏瑶（Serena）",
        "Ethan": "晨煦（Ethan）",
        "Chelsie": "千雪（Chelsie）",
        "Moon": "月白（Moon）",
        "Maia": "四月（Maia）",
        "Kai": "凯（Kai）",
        "Sunny": "四川-晴儿（Sunny）",
        "Rocky": "粤语-阿强（Rocky）",
        "Kiki": "粤语-阿清（Kiki）",
    }
    return names.get(voice_param, f"系统音色（{voice_param}）")


def refresh_runtime_voice_config(config: BridgeConfig) -> BridgeConfig:
    runtime_config = get_runtime_ai_config()
    voice = resolve_tts_voice()
    omni_model = (runtime_config.dashscope_omni_realtime_model or config.omni_model).strip()
    return replace(
        config,
        asr_model=runtime_config.realtime_asr_model or config.asr_model,
        tts_model=voice.tts_model,
        tts_voice_id=voice.voice_id,
        tts_voice_name=voice.voice_name,
        tts_voice_type=voice.voice_type,
        conversation_mode=(runtime_config.realtime_conversation_mode or config.conversation_mode or "pipeline").strip().lower(),
        omni_model=omni_model,
        omni_url=(runtime_config.dashscope_omni_realtime_url or config.omni_url).strip(),
        omni_voice=_resolve_omni_voice(
            None,
            runtime_config,
            voice,
            fallback=config.omni_voice or _qwen_omni_default_voice(omni_model),
            model=omni_model,
        ),
        omni_input_transcription_model=(
            runtime_config.dashscope_omni_input_transcription_model or config.omni_input_transcription_model
        ).strip(),
    )


def serve(config: BridgeConfig, stop_event: threading.Event) -> None:
    logger = JsonlEventLogger(config.log_path)
    logger.emit(
        "bridge_start",
        bind=f"{config.bind_host}:{config.port}",
        conversationMode=config.conversation_mode,
        asrModel=config.asr_model,
        ttsModel=config.tts_model,
        omniModel=config.omni_model,
        voice=config.tts_voice_name,
        omniVoice=config.omni_voice,
        voiceType=config.tts_voice_type,
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((config.bind_host, config.port))
        server.listen(8)
        server.settimeout(0.8)
        while not stop_event.is_set():
            try:
                conn, peer = server.accept()
            except TimeoutError:
                continue
            session_config = refresh_runtime_voice_config(config)
            session_cls = OmniAudioSocketCallSession if session_config.conversation_mode == "omni" else AudioSocketCallSession
            logger.emit(
                "bridge_session_config",
                peer=f"{peer[0]}:{peer[1]}",
                conversationMode=session_config.conversation_mode,
                ttsModel=session_config.tts_model,
                voice=session_config.tts_voice_name,
                voiceId=session_config.tts_voice_id,
                voiceType=session_config.tts_voice_type,
                omniVoice=session_config.omni_voice,
            )
            threading.Thread(
                target=session_cls(conn, peer, session_config, logger).run,
                name=f"ai-acq-audiosocket-{peer[0]}:{peer[1]}",
                daemon=True,
            ).start()
    logger.emit("bridge_stop")


def config_summary(config: BridgeConfig) -> dict[str, object]:
    return {
        "bind": f"{config.bind_host}:{config.port}",
        "conversationMode": config.conversation_mode,
        "asrModel": config.asr_model,
        "ttsModel": config.tts_model,
        "omniModel": config.omni_model,
        "omniUrl": config.omni_url,
        "omniVoice": config.omni_voice,
        "omniInputTranscriptionModel": config.omni_input_transcription_model,
        "voice": config.tts_voice_name,
        "voiceType": config.tts_voice_type,
        "voiceConfigured": bool(config.tts_voice_id),
        "dashscopeKeyConfigured": bool(get_runtime_ai_config().dashscope_api_key.strip()),
        "workspaceConfigured": bool(config.workspace),
        "logPath": str(config.log_path),
        "bargeRmsThreshold": config.barge_rms_threshold,
        "bargeFrames": config.barge_frames,
        "ttsGain": config.tts_gain,
        "openingGraceSeconds": config.opening_grace_seconds,
        "debugAudioCaptureEnabled": config.debug_audio_capture_enabled,
        "debugAudioCaptureDir": str(config.debug_audio_capture_dir),
        "audioQualityEnabled": config.audio_quality_enabled,
        "answerClassificationSeconds": config.answer_classification_seconds,
        "callScreeningHangupSeconds": config.call_screening_hangup_seconds,
        "noResponseHangupSeconds": config.no_response_hangup_seconds,
        "voiceCache": voice_cache_status(),
    }


def _read_exact(conn: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        try:
            chunk = conn.recv(size - len(chunks))
        except socket.timeout as exc:
            raise TimeoutError from exc
        if not chunk:
            raise AudioSocketProtocolError("AudioSocket connection closed.")
        chunks.extend(chunk)
    return bytes(chunks)


def _decode_call_id(payload: bytes) -> str:
    if len(payload) == 16:
        return str(uuid.UUID(bytes=payload))
    return payload.decode("utf-8", errors="replace")


def _pcm_rms(payload: bytes) -> int:
    sample_count = len(payload) // 2
    if sample_count <= 0:
        return 0
    total = 0
    for (sample,) in struct.iter_unpack("<h", payload[: sample_count * 2]):
        total += sample * sample
    return int((total / sample_count) ** 0.5)


def _scale_pcm16(payload: bytes, gain: float) -> bytes:
    if not payload or abs(gain - 1.0) < 0.01:
        return payload
    usable = (len(payload) // 2) * 2
    output = bytearray(usable + (len(payload) - usable))
    output.clear()
    for (sample,) in struct.iter_unpack("<h", payload[:usable]):
        scaled = int(sample * gain)
        output.extend(max(-32768, min(32767, scaled)).to_bytes(2, "little", signed=True))
    if usable < len(payload):
        output.extend(payload[usable:])
    return bytes(output)


def _safe_error_text(message: object) -> str:
    try:
        return str(message)
    except Exception as exc:  # noqa: BLE001
        return f"{type(message).__name__}: <unprintable error: {exc}>"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AI ACQ Asterisk AudioSocket realtime bridge.")
    parser.add_argument("--host", help="TCP bind host for Asterisk AudioSocket.")
    parser.add_argument("--port", type=int, help="TCP port for Asterisk AudioSocket.")
    parser.add_argument("--voice-id", help="DashScope CosyVoice voice_id for realtime TTS.")
    parser.add_argument("--voice-name", help="Human label for the realtime TTS voice.")
    parser.add_argument("--asr-model", help="DashScope realtime ASR model.")
    parser.add_argument("--tts-model", help="DashScope realtime TTS model.")
    parser.add_argument("--conversation-mode", choices=["pipeline", "omni"], help="Realtime engine: pipeline or omni.")
    parser.add_argument("--omni-model", help="DashScope Qwen Omni realtime model.")
    parser.add_argument("--omni-url", help="DashScope Qwen Omni realtime WebSocket base URL.")
    parser.add_argument("--omni-voice", help="Qwen Omni realtime voice.")
    parser.add_argument("--omni-input-transcription-model", help="Qwen Omni realtime input transcription model.")
    parser.add_argument("--opening-text", help="Opening sentence spoken after the call is answered.")
    parser.add_argument("--log-path", help="JSONL event log path.")
    parser.add_argument("--check", action="store_true", help="Print non-secret bridge configuration and exit.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stop_event = threading.Event()

    def _stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    config = build_config(args)
    if args.check:
        print(json.dumps(config_summary(config), ensure_ascii=False, indent=2))
        return
    serve(config, stop_event)


if __name__ == "__main__":
    main()
