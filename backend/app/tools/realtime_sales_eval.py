from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from app.services.realtime_answer_classifier import AnswerClassifier, CallAnswerType, classify_answer_text
from app.services.realtime_audio_quality import RealtimeAudioQualityChain, analyze_pcm16
from app.services.realtime_outbound import _build_reply, _classify_intent
from app.services.realtime_sales_brain import render_sales_reply, score_realtime_events
from app.services.realtime_sales_playbook import (
    build_barge_recovery_instruction,
    build_omni_turn_instruction,
    classify_realtime_call_input,
    extract_human_text_after_system_prompt,
)
from app.services.realtime_sales_state import SalesStateMachine
from app.services.realtime_text_normalizer import has_incomplete_realtime_partial, normalize_realtime_sales_text
from app.tools.realtime_audio_bridge import _adds_significant_business_question, should_commit_stable_asr_partial
from app.tools.realtime_call_replay_eval import evaluate_replay_cases


@dataclass(frozen=True)
class Scenario:
    text: str
    expected_topic: str
    must_include_any: tuple[str, ...]
    forbidden_any: tuple[str, ...] = ()


SCENARIOS = [
    Scenario("你是谁，打电话干嘛？", "identity", ("视频号", "团购", "到店"), ("方便", "十秒", "半分钟", "资料", "加微信")),
    Scenario("你们是什么公司？", "identity", ("视频号", "团购", "到店"), ("方便", "十秒", "半分钟", "资料", "加微信")),
    Scenario("你谁？", "identity", ("视频号", "团购", "到店"), ("方便", "十秒", "半分钟", "资料", "加微信")),
    Scenario("谁？", "identity", ("视频号", "团购", "到店"), ("方便", "十秒", "半分钟", "资料", "加微信")),
    Scenario("你好", "identity", ("视频号", "团购", "到店"), ("方便", "十秒", "二十秒", "半分钟", "资料", "加微信")),
    Scenario("在在。", "identity", ("视频号", "团购", "到店"), ("方便", "十秒", "二十秒", "半分钟", "资料", "加微信")),
    Scenario("这个要不要钱？", "price", ("付费", "收费", "费用", "价格")),
    Scenario("多少钱，别绕。", "price", ("付费", "费用", "价格", "收费"), ("资料", "加微信")),
    Scenario("效果怎么保证？", "guarantee", ("不能", "测试", "数据", "保底")),
    Scenario("你怎么保证能带来客流？", "guarantee", ("不能", "测试", "到店", "数据")),
    Scenario("我已经做美团了，有什么区别？", "channel_difference", ("美团", "视频号", "微信")),
    Scenario("你比美团有什么优势，我为什么要用你？", "advantage", ("优势", "微信", "同城"), ("资料", "加微信")),
    Scenario("跟抖音团购有什么区别？", "channel_difference", ("视频号", "微信", "同城", "私域")),
    Scenario("具体怎么做？", "process", ("套餐", "投放", "流程", "品类")),
    Scenario("怎么合作，流程说一下。", "process", ("套餐", "品类", "投放", "测试")),
    Scenario("你详细说一下。", "process", ("流程", "套餐", "测试"), ("更缺新客", "团购套餐转化")),
    Scenario("同城曝光，你能详细说一下吗？", "exposure_detail", ("同城", "团购券", "门店页", "核销"), ("效果不能", "保底", "更缺新客")),
    Scenario(
        "我要花这个成本，如果达不到那么多客户？",
        "roi_risk",
        ("小", "测试", "达不到", "投入", "成本"),
        ("更缺新客", "团购套餐转化", "微信曝光入口"),
    ),
    Scenario(
        "好，如果我有需求你怎么做？美团你要帮我4G套餐吗？什么意思？",
        "process",
        ("不是4G", "团购套餐", "到店核销"),
        ("美团偏搜索", "私域沉淀", "已有美团也能做补充"),
    ),
    Scenario(
        "用户怎么能看到我的团购券？一定要客户搜索吗？如果客户不搜索，那是不是还要做视频呢？",
        "visibility",
        ("同城推荐", "团购券", "视频", "推荐流", "门店主页"),
        ("更缺新客", "团购套餐转化", "更想提升到店", "费用、效果"),
    ),
    Scenario(
        "新客到店我都说了。",
        "need_confirmed",
        ("新客到店", "套餐", "曝光", "到店数据"),
        ("更缺新客", "团购套餐转化", "效果不能", "保底"),
    ),
    Scenario(
        "你需求什么？你什么新客到店我都说了。",
        "need_confirmed",
        ("新客到店", "套餐", "曝光", "到店数据"),
        ("更缺新客", "团购套餐转化", "效果不能", "保底"),
    ),
    Scenario("不需要资料，直接回答。", "open_need", ("费用", "效果", "流程", "美团"), ("微信", "资料")),
    Scenario("不用加微信，你直接说效果。", "guarantee", ("效果", "测试", "数据", "保底"), ("加微信",)),
    Scenario("别老说发资料，和美团区别是什么？", "channel_difference", ("美团", "视频号", "微信"), ("资料", "加微信")),
    Scenario("你总是重复，能不能说重点？", "quality", ("费用", "效果", "美团", "重点"), ("资料", "加微信")),
    Scenario("你老是说明白，能不能直接说？", "quality", ("不重复", "费用", "效果", "美团"), ("明白", "资料", "加微信")),
    Scenario("我没听清，你说什么？", "quality", ("视频号", "团购", "到店")),
    Scenario("信号断断续续，讲短点。", "quality", ("视频号", "团购", "到店")),
    Scenario("我现在很忙。", "busy", ("晚点", "稍后", "不耽误")),
    Scenario("老板不在，我不负责。", "owner", ("负责", "老板", "店长", "转")),
    Scenario("我的电话你哪里来的？", "source", ("不方便", "不再联系", "业务沟通")),
    Scenario("不需要。", "rejection", ("再见", "不打扰"), ("标记", "不再跟进", "生意顺利")),
    Scenario("不需要了，别联系。", "rejection", ("再见", "不打扰"), ("标记", "不再跟进", "生意顺利")),
    Scenario("现在就这样吧，挂了。", "rejection", ("再见", "不打扰"), ("视频号", "团购", "自我介绍", "方便", "资料", "加微信")),
    Scenario("那你发我看看。", "materials", ("发", "案例", "流程")),
    Scenario("可以，你说一下。", "process", ("套餐", "测试", "品类", "团购")),
    Scenario("这个靠谱吗？", "guarantee", ("测试", "数据", "不能", "保底")),
    Scenario("是不是官方的？", "identity", ("顾问", "服务", "视频号")),
    Scenario("是不是还要另外付费？", "price", ("付费", "费用", "收费")),
    Scenario("基础费用多少钱？", "price", ("付费", "费用", "报价"), ("不合适不建议做", "资料", "加微信")),
    Scenario("和美团比优势在哪里？", "advantage", ("优势", "微信", "同城")),
    Scenario("那你能给我带来多少单？", "guarantee", ("不能", "测试", "数据", "保底")),
    Scenario("你说的我听不懂。", "quality", ("视频号", "团购", "到店")),
    Scenario("什么意思啊？", "quality", ("视频号", "团购", "到店")),
    Scenario("不是问这个，我问费用。", "price", ("付费", "费用", "价格", "收费")),
    Scenario("我的问题你还没解决。", "quality", ("费用", "效果", "美团", "流程")),
    Scenario("说话。", "quality", ("视频号", "团购", "到店"), ("更缺新客", "团购套餐转化")),
    Scenario("我没有提什么问题。", "correction", ("理解错", "猜错", "问我是谁", "来电目的"), ("费用", "效果", "美团", "餐饮", "美业")),
    Scenario("不是费用，你别猜。", "correction", ("理解错", "身份", "来电", "干嘛"), ("费用问题", "餐饮", "美业", "资料", "加微信")),
    Scenario("你先讲重点。", "open_need", ("到店", "曝光", "客流", "费用", "效果")),
    Scenario("我们做餐饮的适合吗？", "open_need", ("餐饮", "套餐", "到店", "品类")),
    Scenario("美业能不能做？", "open_need", ("美业", "套餐", "到店", "品类")),
    Scenario("你不要像机器人一样念稿。", "quality", ("短", "视频号", "到店"), ("明白", "系统", "模型")),
    Scenario("放个屁，别说了。", "rejection", ("再见", "不打扰"), ("标记", "不再跟进", "资料", "加微信")),
]


