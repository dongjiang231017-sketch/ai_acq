from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum

from app.services.realtime_text_normalizer import normalize_realtime_sales_text


SOLUTION_INTRO_REPLY = "我先多讲一句：我们先看门店品类和客单价，设计可核销团购套餐，再小范围测曝光、咨询和到店数据。"
SOFT_WECHAT_OFFER_REPLY = "落地流程就是诊断品类、设计套餐、上架测试和复盘。如果您愿意，我可以微信发一份同品类案例和门店方案。"


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
    solution_intro_count: int = 0
    wechat_offered: bool = False
    wechat_add_asked: bool = False
    wechat_phone_confirm_pending: bool = False
    wechat_id_pending: bool = False
    wechat_confirmed: bool = False
    wechat_identifier: str = ""
    wechat_ask_count: int = 0
    materials_offered: bool = False
    push_forbidden: bool = False
    rejection_count: int = 0
    last_assistant_reply: str = ""


@dataclass(frozen=True)
class WechatClosingResult:
    reply: str
    action: str
    record: bool = False
    wechat_id: str = ""
    wechat_is_phone: bool = False
    summary: str = ""


class SalesStateMachine:
    """Small state layer that guides both local pipeline replies and Omni prompts."""

    def __init__(self) -> None:
        self.state = SalesState()

    def update(self, customer_text: str, intent: str, signal: str = "") -> SalesStage:
        clean = normalize_realtime_sales_text(customer_text).normalized_text
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
        if signal in {"identity_handoff", "human_greeting", "continue_prompt"} or intent == "身份确认":
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
        if self.state.wechat_phone_confirm_pending:
            context.append("正在确认当前手机号是否为微信")
        if self.state.wechat_id_pending:
            context.append("正在等待客户提供微信号")
        if self.state.wechat_confirmed:
            context.append("客户已同意加微信")
        return (
            f"销售状态：阶段={self.state.current_stage.value}；目标={strategy['goal']}；"
            f"限制=最多{strategy['max_sentences']}句，{strategy['rules']}；"
            f"上下文={'；'.join(context) if context else '无'}。"
            "必须先回答客户当前问题；不要复读上一句；不要说被打断、系统、模型、识别。"
            "客户有兴趣后先补充一轮价值和执行流程，不能马上确认微信；"
            "只有已讲过方案内容，或客户明确要求发资料/加微信时，才问一次“方便加个微信吗”；客户同意后先确认当前手机号是不是微信；"
            "如果不是，再问微信号并记录，之后不要重复索要。"
        )

    def constrain_reply(self, reply: str) -> str:
        clean = reply.strip()
        if self.should_end_call():
            return "好的，不打扰了，再见。"
        if self.state.push_forbidden and _has_any(clean, ["加微信", "发资料", "发案例", "留个微信"]):
            return "不继续推。您直接问费用、效果或流程，我按问题答。"
        if self._repeats_wechat_materials_pitch(clean):
            if not self.state.wechat_confirmed and not self.state.wechat_phone_confirm_pending and not self.state.wechat_id_pending:
                self.state.wechat_phone_confirm_pending = True
                return "可以，我加您微信，把案例和门店方案发您。这个手机号就是您的微信吗？"
            return "我不重复刚才那句。您直接问费用、效果或流程，我按问题答。"
        if self.state.solution_intro_count == 0 and _has_any(clean, ["加微信", "加个微信", "微信上", "微信聊", "发资料", "发案例", "门店方案发您"]):
            return SOLUTION_INTRO_REPLY
        if self.state.last_assistant_reply and _normalize(clean) == _normalize(self.state.last_assistant_reply):
            return "我换个角度说：视频号团购补的是微信同城和私域到店。"
        return _suppress_habitual_ack(clean, self.state.last_assistant_reply)

    def record_assistant_reply(self, reply: str) -> None:
        self.state.last_assistant_reply = reply.strip()
        if _has_any(reply, ["加微信", "加个微信", "留个微信", "微信上", "微信聊"]):
            self.state.wechat_offered = True
            self.state.wechat_add_asked = True
            self.state.wechat_ask_count += 1
        if _has_any(
            reply,
            [
                "手机号就是",
                "手机号是",
                "这个手机号",
                "当前手机号",
                "这个号",
                "这号",
                "当前号码",
                "号码就是",
                "号码是",
            ],
        ) and "微信" in reply:
            self.state.wechat_add_asked = True
            self.state.wechat_offered = True
            self.state.wechat_phone_confirm_pending = True
            self.state.wechat_id_pending = False
        if _has_any(
            reply,
            [
                "微信号是哪个",
                "您的微信是哪个",
                "你微信是哪个",
                "微信号多少",
                "微信号是什么",
                "您的微信号",
                "请报一下微信号",
                "告诉我微信号",
            ],
        ):
            self.state.wechat_id_pending = True
            self.state.wechat_phone_confirm_pending = False
        if _has_any(reply, ["发资料", "发案例", "发流程"]):
            self.state.materials_offered = True
        if _looks_like_solution_intro(reply):
            self.state.solution_intro_count += 1

    def handle_wechat_closing_turn(self, customer_text: str, intent: str, *, phone: str = "") -> WechatClosingResult | None:
        clean = normalize_realtime_sales_text(customer_text).normalized_text
        compact = _compact(clean)
        phone_digits = _digits(phone)
        extracted_wechat_id = extract_wechat_id(
            clean,
            current_phone=phone_digits,
            allow_bare=self.state.wechat_id_pending or self.state.wechat_phone_confirm_pending,
        )
        if not clean:
            return None
        if self.state.wechat_confirmed:
            if _is_affirmative_confirmation(compact) or _has_any(compact, ["微信", "手机号", "这个号"]):
                return WechatClosingResult(reply=_wechat_confirmed_reply(), action="wechat_already_confirmed")
            return None
        if _declines_wechat(clean):
            was_wechat_flow = self.state.wechat_add_asked or self.state.wechat_phone_confirm_pending or self.state.wechat_id_pending
            self.state.push_forbidden = True
            self.state.wechat_phone_confirm_pending = False
            self.state.wechat_id_pending = False
            if was_wechat_flow:
                return WechatClosingResult(reply="好的，那先不加微信。您直接问费用、效果或流程，我按问题答。", action="wechat_declined")
            return None
        if self.state.wechat_id_pending:
            if extracted_wechat_id:
                self._mark_wechat_confirmed(extracted_wechat_id)
                return WechatClosingResult(
                    reply=_wechat_confirmed_reply(use_phone=False),
                    action="wechat_id_captured",
                    record=True,
                    wechat_id=extracted_wechat_id,
                    wechat_is_phone=_digits(extracted_wechat_id) == phone_digits and bool(phone_digits),
                    summary=f"客户同意加微信，提供微信号：{extracted_wechat_id}",
                )
            if _is_negative_confirmation(compact):
                self.state.push_forbidden = True
                self.state.wechat_id_pending = False
                return WechatClosingResult(reply="好的，那先不加微信，我不多占您电话时间。", action="wechat_id_declined")
            return None
        if self.state.wechat_phone_confirm_pending:
            if extracted_wechat_id:
                self._mark_wechat_confirmed(extracted_wechat_id)
                return WechatClosingResult(
                    reply=_wechat_confirmed_reply(use_phone=False),
                    action="wechat_id_captured",
                    record=True,
                    wechat_id=extracted_wechat_id,
                    wechat_is_phone=_digits(extracted_wechat_id) == phone_digits and bool(phone_digits),
                    summary=f"客户同意加微信，提供微信号：{extracted_wechat_id}",
                )
            if _is_affirmative_confirmation(compact):
                if phone_digits:
                    self._mark_wechat_confirmed(phone_digits)
                    return WechatClosingResult(
                        reply=_wechat_confirmed_reply(),
                        action="phone_is_wechat_confirmed",
                        record=True,
                        wechat_id=phone_digits,
                        wechat_is_phone=True,
                        summary=f"客户同意加微信，确认当前手机号就是微信：{phone_digits}",
                    )
                self.state.wechat_phone_confirm_pending = False
                self.state.wechat_id_pending = True
                return WechatClosingResult(reply="可以，那您的微信号是哪个？我记一下，稍后添加您。", action="ask_wechat_id")
            if _looks_like_incomplete_phone_wechat_confirmation(compact):
                return WechatClosingResult(reply="", action="wait_phone_confirmation")
            if _is_negative_confirmation(compact):
                self.state.wechat_phone_confirm_pending = False
                self.state.wechat_id_pending = True
                return WechatClosingResult(reply="那您的微信号是哪个？我记一下，稍后添加您。", action="ask_wechat_id")
            return WechatClosingResult(reply="这个手机号就是您的微信吗？", action="repeat_phone_confirm")
        if _customer_accepts_wechat(clean, intent, self.state.last_assistant_reply):
            self.state.wechat_add_asked = True
            self.state.wechat_offered = True
            if extracted_wechat_id:
                self._mark_wechat_confirmed(extracted_wechat_id)
                return WechatClosingResult(
                    reply=_wechat_confirmed_reply(use_phone=False),
                    action="wechat_id_captured",
                    record=True,
                    wechat_id=extracted_wechat_id,
                    wechat_is_phone=_digits(extracted_wechat_id) == phone_digits and bool(phone_digits),
                    summary=f"客户同意加微信，提供微信号：{extracted_wechat_id}",
                )
            if phone_digits:
                self.state.wechat_phone_confirm_pending = True
                return WechatClosingResult(reply="可以，我加您微信，把案例和门店方案发您。这个手机号就是您的微信吗？", action="ask_phone_is_wechat")
            self.state.wechat_id_pending = True
            return WechatClosingResult(reply="可以，那您的微信号是哪个？我记一下，稍后添加您。", action="ask_wechat_id")
        if (
            self.state.solution_intro_count > 0
            and not self.state.wechat_add_asked
            and not self.state.push_forbidden
            and not _explicit_wechat_or_materials_request(clean, intent)
            and _is_interest_or_continue_signal(compact)
        ):
            self.state.wechat_offered = True
            return WechatClosingResult(reply=SOFT_WECHAT_OFFER_REPLY, action="offer_wechat_after_intro")
        if (
            self.state.solution_intro_count == 0
            and not self.state.push_forbidden
            and not _explicit_wechat_or_materials_request(clean, intent)
            and _is_interest_or_continue_signal(compact)
        ):
            return WechatClosingResult(reply=SOLUTION_INTRO_REPLY, action="explain_before_wechat")
        return None

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

    def _mark_wechat_confirmed(self, wechat_id: str) -> None:
        self.state.wechat_confirmed = True
        self.state.wechat_identifier = wechat_id
        self.state.wechat_phone_confirm_pending = False
        self.state.wechat_id_pending = False
        self.state.wechat_offered = True
        self.state.wechat_add_asked = True

    def _repeats_wechat_materials_pitch(self, reply: str) -> bool:
        if not self.state.last_assistant_reply:
            return False
        current = _normalize(reply)
        previous = _normalize(self.state.last_assistant_reply)
        pitch_words = ["发资料", "发案例", "微信发", "加微信", "微信上", "看完再沟通", "不多占"]
        if current == previous:
            return any(word in reply for word in pitch_words)
        current_hits = sum(1 for word in pitch_words if word in reply)
        previous_hits = sum(1 for word in pitch_words if word in self.state.last_assistant_reply)
        return current_hits >= 2 and previous_hits >= 2

    def _strategy(self) -> dict[str, str | int]:
        strategies: dict[SalesStage, dict[str, str | int]] = {
            SalesStage.OPENING: {"goal": "一句话说明身份和来电目的", "rules": "不要长开场", "max_sentences": 2},
            SalesStage.SITUATION: {"goal": "了解当前渠道或是否听得清", "rules": "只问一个问题", "max_sentences": 2},
            SalesStage.PROBLEM: {"goal": "发现到店/曝光/成本痛点", "rules": "不要急推资料", "max_sentences": 2},
            SalesStage.IMPLICATION: {"goal": "轻轻放大痛点影响", "rules": "语气关心", "max_sentences": 2},
            SalesStage.NEED: {"goal": "确认客户更关心费用/效果/流程", "rules": "给选择题", "max_sentences": 2},
            SalesStage.SOLUTION: {"goal": "针对问题给方案", "rules": "结合品类和已有渠道", "max_sentences": 2},
            SalesStage.OBJECTION: {"goal": "先承接异议再短答", "rules": "不硬推，不复读", "max_sentences": 2},
            SalesStage.CLOSING: {
                "goal": "确认意向并完成微信下一步",
                "rules": "确认客户已听过方案内容后，再问是否方便加微信；同意后确认手机号是不是微信；不是就问微信号",
                "max_sentences": 2,
            },
            SalesStage.ENDING: {"goal": "礼貌结束", "rules": "只说不打扰再见", "max_sentences": 1},
        }
        return strategies[self.state.current_stage]


