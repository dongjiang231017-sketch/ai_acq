from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

from app.services.realtime_answer_classifier import CallAnswerType, classify_answer_text
from app.services.realtime_call_state import reduce_realtime_call_events
from app.services.realtime_sales_brain import score_realtime_events
from app.services.realtime_sales_playbook import classify_realtime_call_input, extract_human_text_after_system_prompt


@dataclass(frozen=True)
class ReplayAsrCheck:
    text: str
    expected_signal: str
    expected_answer_type: CallAnswerType
    expected_tail_contains: str = ""


@dataclass(frozen=True)
class ReplayCase:
    name: str
    events: list[dict[str, object]]
    expected_state: str
    required_true_flags: tuple[str, ...] = ()
    expected_turn_taking_status: str | None = None
    expected_current_phase: str | None = None
    max_turn_response_ms: int | None = None
    max_barge_stop_ms: int | None = None
    min_score: int | None = None
    expected_score_status: str | None = None
    expected_last_customer_contains: str = ""
    expected_last_ai_contains: str = ""
    asr_checks: tuple[ReplayAsrCheck, ...] = ()
    note: str = ""
    acceptable_states: tuple[str, ...] = field(default_factory=tuple)


def evaluate_replay_cases() -> dict[str, object]:
    results = [_evaluate_case(case) for case in _replay_cases()]
    return {
        "caseCount": len(results),
        "passed": all(result["passed"] for result in results),
        "results": results,
    }


def _evaluate_case(case: ReplayCase) -> dict[str, object]:
    issues: list[str] = []
    state = reduce_realtime_call_events(case.events).as_dict()
    acceptable_states = set(case.acceptable_states or ()) | {case.expected_state}
    if state["state"] not in acceptable_states:
        issues.append(f"state:{state['state']} expected:{case.expected_state}")
    for flag in case.required_true_flags:
        if not state.get(flag):
            issues.append(f"flag_false:{flag}")
    if case.expected_turn_taking_status and state.get("turnTakingStatus") != case.expected_turn_taking_status:
        issues.append(f"turn:{state.get('turnTakingStatus')} expected:{case.expected_turn_taking_status}")
    if case.expected_current_phase and state.get("currentPhase") != case.expected_current_phase:
        issues.append(f"phase:{state.get('currentPhase')} expected:{case.expected_current_phase}")
    if case.max_turn_response_ms is not None:
        latency = state.get("latestTurnResponseMs")
        if not isinstance(latency, int) or latency > case.max_turn_response_ms:
            issues.append(f"turn_latency:{latency} max:{case.max_turn_response_ms}")
    if case.max_barge_stop_ms is not None:
        latency_breakdown = state.get("latencyBreakdown") if isinstance(state.get("latencyBreakdown"), dict) else {}
        barge_stop = latency_breakdown.get("bargeStopMs") if isinstance(latency_breakdown, dict) else None
        if not isinstance(barge_stop, int) or barge_stop > case.max_barge_stop_ms:
            issues.append(f"barge_stop:{barge_stop} max:{case.max_barge_stop_ms}")
    if case.expected_last_customer_contains and case.expected_last_customer_contains not in str(state.get("lastCustomerText") or ""):
        issues.append(f"last_customer_missing:{case.expected_last_customer_contains}")
    if case.expected_last_ai_contains and case.expected_last_ai_contains not in str(state.get("lastAiReply") or ""):
        issues.append(f"last_ai_missing:{case.expected_last_ai_contains}")
    for check in case.asr_checks:
        issues.extend(_evaluate_asr_check(check))
    score = score_realtime_events(case.events)
    if case.min_score is not None:
        actual_score = int((score or {}).get("score") or 0)
        if actual_score < case.min_score:
            issues.append(f"score:{actual_score} min:{case.min_score}")
    if case.expected_score_status:
        actual_status = str((score or {}).get("status") or "")
        if actual_status != case.expected_score_status:
            issues.append(f"score_status:{actual_status} expected:{case.expected_score_status}")
    return {
        "name": case.name,
        "passed": not issues,
        "state": state,
        "score": score,
        "issues": issues,
        "note": case.note,
    }