def evaluate_scenarios() -> dict[str, object]:
    results: list[dict[str, object]] = []
    total = 0
    for scenario in SCENARIOS:
        history: list[dict[str, str]] = []
        intent, _node = _classify_intent(scenario.text)
        fallback = _build_reply(scenario.text, intent, "测试门店")
        reply = render_sales_reply(scenario.text, intent, "测试门店", fallback, list(history))
        checks = _score_scenario(scenario, reply.reply, reply.plan.topic, history)
        total += checks["score"]
        results.append(
            {
                "text": scenario.text,
                "intent": intent,
                "expectedTopic": scenario.expected_topic,
                "topic": reply.plan.topic,
                "emotion": reply.plan.emotion,
                "reply": reply.reply,
                "score": checks["score"],
                "issues": checks["issues"],
            }
        )
    average = round(total / len(SCENARIOS), 1)
    gate_results = _evaluate_live_gates()
    for item in gate_results:
        total += int(item["score"])
    if gate_results:
        average = round(total / (len(SCENARIOS) + len(gate_results)), 1)
    return {
        "scenarioCount": len(SCENARIOS),
        "gateCount": len(gate_results),
        "averageScore": average,
        "passed": average >= 82 and all(int(item["score"]) >= 65 for item in results + gate_results),
        "results": results,
        "gateResults": gate_results,
    }


