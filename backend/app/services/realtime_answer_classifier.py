from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum


class CallAnswerType(str, Enum):
    UNKNOWN = "unknown"
    HUMAN = "human"
    PHONE_ASSISTANT = "phone_assistant"
    VOICEMAIL = "voicemail"
    SYSTEM_PROMPT = "system_prompt"
    SILENCE = "silence"


@dataclass
class AnswerDetectionState:
    detected_type: CallAnswerType = CallAnswerType.UNKNOWN
    done: bool = False
    first_audio_at: float = 0.0
    last_voice_at: float = 0.0
    current_segment_start: float = 0.0
    speech_count: int = 0
    total_speech_duration: float = 0.0
    longest_speech: float = 0.0
    audio_segments: list[float] = field(default_factory=list)
    asr_texts: list[str] = field(default_factory=list)
    classified_at: float = 0.0
    reason: str = ""


class AnswerClassifier:
    """Classify the first remote audio as human, phone assistant, voicemail, prompt, or silence."""

    def __init__(
        self,
        *,
        # 【审计A6】默认分类等待上限从 7.0 降到 2.5 秒，减少开场沉默。
        max_wait_seconds: float = 2.5,
        voice_rms_threshold: int = 500,
        long_speech_threshold: float = 2.5,
        short_speech_max: float = 1.5,
        short_speech_fast_seconds: float = 0.9,
    ) -> None:
        self.max_wait_seconds = max_wait_seconds
        self.voice_rms_threshold = voice_rms_threshold
        self.long_speech_threshold = long_speech_threshold
        self.short_speech_max = short_speech_max
        self.short_speech_fast_seconds = short_speech_fast_seconds
        self.state = AnswerDetectionState()

    def on_audio_frame(self, rms: int, now: float | None = None) -> CallAnswerType | None:
        now = now or time.monotonic()
        if self.state.done:
            return self.state.detected_type
        if self.state.first_audio_at == 0.0 and rms > 100:
            self.state.first_audio_at = now
        if rms > self.voice_rms_threshold:
            if self.state.current_segment_start == 0.0:
                self.state.current_segment_start = now
                self.state.speech_count += 1
            self.state.last_voice_at = now
        elif self.state.current_segment_start > 0.0:
            self._close_current_segment()
        return self._try_classify(now)

    def on_asr_text(self, text: str, *, is_final: bool = True) -> CallAnswerType | None:
        clean = " ".join(text.strip().split())
        if not clean or self.state.done:
            return self.state.detected_type if self.state.done else None
        self.state.asr_texts.append(clean)
        signal = classify_answer_text(clean)
        # 【审计A6】ASR partial 出现明确真人问候词（喂/哪位，评审修复4：不再含 你好/您好）即视为 HUMAN，
        # 立即放行开场，不再等待第二个语音段或 final。
        if signal == CallAnswerType.UNKNOWN and not is_final and _has_strong_human_greeting(clean):
            signal = CallAnswerType.HUMAN
        if signal != CallAnswerType.UNKNOWN:
            if (
                signal == CallAnswerType.HUMAN
                and not is_final
                and self.state.speech_count <= 0
                and not _has_strong_human_greeting(clean)
            ):
                return None
            return self._classify(signal, f"asr:{signal.value}")
        return None

    def classify_after_wait(self, now: float | None = None) -> CallAnswerType:
        now = now or time.monotonic()
        if self.state.done:
            return self.state.detected_type
        if self.state.current_segment_start > 0.0:
            self._close_current_segment()
        if self.state.first_audio_at == 0.0:
            return self._classify(CallAnswerType.SILENCE, "timeout:no_remote_audio")
        if self.state.longest_speech > self.long_speech_threshold and self.state.speech_count <= 1:
            return self._classify(CallAnswerType.PHONE_ASSISTANT, "timeout:long_single_speech")
        if self.state.speech_count >= 2 and self.state.longest_speech < self.short_speech_max:
            return self._classify(CallAnswerType.HUMAN, "timeout:multiple_short_speech")
        return self._classify(CallAnswerType.UNKNOWN, "timeout:unclassified_remote_audio")

    def _close_current_segment(self) -> None:
        duration = max(0.0, self.state.last_voice_at - self.state.current_segment_start)
        if duration >= 0.1:
            self.state.audio_segments.append(duration)
            self.state.total_speech_duration += duration
            self.state.longest_speech = max(self.state.longest_speech, duration)
        self.state.current_segment_start = 0.0

    def _try_classify(self, now: float) -> CallAnswerType | None:
        if self.state.first_audio_at == 0.0:
            return None
        current_duration = 0.0
        if self.state.current_segment_start > 0.0 and self.state.last_voice_at:
            current_duration = max(0.0, self.state.last_voice_at - self.state.current_segment_start)
            self.state.longest_speech = max(self.state.longest_speech, current_duration)
        if current_duration > self.long_speech_threshold and self.state.speech_count == 1:
            return self._classify(CallAnswerType.PHONE_ASSISTANT, "audio:long_single_speech")
        if (
            self.state.speech_count >= 2
            and self.state.longest_speech < self.short_speech_max
            and now - self.state.first_audio_at >= min(self.max_wait_seconds, self.short_speech_fast_seconds)
        ):
            return self._classify(CallAnswerType.HUMAN, "audio:multiple_short_speech_fast")
        if now - self.state.first_audio_at >= self.max_wait_seconds:
            return self.classify_after_wait(now)
        return None

    def _classify(self, answer_type: CallAnswerType, reason: str) -> CallAnswerType:
        self.state.detected_type = answer_type
        self.state.done = True
        self.state.reason = reason
        self.state.classified_at = time.monotonic()
        return answer_type