def _has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _normalize(text: str) -> str:
    return re.sub(r"[\s。！？?!，,、.；;]+", "", text)


def _compact(text: str) -> str:
    return re.sub(r"[\s。！？?!，,、.；;：:\"'“”‘’（）()]+", "", text.lower())


def _digits(text: str) -> str:
    return "".join(char for char in str(text or "") if char.isdigit())


def extract_wechat_id(text: str, *, current_phone: str = "", allow_bare: bool = False) -> str:
    clean = " ".join(str(text or "").strip().split())
    if not clean:
        return ""
    ascii_joined = re.sub(r"(?<=[A-Za-z0-9_-])\s+(?=[A-Za-z0-9_-])", "", clean)
    marker_patterns = [
        r"(?:微信号|微信|vx|VX|v信|V信|weixin|WeChat|wechat)[是叫:： ]*([A-Za-z][A-Za-z0-9_-]{4,31})",
        r"(?:微信号|微信|vx|VX|v信|V信|weixin|WeChat|wechat)[是叫:： ]*((?:1[3-9]\d{9})|(?:\d{6,20}))",
    ]
    for pattern in marker_patterns:
        match = re.search(pattern, ascii_joined)
        if match:
            candidate = match.group(1).strip("，,。.;；:： ")
            if _looks_like_wechat_id(candidate, current_phone=current_phone):
                return candidate[:80]
    phones = re.findall(r"1[3-9]\d{9}", ascii_joined)
    for phone in phones:
        if phone != current_phone:
            return phone
    if any(keyword in ascii_joined for keyword in ["不是", "另一个", "微信号", "微信是", "我的微信"]):
        tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{4,31}\b", ascii_joined)
        for token in tokens:
            if _looks_like_wechat_id(token, current_phone=current_phone):
                return token[:80]
    if allow_bare:
        # 已进入“请报微信号”状态后，客户通常只念 ID，不会再说
        # “我的微信号是”。仅在该状态放开纯 ID/纯数字提取，避免平时误记。
        bare = ascii_joined.strip("，,。.;；:： ")
        if _looks_like_wechat_id(bare, current_phone=current_phone):
            return bare[:80]
        if re.fullmatch(r"\d{6,20}", bare) and bare != current_phone:
            return bare[:80]
    return ""