def _evaluate_asr_check(check: ReplayAsrCheck) -> list[str]:
    issues: list[str] = []
    tail = extract_human_text_after_system_prompt(check.text)
    signal_text = tail or check.text
    signal = classify_realtime_call_input(signal_text)
    answer_type = classify_answer_text(check.text)
    if signal != check.expected_signal:
        issues.append(f"asr_signal:{signal} expected:{check.expected_signal}")
    if answer_type != check.expected_answer_type:
        issues.append(f"answer_type:{answer_type} expected:{check.expected_answer_type}")
    if check.expected_tail_contains and check.expected_tail_contains not in tail:
        issues.append(f"tail_missing:{check.expected_tail_contains} tail:{tail}")
    return issues


def _replay_cases() -> list[ReplayCase]:
    mixed_prompt = "尝试联系的用户无法接听，请在提示音后录制留言。录音完成后挂断即可。喂喂，不会说话啊。"
    return [
        ReplayCase(
            name="mixed_system_prompt_human_tail_keeps_human_turn",
            note="来自 2026-07-05 失败类型：系统提示和真人尾音合并后不应按纯系统提示忽略。",
            asr_checks=(
                ReplayAsrCheck(
                    text=mixed_prompt,
                    expected_signal="audio_issue",
                    expected_answer_type=CallAnswerType.HUMAN,
                    expected_tail_contains="不会说话",
                ),
            ),
            events=[
                _event("call_connected", "mixed", "2026-07-05T01:00:00.000Z"),
                _event("remote_speech_started", "mixed", "2026-07-05T01:00:00.400Z"),
                _event(
                    "system_prompt_stripped",
                    "mixed",
                    "2026-07-05T01:00:01.100Z",
                    text=mixed_prompt,
                    strippedText="喂喂，不会说话啊。",
                ),
                _event(
                    "answer_classified",
                    "mixed",
                    "2026-07-05T01:00:01.120Z",
                    answerType="human",
                    text="喂喂，不会说话啊。",
                ),
                _event("human_speech_confirmed", "mixed", "2026-07-05T01:00:01.130Z", text="喂喂，不会说话啊。"),
                _event("asr_final", "mixed", "2026-07-05T01:00:01.140Z", text="喂喂，不会说话啊。"),
                _event("llm_reply", "mixed", "2026-07-05T01:00:01.840Z", reply="我在，刚才说的是视频号团购到店获客。"),
                _event("tts_start", "mixed", "2026-07-05T01:00:01.940Z", raw={"sentBytes": 640, "firstAudioMs": 480}),
                _event("tts_done", "mixed", "2026-07-05T01:00:03.200Z", raw={"sentBytes": 640, "firstAudioMs": 480}),
                _event("no_response_hangup_scheduled", "mixed", "2026-07-05T01:00:03.220Z", waitMs=20000),
            ],
            expected_state="waiting_customer_response",
            required_true_flags=("humanSpeechConfirmed", "aiSpeechConfirmed", "autoCloseScheduled"),
            expected_turn_taking_status="pass",
            max_turn_response_ms=1000,
        ),
        ReplayCase(
            name="phone_assistant_waits_then_auto_closes",
            note="电话助理只说明来意，等待转真人；超时必须自动关闭，不能空等两分钟。",
            asr_checks=(
                ReplayAsrCheck(
                    text="机主已开启智能接听，我会帮您转达，请说出来电原因。",
                    expected_signal="call_screening",
                    expected_answer_type=CallAnswerType.PHONE_ASSISTANT,
                ),
            ),
            events=[
                _event("call_connected", "assistant", "2026-07-05T01:10:00.000Z"),
                _event("answer_classified", "assistant", "2026-07-05T01:10:00.650Z", answerType="phone_assistant"),
                _event("call_screening_detected", "assistant", "2026-07-05T01:10:00.680Z", text="机主已开启智能接听，我会帮您转达，请说出来电原因。"),
                _event("llm_reply", "assistant", "2026-07-05T01:10:00.690Z", reply="您好，我这边做视频号团购到店获客，来电想确认门店微信同城曝光合作。"),
                _event("tts_done", "assistant", "2026-07-05T01:10:02.500Z", raw={"sentBytes": 960, "firstAudioMs": 430}),
                _event("call_screening_hangup_scheduled", "assistant", "2026-07-05T01:10:02.520Z", waitMs=12000),
                _event("call_screening_hangup_timeout", "assistant", "2026-07-05T01:10:14.540Z", waitMs=12000),
                _event("call_disconnected", "assistant", "2026-07-05T01:10:14.700Z"),
            ],
            expected_state="call_screening_timeout",
            required_true_flags=("callScreeningDetected", "autoCloseScheduled", "hangupDetected"),
        ),
        ReplayCase(
            name="ai_reply_then_no_customer_response_auto_closes",
            note="来自 2026-07-05 失败类型：AI回复后客户不再说话，必须按无响应关闭。",
            events=[
                _event("call_connected", "idle", "2026-07-05T01:20:00.000Z"),
                _event("human_speech_confirmed", "idle", "2026-07-05T01:20:00.700Z", text="你好。"),
                _event("asr_final", "idle", "2026-07-05T01:20:00.900Z", text="你好。"),
                _event("llm_reply", "idle", "2026-07-05T01:20:01.600Z", reply="您好，我是做视频号团购到店获客的。"),
                _event("tts_start", "idle", "2026-07-05T01:20:01.900Z", raw={"sentBytes": 320, "firstAudioMs": 300}),
                _event("tts_done", "idle", "2026-07-05T01:20:03.100Z", raw={"sentBytes": 800, "firstAudioMs": 510}),
                _event("no_response_hangup_scheduled", "idle", "2026-07-05T01:20:03.120Z", waitMs=20000),
                _event("no_response_hangup_timeout", "idle", "2026-07-05T01:20:23.130Z", waitMs=20000),
                _event("call_disconnected", "idle", "2026-07-05T01:20:23.250Z"),
            ],
            expected_state="no_response_timeout",
            required_true_flags=("humanSpeechConfirmed", "noResponseDetected", "autoCloseScheduled", "hangupDetected"),
            expected_turn_taking_status="pass",
            max_turn_response_ms=1000,
        ),
        ReplayCase(
            name="stable_partial_identity_question_gets_reply_before_final",
            note="来自 2026-07-05 实测：客户问“你谁啊”时 ASR final 迟到，必须先用稳定 partial 触发回复。",
            asr_checks=(
                ReplayAsrCheck(
                    text="那你谁都不说话",
                    expected_signal="identity_handoff",
                    expected_answer_type=CallAnswerType.HUMAN,
                ),
            ),
            events=[
                _event("call_connected", "partial", "2026-07-05T02:05:25.000Z"),
                _event("tts_done", "partial", "2026-07-05T02:05:45.500Z", raw={"sentBytes": 960, "firstAudioMs": 480}),
                _event("no_response_hangup_scheduled", "partial", "2026-07-05T02:05:45.520Z", waitMs=20000),
                _event("asr_partial", "partial", "2026-07-05T02:05:52.400Z", text="那你谁都不"),
                _event(
                    "no_response_hangup_cancelled",
                    "partial",
                    "2026-07-05T02:05:52.401Z",
                    text="那你谁都不",
                ),
                _event("asr_partial_stable", "partial", "2026-07-05T02:05:53.250Z", text="那你谁都不"),
                _event("human_speech_confirmed", "partial", "2026-07-05T02:05:53.260Z", text="那你谁都不"),
                _event("llm_reply", "partial", "2026-07-05T02:05:53.780Z", reply="我是做视频号团购到店获客的，给您来电是确认微信同城曝光需求。"),
                _event("tts_start", "partial", "2026-07-05T02:05:54.050Z", raw={"sentBytes": 640, "firstAudioMs": 420}),
            ],
            expected_state="ai_speaking",
            required_true_flags=("humanSpeechConfirmed", "customerSpeechConfirmed", "aiSpeechConfirmed", "autoCloseScheduled"),
            expected_turn_taking_status="pass",
            max_turn_response_ms=1000,
        ),
        ReplayCase(
            name="voicemail_is_terminal_not_sales_conversation",
            events=[
                _event("call_connected", "voicemail", "2026-07-05T01:30:00.000Z"),
                _event("answer_classified", "voicemail", "2026-07-05T01:30:00.800Z", answerType="voicemail", text="请在提示音后留言，挂断即可。"),
                _event("voicemail_detected", "voicemail", "2026-07-05T01:30:00.810Z", text="请在提示音后留言，挂断即可。"),
                _event("call_disconnected", "voicemail", "2026-07-05T01:30:01.000Z"),
            ],
            expected_state="voicemail",
            required_true_flags=("voicemailDetected", "hangupDetected"),
        ),
        ReplayCase(
            name="silence_after_connect_is_visible",
            events=[
                _event("call_connected", "silence", "2026-07-05T01:40:00.000Z"),
                _event("answer_classified", "silence", "2026-07-05T01:40:01.300Z", answerType="silence"),
                _event("opening_after_remote_silence", "silence", "2026-07-05T01:40:01.310Z", waitMs=1200),
            ],
            expected_state="silence",
            required_true_flags=("silenceDetected",),
        ),
        ReplayCase(
            name="remote_hangup_is_visible",
            events=[
                _event("call_connected", "hangup", "2026-07-05T01:50:00.000Z"),
                _event("hangup_frame", "hangup", "2026-07-05T01:50:04.000Z"),
                _event("call_disconnected", "hangup", "2026-07-05T01:50:04.050Z"),
            ],
            expected_state="hangup",
            required_true_flags=("hangupDetected",),
        ),
        ReplayCase(
            name="customer_rejected_close_is_not_link_error",
            events=[
                _event("call_connected", "closed", "2026-07-05T01:55:00.000Z"),
                _event("human_speech_confirmed", "closed", "2026-07-05T01:55:00.600Z", text="不合适，再见，挂了。"),
                _event("asr_partial_stable", "closed", "2026-07-05T01:55:01.100Z", text="不合适，再见"),
                _event("llm_reply", "closed", "2026-07-05T01:55:01.110Z", reply="好的，不打扰了，再见。"),
                _event("tts_start", "closed", "2026-07-05T01:55:01.420Z", raw={"sentBytes": 640, "firstAudioMs": 330}),
                _event("tts_done", "closed", "2026-07-05T01:55:02.200Z", raw={"sentBytes": 640, "firstAudioMs": 330}),
                _event("call_closing", "closed", "2026-07-05T01:55:02.210Z", reason="customer_rejected"),
                _event("call_closed", "closed", "2026-07-05T01:55:02.220Z", reason="customer_rejected"),
                _event("call_disconnected", "closed", "2026-07-05T01:55:02.260Z"),
            ],
            expected_state="closed",
            required_true_flags=("humanSpeechConfirmed", "aiSpeechConfirmed", "hangupDetected"),
            expected_turn_taking_status="pass",
            max_turn_response_ms=1000,
            min_score=85,
            expected_score_status="pass",
        ),
        ReplayCase(
            name="audiosocket_close_after_human_ai_is_remote_hangup_not_link_error",
            note="来自 2026-07-05 实测：真人和AI已对话后 AudioSocket 关闭，应视为通话结束，不应把监控页打成链路异常。",
            events=[
                _event("call_connected", "socketclose", "2026-07-05T03:48:00.000Z"),
                _event("human_speech_confirmed", "socketclose", "2026-07-05T03:48:01.000Z", text="你好。"),
                _event("asr_final", "socketclose", "2026-07-05T03:48:01.100Z", text="你好。"),
                _event("llm_reply", "socketclose", "2026-07-05T03:48:01.730Z", reply="您好，我是做视频号团购到店获客的。"),
                _event("tts_start", "socketclose", "2026-07-05T03:48:01.900Z", raw={"sentBytes": 640, "firstAudioMs": 430}),
                _event("tts_done", "socketclose", "2026-07-05T03:48:03.000Z", raw={"sentBytes": 640, "firstAudioMs": 430}),
                _event("call_error", "socketclose", "2026-07-05T03:48:30.000Z", error="AudioSocket connection closed."),
                _event("call_disconnected", "socketclose", "2026-07-05T03:48:30.050Z"),
            ],
            expected_state="closed",
            required_true_flags=("humanSpeechConfirmed", "aiSpeechConfirmed", "hangupDetected"),
            expected_turn_taking_status="pass",
            max_turn_response_ms=1000,
            min_score=85,
            expected_score_status="pass",
        ),
        ReplayCase(
            name="long_video_question_final_is_visible_as_latest_customer_text",
            note="来自 2026-07-05 实测：客户长问题最终补出“是不是还得做视频”后，监控态必须保留完整 final。",
            events=[
                _event("call_connected", "videoq", "2026-07-05T03:49:00.000Z"),
                _event("human_speech_confirmed", "videoq", "2026-07-05T03:49:01.000Z", text="我知道你怎么帮我获客。"),
                _event("asr_partial", "videoq", "2026-07-05T03:49:05.000Z", text="如果客户不搜索，那是不是我还要做视频呢？我是说我是不是还"),
                _event(
                    "asr_final",
                    "videoq",
                    "2026-07-05T03:49:06.000Z",
                    text="用户怎么能看到我的团购券？一定要客户搜索吗？如果客户不搜索，那是不是还得做视频呢？",
                ),
                _event(
                    "llm_reply",
                    "videoq",
                    "2026-07-05T03:49:06.690Z",
                    reply="客户不一定主动搜索；视频号有同城推荐和团购券入口，视频只是曝光承载。",
                ),
                _event("tts_start", "videoq", "2026-07-05T03:49:06.900Z", raw={"sentBytes": 800, "firstAudioMs": 440}),
            ],
            expected_state="ai_speaking",
            required_true_flags=("humanSpeechConfirmed", "customerSpeechConfirmed", "aiSpeechConfirmed"),
            expected_last_customer_contains="还得做视频",
            expected_last_ai_contains="团购券入口",
            expected_turn_taking_status="pass",
            max_turn_response_ms=1000,
        ),
        ReplayCase(
            name="cumulative_need_partial_waits_for_final_need_confirmed",
            note="来自 2026-07-05 实测：同一 ASR 分段反复带出旧前缀“你需求什么”时，不应按多轮客户发言重复追问。",
            events=[
                _event("call_connected", "needpartial", "2026-07-05T06:18:35.000Z"),
                _event("human_speech_confirmed", "needpartial", "2026-07-05T06:18:36.000Z", text="你需求什么？"),
                _event("asr_partial", "needpartial", "2026-07-05T06:18:41.946Z", text="你需求什么？"),
                _event("asr_partial", "needpartial", "2026-07-05T06:18:52.047Z", text="你需求什么？你什么新客？"),
                _event("asr_partial", "needpartial", "2026-07-05T06:19:01.725Z", text="你需求什么？你什么新客到店我都说了"),
                _event("asr_final", "needpartial", "2026-07-05T06:19:02.000Z", text="新客到店我都说了。"),
                _event(
                    "llm_reply",
                    "needpartial",
                    "2026-07-05T06:19:02.560Z",
                    reply="对，您刚才说的是新客到店。那就按到店目标走：先做团购套餐和同城曝光，小范围测到店数据。",
                ),
                _event("tts_start", "needpartial", "2026-07-05T06:19:02.780Z", raw={"sentBytes": 800, "firstAudioMs": 420}),
            ],
            expected_state="ai_speaking",
            required_true_flags=("humanSpeechConfirmed", "customerSpeechConfirmed", "aiSpeechConfirmed"),
            expected_last_customer_contains="新客到店",
            expected_last_ai_contains="按到店目标",
            expected_turn_taking_status="pass",
            max_turn_response_ms=1000,
        ),
        ReplayCase(
            name="incomplete_partial_waits_for_final_without_reply",
            note="客户问题还没说完时，只能显示等待 final，不能抢答旧主题。",
            events=[
                _event("call_connected", "waitfinal", "2026-07-05T07:00:00.000Z"),
                _event("remote_speech_started", "waitfinal", "2026-07-05T07:00:00.300Z", rms=3100),
                _event("asr_partial", "waitfinal", "2026-07-05T07:00:00.800Z", text="我是说我是不是还"),
                _event(
                    "turn_waiting_final",
                    "waitfinal",
                    "2026-07-05T07:00:00.810Z",
                    text="我是说我是不是还",
                    reason="incomplete_or_nonactionable_partial",
                ),
            ],
            expected_state="customer_speaking",
            required_true_flags=("customerSpeechConfirmed",),
            expected_current_phase="waiting_asr_final",
            expected_turn_taking_status="unknown",
        ),
        ReplayCase(
            name="complete_business_partial_gets_first_audio_under_one_second",
            note="完整可答的问题不必等慢 final，应该从 stable partial 到首个声音在 1 秒内。",
            events=[
                _event("call_connected", "fastpartial", "2026-07-05T07:05:00.000Z"),
                _event("human_speech_confirmed", "fastpartial", "2026-07-05T07:05:00.300Z", text="同城曝光，你能详细说一下吗？"),
                _event("asr_partial", "fastpartial", "2026-07-05T07:05:00.520Z", text="同城曝光，你能详细说一下吗？"),
                _event("turn_endpoint_candidate", "fastpartial", "2026-07-05T07:05:00.530Z", waitMs=450),
                _event("asr_partial_stable", "fastpartial", "2026-07-05T07:05:00.980Z", text="同城曝光，你能详细说一下吗？", waitMs=450),
                _event("turn_reply_preparing", "fastpartial", "2026-07-05T07:05:00.990Z", text="同城曝光，你能详细说一下吗？"),
                _event("turn_llm_start", "fastpartial", "2026-07-05T07:05:01.000Z", text="同城曝光，你能详细说一下吗？"),
                _event("llm_reply", "fastpartial", "2026-07-05T07:05:01.250Z", reply="同城曝光就是让附近的人刷到门店套餐。", latencyMs=240),
                _event("tts_start", "fastpartial", "2026-07-05T07:05:01.620Z", raw={"sentBytes": 640, "firstAudioMs": 360}),
            ],
            expected_state="ai_speaking",
            required_true_flags=("humanSpeechConfirmed", "customerSpeechConfirmed", "aiSpeechConfirmed"),
            expected_current_phase="ai_speaking",
            expected_turn_taking_status="pass",
            max_turn_response_ms=1000,
        ),
        ReplayCase(
            name="barge_in_stops_ai_and_returns_to_listening_fast",
            note="客户打断时必须可见停嘴耗时，不能继续播旧答案。",
            events=[
                _event("call_connected", "bargefast", "2026-07-05T07:10:00.000Z"),
                _event("human_speech_confirmed", "bargefast", "2026-07-05T07:10:00.400Z", text="多少钱？"),
                _event("asr_final", "bargefast", "2026-07-05T07:10:00.700Z", text="多少钱？"),
                _event("llm_reply", "bargefast", "2026-07-05T07:10:01.100Z", reply="先看门店适不适合。", latencyMs=300),
                _event("tts_start", "bargefast", "2026-07-05T07:10:01.260Z", raw={"sentBytes": 640, "firstAudioMs": 350}),
                _event("barge_in", "bargefast", "2026-07-05T07:10:01.560Z"),
                _event("barge_playback_drained", "bargefast", "2026-07-05T07:10:01.640Z", waitMs=80),
                _event("barge_recovery_ready", "bargefast", "2026-07-05T07:10:01.650Z", waitMs=90),
                _event("asr_partial", "bargefast", "2026-07-05T07:10:01.900Z", text="别绕，直接说费用"),
                _event("turn_waiting_final", "bargefast", "2026-07-05T07:10:01.910Z", text="别绕，直接说费用"),
            ],
            expected_state="customer_speaking",
            required_true_flags=("humanSpeechConfirmed", "interruptionDetected", "aiSpeechConfirmed"),
            expected_current_phase="waiting_asr_final",
            max_barge_stop_ms=200,
        ),
        ReplayCase(
            name="omni_barge_duplicate_transcript_still_recovers_reply",
            note="来自 2026-07-05 实测：AI刚开口被打断后，只收到重复“喂。”也不能沉默，必须 watchdog 恢复回复。",
            events=[
                _event("call_connected", "bardupe", "2026-07-05T11:35:40.000Z"),
                _event("human_speech_confirmed", "bardupe", "2026-07-05T11:35:43.090Z", text="喂"),
                _event("asr_final", "bardupe", "2026-07-05T11:35:43.390Z", text="喂"),
                _event("turn_reply_preparing", "bardupe", "2026-07-05T11:35:43.400Z", text="喂"),
                _event("turn_llm_start", "bardupe", "2026-07-05T11:35:43.410Z", text="喂"),
                _event("tts_start", "bardupe", "2026-07-05T11:35:44.236Z", raw={"sentBytes": 640, "firstAudioMs": 447}),
                _event("barge_in", "bardupe", "2026-07-05T11:35:45.222Z"),
                _event("barge_recovery_ready", "bardupe", "2026-07-05T11:35:45.223Z", waitMs=1),
                _event("tts_interrupted", "bardupe", "2026-07-05T11:35:45.260Z", raw={"sentBytes": 12800}),
                _event("customer_turn_duplicate_ignored", "bardupe", "2026-07-05T11:35:45.425Z", text="喂。"),
                _event("barge_turn_committed", "bardupe", "2026-07-05T11:35:46.275Z", elapsedMs=1050, silenceMs=850),
                _event("llm_reply", "bardupe", "2026-07-05T11:35:46.540Z", reply="您好，我在。刚才说的是视频号团购到店获客。"),
                _event("tts_start", "bardupe", "2026-07-05T11:35:46.780Z", raw={"sentBytes": 640, "firstAudioMs": 430}),
            ],
            expected_state="ai_speaking",
            required_true_flags=("humanSpeechConfirmed", "interruptionDetected", "aiSpeechConfirmed"),
            expected_current_phase="ai_speaking",
            expected_turn_taking_status="pass",
            max_barge_stop_ms=200,
            max_turn_response_ms=1000,
            min_score=85,
        ),
        ReplayCase(
            name="turn_taking_fast_after_customer_final",
            events=[
                _event("call_connected", "turnfast", "2026-07-05T02:00:00.000Z"),
                _event("human_speech_confirmed", "turnfast", "2026-07-05T02:00:00.500Z", text="多少钱？"),
                _event("tts_start", "turnfast", "2026-07-05T02:00:00.700Z", raw={"sentBytes": 640, "firstAudioMs": 430}),
                _event("barge_in", "turnfast", "2026-07-05T02:00:01.000Z"),
                _event("tts_interrupted", "turnfast", "2026-07-05T02:00:01.060Z", raw={"sentBytes": 320}),
                _event("barge_recovery_ready", "turnfast", "2026-07-05T02:00:01.090Z"),
                _event("asr_final", "turnfast", "2026-07-05T02:00:01.500Z", text="多少钱，别绕。"),
                _event("llm_reply", "turnfast", "2026-07-05T02:00:02.230Z", reply="要收费，先看门店适不适合。"),
                _event("tts_start", "turnfast", "2026-07-05T02:00:02.360Z", raw={"sentBytes": 640, "firstAudioMs": 430}),
            ],
            expected_state="ai_speaking",
            required_true_flags=("humanSpeechConfirmed", "interruptionDetected", "aiSpeechConfirmed"),
            expected_turn_taking_status="pass",
            max_turn_response_ms=1000,
        ),
        ReplayCase(
            name="turn_taking_slow_is_detected",
            events=[
                _event("call_connected", "turnslow", "2026-07-05T02:10:00.000Z"),
                _event("human_speech_confirmed", "turnslow", "2026-07-05T02:10:00.500Z", text="你是谁？"),
                _event("asr_final", "turnslow", "2026-07-05T02:10:01.000Z", text="你是谁？"),
                _event("llm_reply", "turnslow", "2026-07-05T02:10:02.700Z", reply="我是做视频号团购到店获客的。"),
                _event("tts_start", "turnslow", "2026-07-05T02:10:02.850Z", raw={"sentBytes": 640, "firstAudioMs": 430}),
            ],
            expected_state="ai_speaking",
            required_true_flags=("humanSpeechConfirmed", "aiSpeechConfirmed"),
            expected_turn_taking_status="fail",
        ),
    ]


def _event(event_type: str, call_id: str, at: str, **fields: object) -> dict[str, object]:
    payload = {"type": event_type, "callId": call_id, "at": at, **fields}
    raw = fields.get("raw")
    if isinstance(raw, dict):
        payload["raw"] = {**payload, **raw}
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay realtime failed-call fixtures without placing a call.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    args = parser.parse_args()
    report = evaluate_replay_cases()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"replayCases={report['caseCount']} passed={report['passed']}")
        for item in report["results"]:
            if item["passed"]:
                continue
            print(f"- {item['name']}: {','.join(item['issues'])}")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