# 【审计A6】partial 里出现任一强真人问候词就立即判 HUMAN 的标记表。
# 评审修复4：去掉"你好/您好"（彩铃"您好，您拨打的用户…"的早期 partial 会误判成真人），
# 只保留"喂/哪位"这两个几乎只有真人会说的标记。
_STRONG_HUMAN_GREETING_MARKERS = ("喂", "哪位")


def _has_strong_human_greeting(text: str) -> bool:
    compact = re.sub(r"[\s。！？?!，,、.]+", "", text.lower())
    if not compact:
        return False
    return any(marker in compact for marker in _STRONG_HUMAN_GREETING_MARKERS)


def classify_answer_text(text: str) -> CallAnswerType:
    clean = " ".join(text.strip().split())
    compact = re.sub(r"[\s。！？?!，,、.]+", "", clean.lower())
    if not compact:
        return CallAnswerType.UNKNOWN
    human_tail = _extract_human_tail_after_prompt(clean)
    if human_tail:
        tail_type = classify_answer_text(human_tail)
        if tail_type in {CallAnswerType.PHONE_ASSISTANT, CallAnswerType.VOICEMAIL, CallAnswerType.SYSTEM_PROMPT}:
            return tail_type
        return CallAnswerType.HUMAN
    if any(
        keyword in clean
        for keyword in [
            "语音信箱",
            "語音信箱",
            "语音留言",
            "语音录音",
            "录制留言",
            "提示音后",
            "提示音後",
            "请在提示音后",
            "挂断即可",
            "若要留言",
            "请留言",
            "請留言",
        ]
    ):
        return CallAnswerType.VOICEMAIL
    if any(
        keyword in clean
        for keyword in [
            "通话已不再录音",
            "开始录音",
            "停止录音",
            "正在录音",
            "暂时无法接听",
            "用户无法接听",
            "无法接通",
            "无法接听",
        ]
    ):
        return CallAnswerType.SYSTEM_PROMPT
    if any(
        keyword in clean
        for keyword in [
            "电话助理",
            "电话秘书",
            "来电助理",
            "来电秘书",
            "接听助理",
            "智能接听",
            "智能助理",
            "ai接听",
            "AI接听",
            "AI 接听",
            "机主已开启",
            "机主正在忙",
            "机主不方便",
            "我是机主",
            "保护机主",
            "我是您的来电助理",
            "正在与来电助理通话",
            "为了保护机主",
            "请简短说明",
            "简短说明来意",
            "确认是否接听",
            "机主接听前",
            "请不要挂断",
            "不要挂断电话",
            "能帮您确认",
            "为您确认",
            "确认此人是否方便",
            "请说明",
            "请先说明",
            "请说出",
            "请先说",
            "来意",
            "来电原因",
            "稍后为您转达",
            "稍后为你转达",
            "为您转达",
            "为你转达",
            "帮您转达",
            "帮你转达",
            "已通知机主",
            "通知机主",
            "帮您记录",
            "帮你记录",
            "请留下您的姓名",
            "留下您的姓名",
        ]
    ):
        return CallAnswerType.PHONE_ASSISTANT
    if len(compact) <= 8 and any(keyword in compact for keyword in ["喂", "你好", "您好", "在", "谁", "哪位", "什么事"]):
        return CallAnswerType.HUMAN
    return CallAnswerType.UNKNOWN


_PROMPT_TAIL_MARKERS = [
    "挂断即可",
    "录音完成后",
    "提示音后录制",
    "请在提示音后",
    "提示音后",
    "请留言",
    "语音信箱",
    "语音留言",
    "用户无法接听",
    "暂时无法接听",
    "无法接听",
    "无法接通",
]


def _extract_human_tail_after_prompt(text: str) -> str:
    best_tail = ""
    best_idx = -1
    for marker in _PROMPT_TAIL_MARKERS:
        idx = text.rfind(marker)
        if idx < 0 or idx < best_idx:
            continue
        tail = text[idx + len(marker) :]
        tail = re.sub(r"^[\s。！？?!，,、.；;：:]+", "", tail).strip()
        if _looks_like_human_tail(tail):
            best_tail = tail
            best_idx = idx
    return best_tail


def _looks_like_human_tail(text: str) -> bool:
    compact = re.sub(r"[\s。！？?!，,、.；;：:]+", "", text)
    if len(compact) < 2:
        return False
    if any(marker in text for marker in _PROMPT_TAIL_MARKERS):
        return False
    return True