def _looks_like_wechat_id(candidate: str, *, current_phone: str = "") -> bool:
    value = candidate.strip()
    if not value:
        return False
    if value == current_phone:
        return True
    if re.fullmatch(r"1[3-9]\d{9}", value):
        return True
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{4,31}", value))


def _declines_wechat(text: str) -> bool:
    return _has_any(
        _compact(text),
        ["不加微信", "不用加微信", "不要加微信", "不需要加微信", "别加微信", "先不加", "不用发资料", "不需要资料", "不要资料"],
    )


def _is_affirmative_confirmation(compact: str) -> bool:
    if compact in {
        "是",
        "是的",
        "是啊",
        "对",
        "对的",
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
        "没错",
        "没问题",
        "可以加",
        "发吧",
        "加吧",
        "你加吧",
        "对就是",
        "是我的微信",
        "是我微信",
    }:
        return True
    if _has_any(compact, ["就是手机号", "就是这个号", "就是这个号码", "是这个号", "是这个号码", "微信就是手机号", "手机号就是微信"]):
        return True
    if _has_any(
        compact,
        [
            "微信就是手机号",
            "微信是手机号",
            "手机号就是微信",
            "手机号码就是微信",
            "手机号是微信",
            "手机号码是微信",
        ],
    ):
        return True
    phone_markers = ["手机号", "手机号码", "这手机号", "这个手机号", "这个号", "这个号码"]
    confirmation_tails = [
        "是我微信",
        "是我的微信",
        "就是我微信",
        "就是我的微信",
        "就我微信",
        "就我的微信",
        "是我微",
        "是我的微",
        "就是我微",
        "就是我的微",
        "就我微",
        "就我的微",
    ]
    return any(
        f"{phone_marker}{tail}" in compact
        for phone_marker in phone_markers
        for tail in confirmation_tails
    )


