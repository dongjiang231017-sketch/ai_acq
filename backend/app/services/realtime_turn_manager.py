from __future__ import annotations

import time
from dataclasses import dataclass

from app.services.realtime_sales_playbook import classify_realtime_call_input
from app.services.realtime_text_normalizer import has_incomplete_realtime_partial, normalize_realtime_sales_text


FAST_PARTIAL_SIGNALS = {
    "identity_handoff",
    "audio_issue",
    "repetition_complaint",
    "direct_answer_only",
    "terminal_close",
    "rejection",
    "call_screening",
}

FAST_PARTIAL_MARKERS = (
    "喂",
    "你谁",
    "谁啊",
    "谁呀",
    "你是谁",
    "哪位",
    "干嘛",
    "做什么",
    "什么事",
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
    "加微信",
    "加我微信",
    "发资料",
    "发案例",
    "发给我",
    "给我发",
)

COMPLETE_QUESTION_MARKERS = (
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
    "发资料",
    "发案例",
    "达不到",
    "保证",
    "多少客户",
    "多少单",
    "到店客流",
)


def compact_customer_text(text: str) -> str:
    return "".join(
        char.lower()
        for char in text
        if char not in " \t\r\n。！？?!，,、.；;：:\"'“”‘’（）()[]【】"
    )


def is_complete_actionable_partial(text: str, *, min_compact_chars: int = 5) -> bool:
    normalized = normalize_realtime_sales_text(text).normalized_text or text
    compact = compact_customer_text(normalized)
    if len(compact) < min_compact_chars:
        return False
    if compact.startswith("你需求什么"):
        return False
    has_question_shape = any(marker in text for marker in ("？", "?")) or compact.endswith(("吗", "呢", "嘛"))
    has_actionable_marker = any(marker in compact for marker in COMPLETE_QUESTION_MARKERS)
    return has_question_shape and has_actionable_marker


def should_fast_commit_partial(text: str) -> bool:
    compact = compact_customer_text(text)
    if compact == "喂":
        return True
    if len(compact) < 2:
        return False
    if has_incomplete_realtime_partial(text):
        return False
    signal = classify_realtime_call_input(text)
    if signal in {"empty", "system_prompt"}:
        return False
    if signal in FAST_PARTIAL_SIGNALS:
        return True
    if any(marker in compact for marker in FAST_PARTIAL_MARKERS):
        return True
    return is_complete_actionable_partial(text)


def stable_partial_delay_seconds(text: str, *, base_seconds: float = 0.45) -> float:
    compact = compact_customer_text(text)
    signal = classify_realtime_call_input(text)
    if signal in FAST_PARTIAL_SIGNALS or any(marker in compact for marker in FAST_PARTIAL_MARKERS):
        return base_seconds
    if is_complete_actionable_partial(text):
        return 0.25
    return base_seconds + 0.35


@dataclass(frozen=True)
class TurnAudioDecision:
    has_voice: bool
    speech_started: bool
    speech_ended: bool
    barge_in: bool
    voice_ms: int
    silence_ms: int
    loud_frames: int
    reason: str


@dataclass(frozen=True)
class TurnEndpointDecision:
    should_commit: bool
    wait_seconds: float
    signal: str
    reason: str


class RealtimeTurnManager:
    """Central turn-taking state for VAD, endpointing, and barge-in.

    This class deliberately owns the timing state that used to be scattered
    through ASR callbacks and playback loops. It makes "when should AI reply"
    testable without placing a real call.
    """

    def __init__(
        self,
        *,
        rms_threshold: int,
        barge_frames: int,
        speech_start_frames: int = 2,
        speech_end_silence_ms: int = 520,
        min_barge_gap_seconds: float = 0.8,
    ) -> None:
        self.rms_threshold = max(1, int(rms_threshold))
        self.barge_frames = max(1, int(barge_frames))
        self.speech_start_frames = max(1, int(speech_start_frames))
        self.speech_end_silence_seconds = max(0.08, speech_end_silence_ms / 1000)
        self.min_barge_gap_seconds = max(0.0, min_barge_gap_seconds)
        self._voice_frames = 0
        self._barge_loud_frames = 0
        self._speech_active = False
        self._speech_started_at = 0.0
        self._last_voice_at = 0.0
        self._last_barge_at = 0.0

    def on_audio_frame(
        self,
        rms: int,
        *,
        now: float | None = None,
        ai_speaking: bool = False,
    ) -> TurnAudioDecision:
        now = now or time.monotonic()
        has_voice = rms >= self.rms_threshold
        speech_started = False
        speech_ended = False
        barge_in = False

        if has_voice:
            self._voice_frames += 1
            self._barge_loud_frames = self._barge_loud_frames + 1 if ai_speaking else 0
            self._last_voice_at = now
            if not self._speech_active and self._voice_frames >= self.speech_start_frames:
                self._speech_active = True
                self._speech_started_at = now
                speech_started = True
        else:
            self._voice_frames = 0
            self._barge_loud_frames = 0
            if self._speech_active and self._last_voice_at and now - self._last_voice_at >= self.speech_end_silence_seconds:
                self._speech_active = False
                speech_ended = True

        if (
            ai_speaking
            and has_voice
            and self._barge_loud_frames >= self.barge_frames
            and now - self._last_barge_at >= self.min_barge_gap_seconds
        ):
            self._last_barge_at = now
            barge_in = True

        voice_ms = int(max(0.0, now - self._speech_started_at) * 1000) if self._speech_started_at else 0
        silence_ms = int(max(0.0, now - self._last_voice_at) * 1000) if self._last_voice_at else 0
        if barge_in:
            reason = "barge_in"
        elif speech_started:
            reason = "speech_started"
        elif speech_ended:
            reason = "speech_ended"
        elif has_voice:
            reason = "voice_continues"
        else:
            reason = "silence"
        return TurnAudioDecision(
            has_voice=has_voice,
            speech_started=speech_started,
            speech_ended=speech_ended,
            barge_in=barge_in,
            voice_ms=voice_ms,
            silence_ms=silence_ms,
            loud_frames=self._barge_loud_frames,
            reason=reason,
        )

    def on_partial_text(self, text: str) -> TurnEndpointDecision:
        signal = classify_realtime_call_input(text)
        if should_fast_commit_partial(text):
            return TurnEndpointDecision(
                should_commit=True,
                wait_seconds=stable_partial_delay_seconds(text),
                signal=signal,
                reason="fast_partial_or_complete_question",
            )
        return TurnEndpointDecision(
            should_commit=False,
            wait_seconds=0.0,
            signal=signal,
            reason="incomplete_or_nonactionable_partial",
        )