def _evaluate_live_gates() -> list[dict[str, object]]:
    gates: list[dict[str, object]] = []

    screening_text = "请留下您的姓名和来电原因，我会帮您确认此人是否方便接听。"
    screening_signal = classify_realtime_call_input(screening_text)
    gates.append(
        {
            "text": screening_text,
            "score": 100 if screening_signal == "call_screening" else 35,
            "issues": [] if screening_signal == "call_screening" else [f"signal:{screening_signal}"],
        }
    )
    screening_followup = "谢谢，请不要挂断电话。"
    screening_followup_signal = classify_realtime_call_input(screening_followup)
    gates.append(
        {
            "text": screening_followup,
            "score": 100 if screening_followup_signal == "call_screening" else 35,
            "issues": [] if screening_followup_signal == "call_screening" else [f"signal:{screening_followup_signal}"],
        }
    )
    apple_assistant_text = "我是您的来电助理，为了保护机主，请简短说明来电原因。"
    apple_assistant_signal = classify_realtime_call_input(apple_assistant_text)
    gates.append(
        {
            "text": "phone_assistant_not_human",
            "score": 100 if apple_assistant_signal == "call_screening" else 35,
            "issues": [] if apple_assistant_signal == "call_screening" else [f"signal:{apple_assistant_signal}"],
        }
    )
    smart_answering_text = "机主已开启智能接听，我会帮您转达，请说出来电原因。"
    smart_answering_signal = classify_realtime_call_input(smart_answering_text)
    gates.append(
        {
            "text": "smart_answering_not_human",
            "score": 100 if smart_answering_signal == "call_screening" else 35,
            "issues": [] if smart_answering_signal == "call_screening" else [f"signal:{smart_answering_signal}"],
        }
    )
    screening_reply_instruction = build_omni_turn_instruction(screening_text, "call_screening")
    gates.append(
        {
            "text": "call_screening_reply_no_ai_role",
            "score": 100 if "助手" not in screening_reply_instruction else 45,
            "issues": [] if "助手" not in screening_reply_instruction else ["assistant_role_leak"],
        }
    )

    late_hello_instruction = build_omni_turn_instruction(
        "你好。",
        "human_greeting",
        recent_history=[
            {"role": "assistant", "content": "您好，我是视频号团购业务助手，想确认门店团购曝光合作，麻烦转接负责人，谢谢。"}
        ],
        first_human_after_screening=True,
        last_reply="您好，我是视频号团购业务助手，想确认门店团购曝光合作，麻烦转接负责人，谢谢。",
    )
    late_hello_reply = _extract_forced_reply(late_hello_instruction)
    forbidden = ["方便听", "二十秒", "发资料", "加微信", "转接负责人"]
    gates.append(
        {
            "text": "late_human_hello_after_call_screening",
            "score": 100 if all(word not in late_hello_reply for word in forbidden) else 45,
            "issues": [] if all(word not in late_hello_reply for word in forbidden) else ["late_hello_bad_instruction"],
        }
    )

    identity_instruction = build_omni_turn_instruction("你是谁？", "identity_handoff")
    identity_reply = _extract_forced_reply(identity_instruction)
    identity_forbidden = ["费用", "效果", "美团区别", "发资料", "加微信", "方便听"]
    gates.append(
        {
            "text": "omni_identity_no_push",
            "score": 100 if all(word not in identity_reply for word in identity_forbidden) else 45,
            "issues": [] if all(word not in identity_reply for word in identity_forbidden) else ["identity_push_instruction"],
        }
    )
    repeated_identity_history = [
        {"role": "user", "content": "你是谁？"},
        {"role": "assistant", "content": "我是做视频号团购到店获客的，给您来电是确认门店是否需要微信同城曝光。"},
    ]
    repeated_identity_reply = render_sales_reply(
        "你是谁？",
        "身份确认",
        "测试门店",
        "我是做视频号团购到店获客的，给您来电是确认门店是否需要微信同城曝光。",
        repeated_identity_history,
    ).reply
    gates.append(
        {
            "text": "repeat_identity_uses_new_wording",
            "reply": repeated_identity_reply,
            "score": 100
            if "简单说" in repeated_identity_reply
            and "发资料" not in repeated_identity_reply
            and "加微信" not in repeated_identity_reply
            else 45,
            "issues": []
            if "简单说" in repeated_identity_reply
            and "发资料" not in repeated_identity_reply
            and "加微信" not in repeated_identity_reply
            else ["repeat_identity_not_reworded"],
        }
    )
    omni_repeat_identity_instruction = build_omni_turn_instruction(
        "你是谁？",
        "identity_handoff",
        recent_history=repeated_identity_history,
        last_reply="我是做视频号团购到店获客的，给您来电是确认门店是否需要微信同城曝光。",
    )
    omni_repeat_identity_reply = _extract_forced_reply(omni_repeat_identity_instruction)
    gates.append(
        {
            "text": "omni_repeat_identity_no_replay",
            "score": 100 if "简单说" in omni_repeat_identity_reply else 45,
            "issues": [] if "简单说" in omni_repeat_identity_reply else ["omni_identity_replayed"],
        }
    )
    short_who_signal = classify_realtime_call_input("谁？")
    gates.append(
        {
            "text": "omni_short_who_identity",
            "score": 100 if short_who_signal == "identity_handoff" else 45,
            "issues": [] if short_who_signal == "identity_handoff" else [f"signal:{short_who_signal}"],
        }
    )
    audio_issue_instruction = build_omni_turn_instruction("你说什么？", "audio_issue")
    audio_issue_reply = _extract_forced_reply(audio_issue_instruction)
    audio_issue_forbidden = ["费用", "效果", "美团", "被打断", "系统", "模型"]
    gates.append(
        {
            "text": "omni_audio_issue_short_no_sales_guess",
            "score": 100 if all(word not in audio_issue_reply for word in audio_issue_forbidden) else 45,
            "issues": [] if all(word not in audio_issue_reply for word in audio_issue_forbidden) else ["audio_issue_sales_guess"],
        }
    )
    rejection_instruction = build_omni_turn_instruction("放个屁。", "rejection")
    rejection_reply = _extract_forced_reply(rejection_instruction)
    rejection_forbidden = ["费用", "效果", "美团", "资料", "加微信", "到店客流", "标记", "不再跟进", "生意顺利"]
    gates.append(
        {
            "text": "omni_rejection_closes_no_push",
            "score": 100 if "再见" in rejection_reply and all(word not in rejection_reply for word in rejection_forbidden) else 45,
            "issues": [] if "再见" in rejection_reply and all(word not in rejection_reply for word in rejection_forbidden) else ["rejection_push"],
        }
    )
    terminal_signal = classify_realtime_call_input("现在就这样吧，挂了。")
    gates.append(
        {
            "text": "omni_terminal_close_signal",
            "score": 100 if terminal_signal == "terminal_close" else 35,
            "issues": [] if terminal_signal == "terminal_close" else [f"signal:{terminal_signal}"],
        }
    )
    terminal_instruction = build_omni_turn_instruction("现在就这样吧，挂了。", "terminal_close")
    terminal_reply = _extract_forced_reply(terminal_instruction)
    terminal_forbidden = ["视频号", "团购", "微信", "资料", "负责人", "方便", "标记", "不再跟进"]
    gates.append(
        {
            "text": "omni_terminal_close_short_goodbye",
            "score": 100 if "再见" in terminal_reply and all(word not in terminal_reply for word in terminal_forbidden) else 45,
            "issues": [] if "再见" in terminal_reply and all(word not in terminal_reply for word in terminal_forbidden) else ["terminal_close_push"],
        }
    )
    no_need_signal = classify_realtime_call_input("不需要。")
    gates.append(
        {
            "text": "omni_plain_no_need_closes",
            "score": 100 if no_need_signal == "terminal_close" else 35,
            "issues": [] if no_need_signal == "terminal_close" else [f"signal:{no_need_signal}"],
        }
    )
    correction_instruction = build_omni_turn_instruction("我没有提什么问题。", "human_speech")
    correction_reply = _extract_forced_reply(correction_instruction)
    correction_forbidden = ["费用", "效果", "美团", "餐饮", "美业", "资料", "加微信"]
    gates.append(
        {
            "text": "omni_correction_no_guess",
            "score": 100 if all(word not in correction_reply for word in correction_forbidden) else 45,
            "issues": [] if all(word not in correction_reply for word in correction_forbidden) else ["correction_guessing"],
        }
    )
    fast_barge_score = score_realtime_events(
        [
            {"type": "call_connected", "callId": "gate", "at": "2026-07-01T00:00:00Z"},
            {"type": "human_speech_confirmed", "callId": "gate", "text": "你是谁", "at": "2026-07-01T00:00:01Z"},
            {
                "type": "tts_start",
                "callId": "gate",
                "raw": {"sentBytes": 320, "firstAudioMs": 520},
                "at": "2026-07-01T00:00:01.520Z",
            },
            {"type": "barge_in", "callId": "gate", "at": "2026-07-01T00:00:02Z"},
            {"type": "barge_recovery_ready", "callId": "gate", "at": "2026-07-01T00:00:02.080Z"},
            {
                "type": "omni_response_slow_fallback",
                "callId": "gate",
                "fallbackText": "您刚才是问我身份，还是问具体做什么？",
                "at": "2026-07-01T00:00:02.850Z",
            },
        ],
    )
    turn_metric = next(
        (metric for metric in (fast_barge_score or {}).get("metrics", []) if metric.get("name") == "打断恢复"),
        {},
    )
    gates.append(
        {
            "text": "barge_recovery_scored_within_1s",
            "score": int(turn_metric.get("score") or 0),
            "issues": [] if int(turn_metric.get("score") or 0) >= 85 else ["barge_recovery_too_slow"],
        }
    )
    recovery_instruction = build_barge_recovery_instruction(
        [{"role": "assistant", "content": "费用看套餐和投放，先判断适不适合再报价。"}],
        last_assistant_reply="费用看套餐和投放，先判断适不适合再报价。",
    )
    gates.append(
        {
            "text": "barge_recovery_contextual_no_technical_tone",
            "score": 100
            if "费用看套餐" in recovery_instruction
            and all(word not in recovery_instruction for word in ["被打断", "系统识别", "没听清"])
            else 45,
            "issues": []
            if "费用看套餐" in recovery_instruction
            and all(word not in recovery_instruction for word in ["被打断", "系统识别", "没听清"])
            else ["bad_barge_recovery_instruction"],
        }
    )
    assistant_classifier = AnswerClassifier()
    assistant_type = assistant_classifier.on_asr_text("我是您的来电助理，为了保护机主，请简短说明来电原因。")
    gates.append(
        {
            "text": "answer_classifier_phone_assistant",
            "score": 100 if assistant_type == CallAnswerType.PHONE_ASSISTANT else 35,
            "issues": [] if assistant_type == CallAnswerType.PHONE_ASSISTANT else [f"type:{assistant_type}"],
        }
    )
    smart_assistant_type = classify_answer_text("机主正在忙，我是智能接听助理，请问您有什么事。")
    gates.append(
        {
            "text": "answer_classifier_smart_answering",
            "score": 100 if smart_assistant_type == CallAnswerType.PHONE_ASSISTANT else 35,
            "issues": [] if smart_assistant_type == CallAnswerType.PHONE_ASSISTANT else [f"type:{smart_assistant_type}"],
        }
    )
    voicemail_classifier = AnswerClassifier()
    voicemail_type = voicemail_classifier.on_asr_text("您好，请在提示音后留言，挂断即可。")
    gates.append(
        {
            "text": "answer_classifier_voicemail",
            "score": 100 if voicemail_type == CallAnswerType.VOICEMAIL else 35,
            "issues": [] if voicemail_type == CallAnswerType.VOICEMAIL else [f"type:{voicemail_type}"],
        }
    )
    merged_system_prompt = "您好，用户无法接听，请在提示音后录制留言，录音完成后挂断即可。喂，你好。"
    merged_tail = extract_human_text_after_system_prompt(merged_system_prompt)
    gates.append(
        {
            "text": "system_prompt_with_human_tail_stripped",
            "score": 100 if merged_tail == "喂，你好。" else 35,
            "issues": [] if merged_tail == "喂，你好。" else [f"tail:{merged_tail}"],
        }
    )
    real_mixed_prompt = "尝试联系的用户无法接听，请在提示音后录制留言。录音完成后挂断即可。喂喂，不会说话啊。"
    real_mixed_tail = extract_human_text_after_system_prompt(real_mixed_prompt)
    real_mixed_signal = classify_realtime_call_input(real_mixed_tail)
    real_mixed_answer_type = classify_answer_text(real_mixed_prompt)
    gates.append(
        {
            "text": "real_mixed_system_prompt_keeps_audio_issue",
            "score": 100
            if "不会说话" in real_mixed_tail
            and real_mixed_signal == "audio_issue"
            and real_mixed_answer_type == CallAnswerType.HUMAN
            else 35,
            "reply": real_mixed_tail,
            "issues": []
            if "不会说话" in real_mixed_tail
            and real_mixed_signal == "audio_issue"
            and real_mixed_answer_type == CallAnswerType.HUMAN
            else [f"tail:{real_mixed_tail}", f"signal:{real_mixed_signal}", f"type:{real_mixed_answer_type}"],
        }
    )
    repaired = normalize_realtime_sales_text("好，如果我有需求你怎么做？美团你要帮我4G套餐吗？什么意思？")
    gates.append(
        {
            "text": "sales_asr_repairs_4g_package_to_group_buying",
            "reply": repaired.normalized_text,
            "score": 100 if repaired.has_fix("group_buying_package") and "团购套餐" in repaired.normalized_text else 35,
            "issues": []
            if repaired.has_fix("group_buying_package") and "团购套餐" in repaired.normalized_text
            else [f"normalized:{repaired.normalized_text}", f"fixes:{','.join(repaired.fixes)}"],
        }
    )
    four_g_reply = render_sales_reply(
        "好，如果我有需求你怎么做？美团你要帮我4G套餐吗？什么意思？",
        "合作咨询",
        "测试门店",
        "先看品类，定团购套餐，小范围测试。",
        [],
    ).reply
    gates.append(
        {
            "text": "sales_reply_corrects_4g_package_mishearing",
            "reply": four_g_reply,
            "score": 100
            if "不是4G" in four_g_reply and "团购套餐" in four_g_reply and "美团偏搜索" not in four_g_reply
            else 35,
            "issues": []
            if "不是4G" in four_g_reply and "团购套餐" in four_g_reply and "美团偏搜索" not in four_g_reply
            else ["four_g_not_corrected"],
        }
    )
    gates.append(
        {
            "text": "incomplete_asr_partial_waits_for_more_words",
            "score": 100 if has_incomplete_realtime_partial("好，如果我有需") else 35,
            "issues": [] if has_incomplete_realtime_partial("好，如果我有需") else ["partial_not_marked_incomplete"],
        }
    )
    video_partial = "如果客户不搜索，那是不是我还要做视频呢？我是说我是不是还"
    video_final = "如果客户不搜索，那是不是我还要做视频呢？我是说我是不是还得做视频呢？"
    gates.append(
        {
            "text": "long_video_question_partial_waits_for_final",
            "score": 100 if has_incomplete_realtime_partial(video_partial) and not should_commit_stable_asr_partial(video_partial) else 35,
            "issues": []
            if has_incomplete_realtime_partial(video_partial) and not should_commit_stable_asr_partial(video_partial)
            else ["video_partial_committed_too_early"],
        }
    )
    gates.append(
        {
            "text": "video_question_final_not_deduped_as_old_partial",
            "score": 100 if _adds_significant_business_question(video_final, video_partial) else 35,
            "issues": []
            if _adds_significant_business_question(video_final, video_partial)
            else ["video_final_marked_duplicate"],
        }
    )
    cumulative_need_partial = "你需求什么？你什么新客？"
    gates.append(
        {
            "text": "cumulative_need_partial_waits_for_final",
            "score": 100 if not should_commit_stable_asr_partial(cumulative_need_partial) else 35,
            "issues": [] if not should_commit_stable_asr_partial(cumulative_need_partial) else ["cumulative_partial_committed"],
        }
    )
    complete_detail_partial = "同城曝光，你能详细说一下吗？"
    incomplete_detail_partial = "同城曝光，你能详细说一下吗？我说你能详细"
    gates.append(
        {
            "text": "complete_business_question_partial_commits_fast",
            "score": 100 if should_commit_stable_asr_partial(complete_detail_partial) else 35,
            "issues": [] if should_commit_stable_asr_partial(complete_detail_partial) else ["complete_question_waited_for_final"],
        }
    )
    gates.append(
        {
            "text": "continued_business_question_partial_waits_for_final",
            "score": 100 if has_incomplete_realtime_partial(incomplete_detail_partial) and not should_commit_stable_asr_partial(incomplete_detail_partial) else 35,
            "issues": []
            if has_incomplete_realtime_partial(incomplete_detail_partial) and not should_commit_stable_asr_partial(incomplete_detail_partial)
            else ["continued_question_committed_too_early"],
        }
    )
    roi_partial = "我要花这个成本，如果达不到那么多客户？"
    gates.append(
        {
            "text": "roi_risk_question_partial_commits_fast",
            "score": 100 if should_commit_stable_asr_partial(roi_partial) else 35,
            "issues": [] if should_commit_stable_asr_partial(roi_partial) else ["roi_risk_question_waited_for_final"],
        }
    )
    phone_question_partial = "你打的不就是我手机号吗？"
    gates.append(
        {
            "text": "phone_question_partial_commits_fast",
            "score": 100 if should_commit_stable_asr_partial(phone_question_partial) else 35,
            "issues": [] if should_commit_stable_asr_partial(phone_question_partial) else ["phone_question_waited_for_final"],
        }
    )
    wechat_material_partial = "好，你加我微信，发案例给我看一下。"
    gates.append(
        {
            "text": "wechat_material_partial_commits_fast",
            "score": 100 if should_commit_stable_asr_partial(wechat_material_partial) else 35,
            "issues": [] if should_commit_stable_asr_partial(wechat_material_partial) else ["wechat_material_waited_for_final"],
        }
    )
    repaired_need = normalize_realtime_sales_text("你需求什么？你什么新客到店我都说了。")
    gates.append(
        {
            "text": "sales_asr_removes_repeated_need_question_prefix",
            "reply": repaired_need.normalized_text,
            "score": 100
            if repaired_need.has_fix("repeated_need_question_asr_artifact")
            and repaired_need.normalized_text == "新客到店我都说了。"
            else 35,
            "issues": []
            if repaired_need.has_fix("repeated_need_question_asr_artifact")
            and repaired_need.normalized_text == "新客到店我都说了。"
            else [f"normalized:{repaired_need.normalized_text}", f"fixes:{','.join(repaired_need.fixes)}"],
        }
    )
    ack_history = [{"role": "assistant", "content": "明白。美团偏搜索下单，视频号偏微信同城推荐。"}]
    ack_reply = render_sales_reply(
        "你老是说明白，能不能直接说？",
        "听不清/澄清",
        "测试门店",
        "我换短点说：视频号团购就是帮门店到店获客。",
        ack_history,
    ).reply
    gates.append(
        {
            "text": "sales_reply_suppresses_habitual_mingbai",
            "reply": ack_reply,
            "score": 100 if not ack_reply.startswith("明白") and "明白" not in ack_reply else 35,
            "issues": [] if not ack_reply.startswith("明白") and "明白" not in ack_reply else ["habitual_ack"],
        }
    )
    human_classifier = AnswerClassifier()
    human_type = human_classifier.on_asr_text("你好。")
    gates.append(
        {
            "text": "answer_classifier_human_greeting",
            "score": 100 if human_type == CallAnswerType.HUMAN else 35,
            "issues": [] if human_type == CallAnswerType.HUMAN else [f"type:{human_type}"],
        }
    )
    fsm = SalesStateMachine()
    stage = fsm.update("不用加微信，你直接说效果。", "效果询问", "direct_answer_only")
    constrained = fsm.constrain_reply("可以，我加您微信发资料。")
    gates.append(
        {
            "text": "sales_state_suppresses_push_after_refusal",
            "score": 100 if stage.value == "objection" and "资料" not in constrained and "加微信" not in constrained else 45,
            "issues": [] if stage.value == "objection" and "资料" not in constrained and "加微信" not in constrained else ["push_not_suppressed"],
        }
    )
    quality_chain = RealtimeAudioQualityChain(enabled=True)
    loud = b"".join((32760).to_bytes(2, "little", signed=True) for _ in range(160))
    processed = quality_chain.process(loud)
    raw_stats = analyze_pcm16(loud)
    processed_stats = analyze_pcm16(processed)
    gates.append(
        {
            "text": "audio_quality_limits_clipped_frame",
            "score": 100 if processed_stats.peak <= raw_stats.peak and processed_stats.clipped <= raw_stats.clipped else 45,
            "issues": []
            if processed_stats.peak <= raw_stats.peak and processed_stats.clipped <= raw_stats.clipped
            else ["audio_quality_not_limiting"],
        }
    )
    replay_report = evaluate_replay_cases()
    for result in replay_report["results"]:
        gates.append(
            {
                "text": f"replay_{result['name']}",
                "score": 100 if result["passed"] else 35,
                "issues": list(result["issues"]),
            }
        )
    return gates