def _looks_like_incomplete_phone_wechat_confirmation(compact: str) -> bool:
    if _is_affirmative_confirmation(compact) or _is_negative_confirmation(compact):
        return False
    phone_markers = ["手机号", "手机号码", "这手机号", "这个手机号", "这个号", "这个号码"]
    return any(marker in compact for marker in phone_markers) and _has_any(compact, ["是", "就", "就是", "我"])


def _is_negative_confirmation(compact: str) -> bool:
    return _has_any(compact, ["不是", "不是这个", "不是这个号", "不是这个号码", "微信不是", "不是手机号", "另一个", "其他微信", "换一个"])


def _customer_accepts_wechat(text: str, intent: str, last_reply: str) -> bool:
    compact = _compact(text)
    if _declines_wechat(text):
        return False
    explicit_request = _explicit_wechat_or_materials_request(text, intent)
    if explicit_request and "短信" not in compact:
        return True
    asked_wechat = _has_any(last_reply, ["加微信", "加个微信", "微信上", "微信聊", "微信发", "发资料", "发案例", "发流程", "门店方案发您"])
    if not asked_wechat:
        return False
    if _is_affirmative_confirmation(compact):
        return True
    if _is_interest_to_learn_signal(compact):
        return True
    return _has_any(compact, ["可以加", "你加我", "发我", "发给我", "给我发", "发过来", "发一下", "加一下", "微信聊", "微信发"])


