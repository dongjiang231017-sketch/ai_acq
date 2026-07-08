# 后台对接指南（给负责 backend 的同事）

目标：在现有系统里把 LiveKit 变成第三条线路。前端选 `livekit` 路线时，
后台不走 Asterisk/AMI/AudioSocket，直接转调 PoC 的 dial_api；
意向池、通话记录沿用现有表结构，**不改数据模型**。

改动共 5 步，全部是加法，不动 pipeline/omni 现有逻辑。

## 第1步：拷贝适配层

把本目录的 `livekit_route.py` 拷到 `backend/app/services/livekit_route.py`。
零新依赖（纯标准库）。

## 第2步：schemas 放行新路线值

`backend/app/schemas/task.py:201`，conversationRoute 的校验：

```python
# 原来
pattern="^(pipeline|omni)$"
# 改为
pattern="^(pipeline|omni|livekit)$"
```

## 第3步：test-call 入口加分支

`backend/app/api/outbound.py` 的 `create_telephony_test_call`（154行），
在 `pipeline = build_realtime_pipeline()`（157行）**之前**加：

```python
from app.services.livekit_route import (
    LivekitRouteError,
    dial_livekit_call,
    fetch_livekit_events,
    summarize_livekit_call,
    sync_livekit_intents,
)

requested = (payload.conversation_route or "").strip().lower()
if requested == "livekit":
    try:
        dial = dial_livekit_call(payload.phone, merchant_name="单号真实试拨")
    except LivekitRouteError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    call_id = dial["call_id"]
    # 简单等待接通（最多12s，250ms一轮）；不想同步等就直接返回让前端轮询
    deadline = time.monotonic() + 12.0
    summary = summarize_livekit_call([])
    while time.monotonic() < deadline:
        summary = summarize_livekit_call(fetch_livekit_events(call_id))
        if summary["cellularConfirmed"] or summary["dialFailed"]:
            break
        time.sleep(0.25)
    sync_livekit_intents(call_id, payload.phone)
    return {
        "accepted": not summary["dialFailed"],
        "actionId": call_id,
        "channel": "livekit",
        "requestedRoute": "livekit",
        "actualBridgeRoute": "livekit",
        "effectiveRoute": "livekit",
        "routeFallbackReason": None,
        "routeMatched": True,
        "gatewayStatus": "failed" if summary["dialFailed"] else "dialing",
        "message": summary["dialFailReason"] or "LiveKit 线路已受理拨号",
        "rawPayload": "",
        "verificationStage": (
            "realtime_conversation_confirmed" if summary["conversationConfirmed"]
            else "livekit_dial_failed" if summary["dialFailed"]
            else "livekit_dialing"
        ),
        "cellularConfirmed": summary["cellularConfirmed"],
        "mediaLoopConfirmed": summary["cellularConfirmed"],
        "humanSpeechConfirmed": summary["humanSpeechConfirmed"],
        "aiSpeechConfirmed": summary["aiSpeechConfirmed"],
        "callScreeningDetected": False,
        "bridgeError": summary["dialFailReason"],
        "conversationConfirmed": summary["conversationConfirmed"],
        "acceptanceReady": summary["conversationConfirmed"],
        "acceptanceNote": "LiveKit PoC 线路。",
        "cellularDiagnostic": {"status": "pass" if summary["cellularConfirmed"] else "pending",
                               "stage": "livekit", "title": "LiveKit 线路",
                               "summary": "", "canRetry": True},
        "autoRecovery": None,
    }
```

要点：**livekit 分支完全绕开** `build_realtime_pipeline` / `prepare_realtime_route_for_call`
/ AMI / 409 路线匹配检查——那些都是 Asterisk 体系的概念，对 LiveKit 不适用。

## 第4步：配置项

`backend/app/core/config.py` 的 Settings 加：

```python
livekit_dial_api_url: str = "http://127.0.0.1:8100"
```

`.env.example` 加 `LIVEKIT_DIAL_API_URL=http://127.0.0.1:8100`（PoC 的 dial_api
和后台不同机时改成对应地址）。然后把 `livekit_route.py` 顶部的常量改为读 settings。

## 第5步：前端线路选项（可选，先用 curl 测通再做）

`realtime_outbound.py` 的 `_conversation_route_options`（177行）里追加：

```python
from app.services.livekit_route import livekit_route_available
options.append({
    "value": "livekit",
    "label": "LiveKit 实验线路",
    "modeLabel": "Omni直连（LiveKit媒体层）",
    "available": livekit_route_available(),
    "isActive": False,
    "estimatedLatencyMs": 800,
    "estimatedCostPerMinute": 0.09,
})
```

## 通话中转写/监控

现有前端监控页读的是 AudioSocket bridge 的 JSONL，LiveKit 线路的事件在
PoC 侧（`GET :8100/calls/{call_id}`，含 transcript/turn_latency/挂断）。
PoC 阶段建议直接看这个接口；要并进现有监控页，把 events 映射成
`realtime_live_events` 的格式即可（字段见 `metrics_recorder.py`）。

## 意向池

`sync_livekit_intents` 已接进现有 `record_realtime_intent_signal`：
同一套强意向判定（加微信/发资料）、同一张 IntentCustomer/IntentEvent 表、
按 call_id 幂等去重。通话结束后调一次即可；批量外呼时建议起个后台任务
每 10 秒对进行中的通话轮询调用，避免漏记（旧系统 A7 问题的教训）。

## 验收对比

两条线路各打 50 通同批号码：
- LiveKit 线路：`python scripts/measure_report.py agent/metrics_logs/`
- 现有线路：用飞行记录仪的 turn 延迟数据
对比 P50/P95、接通率、意向捕获数，赢的当主链路。