def _extract_forced_reply(instruction: str) -> str:
    marker = "只说这句："
    if marker in instruction:
        return instruction.split(marker, 1)[1].split("只用普通话", 1)[0]
    marker = "不要解释系统："
    if marker in instruction:
        return instruction.split(marker, 1)[1].split("禁止主动", 1)[0]
    return instruction


def _score_scenario(scenario: Scenario, reply: str, topic: str, history: list[dict[str, str]]) -> dict[str, object]:
    score = 100
    issues: list[str] = []
    if topic != scenario.expected_topic and not _compatible_topic(topic, scenario.expected_topic):
        score -= 18
        issues.append(f"topic:{topic}")
    if scenario.must_include_any and not any(keyword in reply for keyword in scenario.must_include_any):
        score -= 22
        issues.append("missing_answer_keyword")
    forbidden = [keyword for keyword in scenario.forbidden_any if keyword in reply]
    if forbidden:
        score -= 24
        issues.append("forbidden:" + ",".join(forbidden))
    if len(reply) > 92:
        score -= 12
        issues.append("too_long")
    last_reply = next((turn.get("content", "") for turn in reversed(history) if turn.get("role") == "assistant"), "")
    if _normalize(reply) and _normalize(reply) == _normalize(last_reply):
        score -= 30
        issues.append("repeated_reply")
    if any(word in reply for word in ["系统", "模型", "识别", "被打断"]):
        score -= 20
        issues.append("technical_tone")
    return {"score": max(0, score), "issues": issues}


def _compatible_topic(actual: str, expected: str) -> bool:
    compatible = {
        ("quality", "open_need"),
        ("open_need", "process"),
        ("guarantee", "open_need"),
        ("channel_difference", "open_need"),
    }
    return (actual, expected) in compatible or (expected, actual) in compatible


def _normalize(text: str) -> str:
    return "".join(ch for ch in text if ch.isalnum())


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate realtime outbound sales behavior without placing a call.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    args = parser.parse_args()
    report = evaluate_scenarios()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"scenarios={report['scenarioCount']} gates={report.get('gateCount', 0)} "
            f"average={report['averageScore']} passed={report['passed']}"
        )
        weak = [item for item in report["results"] + report.get("gateResults", []) if int(item["score"]) < 85]
        for item in weak[:8]:
            print(f"- {item['score']} {item['text']} -> {item['reply']} ({','.join(item['issues'])})")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
