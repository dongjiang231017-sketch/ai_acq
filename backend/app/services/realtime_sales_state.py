from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum


class SalesStage(str, Enum):
    OPENING = "opening"
    SITUATION = "situation"
    PROBLEM = "problem"
    IMPLICATION = "implication"
    NEED = "need"
    SOLUTION = "solution"
    OBJECTION = "objection"
    CLOSING = "closing"
    ENDING = "ending"


@dataclass
class SalesState:
    current_stage: SalesStage = SalesStage.OPENING
    previous_stage: SalesStage = SalesStage.OPENING
    stage_entered_at: float = field(default_factory=time.monotonic)
    turns_in_stage: int = 0
    total_turns: int = 0
    merchant_type: str = ""
    current_channel: str = ""
    pain_points: list[str] = field(default_factory=list)
    objections_raised: list[str] = field(default_factory=list)
    interest_signals: list[str] = field(default_factory=list)
    wechat_offered: bool = False
    materials_offered: bool = False
    push_forbidden: bool = False
    rejection_count: int = 0
    last_assistant_reply: str = ""


class SalesStateMachine:
    """Small state layer that guides both local pipeline replies and Omni prompts."""

    def __init__(self) -> None:
        self.state = SalesState()

    def update(self, customer_text: str, intent: str, signal: str = "") -> SalesStage:
        clean = customer_text.strip()
        self.state.total_turns += 1
        self.state.turns_in_stage += 1
        self._extract_context(clean)
        if _has_any(clean, ["不需要资料", "不用资料", "不要资料", "不用加微信", "不加微信", "直接回答", "说重点", "别推"]):
            self.state.push_forbidden = True
        if signal in {"terminal_close", "rejection"} or intent in {"明确拒绝", "礼貌结束"}:
            self.state.rejection_count += 1
            self._transition(SalesStage.ENDING)
            return self.state.current_stage
        if intent == "稍后联系":
            self._transition(SalesStage.ENDING)
            return self.state.current_stage
        if signal in {"identity_handoff", "human_greeting"} or intent == "身份确认":
            if self.state.current_stage == SalesStage.OPENING:
                self._transition(SalesStage.SITUATION)
            return self.state.current_stage
        if signal in {"direct_answer_only", "repetition_complaint"}:
            self.state.push_forbidden = True
            self._transition(SalesStage.OBJECTION)
            return self.state.current_stage
        if intent in {"价格异议", "效果询问", "已有渠道", "来源/隐私"}:
            self._record_objection(intent)
            self._transition(SalesStage.OBJECTION)
            return self.state.current_stage
        if intent == "加微信/发资料":
            self.state.wechat_offered = self.state.wechat_offered or "微信" in clean
            self.state.materials_offered = self.state.materials_offered or _has_any(clean, ["资料", "案例", "发我", "发给我"])
            self._transition(SalesStage.CLOSING)
            return self.state.current_stage
        if intent == "合作咨询" or _has_any(clean, ["怎么做", "怎么合作", "流程", "具体讲"]):
            self._transition(SalesStage.SOLUTION)
            return self.state.current_stage
        if self.state.current_stage == SalesStage.SITUATION and self.state.turns_in_stage >= 2:
            self._transition(SalesStage.PROBLEM)
        elif self.state.current_stage == SalesStage.PROBLEM and self.state.turns_in_stage >= 2:
            self._transition(SalesStage.NEED)
        elif self.state.current_stage == SalesStage.NEED:
            self._transition(SalesStage.SOLUTION)
        elif self.state.current_stage == SalesStage.SOLUTION and self.state.turns_in_stage >= 2 and not self.state.push_forbidden:
            self._transition(SalesStage.CLOSING)
        return self.state.current_stage

    def get_stage_instruction(self) -> str:
        strategy = self._strategy()
        context = []
        if self.state.merchant_type:
            context.append(f"商家类型={self.state.merchant_type}")
        if self.state.current_channel:
            context.append(f"已有渠道={self.state.current_channel}")
        if self.state.objections_raised:
            context.append(f"已提异议={','.join(dict.fromkeys(self.state.objections_raised))}")
        if self.state.push_forbidden:
            context.append("客户已拒绝资料/微信推进")
        if self.state.last_assistant_reply:
            context.append(f"上一句AI={self.state.last_assistant_reply[:60]}")
        return (
            f"销售状态：阶段={self.state.current_stage.value}；目标={strategy['goal']}；"
            f"限制=最多{strategy['max_sentences']}句，{strategy['rules']}；"
            f"上下文={'；'.join(context) if context else '无'}。"
            "必须先回答客户当前问题；不要复读上一句；不要说被打断、系统、模型、识别。"
        )

    def constrain_reply(self, reply: str) -> str:
        clean = reply.strip()
        if self.should_end_call():
            return "好的，不打扰了，再见。"
        if self.state.push_forbidden and _has_any(clean, ["加微信", "发资料", "发案例", "留个微信"]):
            return "明白，不继续推。您直接问费用、效果或流程，我按问题答。"
        if self.state.last_assistant_reply and _normalize(clean) == _normalize(self.state.last_assistant_reply):
            return "我换个角度说：视频号团购补的是微信同城和私域到店。"
        return clean

    def record_assistant_reply(self, reply: str) -> None:
        self.state.last_assistant_reply = reply.strip()
        if _has_any(reply, ["加微信", "留个微信"]):
            self.state.wechat_offered = True
        if _has_any(reply, ["发资料", "发案例", "发流程"]):
            self.state.materials_offered = True

    def should_end_call(self) -> bool:
        return self.state.current_stage == SalesStage.ENDING or self.state.rejection_count >= 2

    def _transition(self, next_stage: SalesStage) -> None:
        if next_stage == self.state.current_stage:
            return
        self.state.previous_stage = self.state.current_stage
        self.state.current_stage = next_stage
        self.state.stage_entered_at = time.monotonic()
        self.state.turns_in_stage = 0

    def _extract_context(self, text: str) -> None:
        for merchant_type in ["餐饮", "美业", "美容", "美发", "娱乐", "休闲", "健身", "零售"]:
            if merchant_type in text:
                self.state.merchant_type = merchant_type
        for channel in ["美团", "抖音", "大众点评", "小红书", "高德"]:
            if channel in text:
                self.state.current_channel = channel
        if _has_any(text, ["没客", "客流", "到店", "曝光", "转化", "成本"]):
            self.state.pain_points.append(text[:28])
        if _has_any(text, ["可以", "了解", "说一下", "看看", "怎么合作", "发我"]):
            self.state.interest_signals.append(text[:28])

    def _record_objection(self, intent: str) -> None:
        mapping = {
            "价格异议": "price",
            "效果询问": "effect",
            "已有渠道": "existing_channel",
            "来源/隐私": "privacy",
        }
        self.state.objections_raised.append(mapping.get(intent, intent))

    def _strategy(self) -> dict[str, str | int]:
        strategies: dict[SalesStage, dict[str, str | int]] = {
            SalesStage.OPENING: {"goal": "一句话说明身份和来电目的", "rules": "不要长开场", "max_sentences": 2},
            SalesStage.SITUATION: {"goal": "了解当前渠道或是否听得清", "rules": "只问一个问题", "max_sentences": 2},
            SalesStage.PROBLEM: {"goal": "发现到店/曝光/成本痛点", "rules": "不要急推资料", "max_sentences": 2},
            SalesStage.IMPLICATION: {"goal": "轻轻放大痛点影响", "rules": "语气关心", "max_sentences": 2},
            SalesStage.NEED: {"goal": "确认客户更关心费用/效果/流程", "rules": "给选择题", "max_sentences": 2},
            SalesStage.SOLUTION: {"goal": "针对问题给方案", "rules": "结合品类和已有渠道", "max_sentences": 2},
            SalesStage.OBJECTION: {"goal": "先承接异议再短答", "rules": "不硬推，不复读", "max_sentences": 2},
            SalesStage.CLOSING: {"goal": "只在客户愿意时推进下一步", "rules": "客户拒绝资料就停止推进", "max_sentences": 2},
            SalesStage.ENDING: {"goal": "礼貌结束", "rules": "只说不打扰再见", "max_sentences": 1},
        }
        return strategies[self.state.current_stage]


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _normalize(text: str) -> str:
    return re.sub(r"[\s。！？?!，,、.；;]+", "", text)