def _explicit_wechat_or_materials_request(text: str, intent: str) -> bool:
    compact = _compact(text)
    return intent == "加微信/发资料" and _has_any(
        compact,
        ["微信", "资料", "案例", "发我", "发给我", "给我发", "发过来", "发来", "发一下", "加一下"],
    )


def _is_interest_to_learn_signal(compact: str) -> bool:
    if not compact:
        return False
    if _has_any(compact, ["不需要", "不用", "不要", "没兴趣", "不感兴趣", "别发", "不加"]):
        return False
    if compact in {
        "要",
        "需要",
        "需要的",
        "要的",
        "想要",
        "有需要",
        "有",
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
    direct_markers = [
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
    ]
    if _has_any(compact, direct_markers):
        return True
    return ("想" in compact or "要" in compact or "可以" in compact) and _has_any(
        compact,
        ["做", "了解", "看看", "资料", "案例", "合作", "开通", "办理"],
    )


def _is_interest_or_continue_signal(compact: str) -> bool:
    if _is_interest_to_learn_signal(compact):
        return True
    return compact in {
        "你说",
        "您说",
        "你讲",
        "您讲",
        "继续",
        "说你说",
        "说您说",
        "方便你说",
        "方便您说",
        "方便说",
        "你方便说",
        "您方便说",
        "那你说",
        "那您说",
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
    }


def _wechat_confirmed_reply(*, use_phone: bool = True) -> str:
    target = "这个手机号" if use_phone else "这个微信"
    return f"好的，我稍后按{target}添加您，您通过后我把案例和门店方案发过去。感谢您接听，先不多打扰了。"


def _looks_like_solution_intro(reply: str) -> bool:
    compact = _compact(reply)
    if not compact:
        return False
    return _has_any(
        compact,
        [
            "视频号团购",
            "同城曝光",
            "团购套餐",
            "到店数据",
            "客单价",
            "核销套餐",
            "小范围测试",
            "小范围测",
            "咨询和到店",
            "微信生态",
            "私域",
        ],
    )


def _suppress_habitual_ack(reply: str, last_reply: str) -> str:
    if not reply.startswith(("明白", "好的", "好，", "好。", "可以，")):
        return reply
    stripped = re.sub(r"^(明白|好的|好|可以)[，。,.\s]+", "", reply, count=1)
    if len(stripped) >= 6 and (_normalize(last_reply).startswith(("明白", "好的", "好", "可以")) or reply.startswith("明白")):
        return stripped
    return reply
