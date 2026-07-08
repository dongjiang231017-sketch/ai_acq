# 实时外呼提速试验

本文记录从当前 Asterisk AudioSocket 链路切到更快实时语音方案的试验顺序。所有命令默认在本机开发环境执行，先做不拨号检查，再做单号试拨，最后才评估替换方案。

## 第一步：先验证现有 Omni 路线

当前优先试现有 `omni` 路线，不直接替换拨号系统。原因是它不需要重接线索、任务、后台和通话记录，只把实时对话从 `ASR -> LLM -> TTS` 分段等待，改成端到端实时语音模型。

本机安全检查：

```bash
cd backend
source .venv/bin/activate
python -m app.tools.realtime_omni_readiness
```

带模型烟测，但不拨真实电话：

```bash
python -m app.tools.realtime_omni_readiness --model-smoke
```

检查 AudioSocket bridge 配置：

```bash
python -m app.tools.realtime_audio_bridge --check --conversation-mode omni
```

如果 bridge 没有监听，启动 Omni bridge：

```bash
python -m app.tools.realtime_audio_bridge --conversation-mode omni
```

后端预检，不拨号：

```bash
curl http://localhost:8001/api/outbound/telephony/health
curl http://localhost:8001/api/outbound/telephony/preflight
curl http://localhost:8001/api/outbound/realtime/pipeline
```

单号真实试拨只在预检全绿后执行：

```bash
curl -X POST http://localhost:8001/api/outbound/telephony/test-call \
  -H 'Content-Type: application/json' \
  -d '{"phone":"测试手机号","conversationRoute":"omni"}'
```

批量开关必须保持关闭，直到多次单号试拨确认接通、首句、打断、复问和挂断都稳定：

```text
ASTERISK_BULK_CALL_ENABLED=false
```

## 当前本机结果

2026-07-07 已完成：

- `REALTIME_CONVERSATION_MODE=omni`
- AudioSocket bridge 正在监听 `127.0.0.1:9019`
- API 后端在线：`http://localhost:8001/api/health`
- Asterisk AMI 可达、已认证、trunk 可达
- 单号试拨开关已开启，批量外呼仍关闭
- Omni 模型烟测通过，首包音频约 `433ms`

下一步需要一个真实测试手机号，用 `/api/outbound/telephony/test-call` 验证电话里的真实轮次速度。

## 第二步：LiveKit PoC

如果现有 Omni + AudioSocket 仍然不像真人外呼，再做 LiveKit PoC。目标不是替换业务系统，而是验证更专业的实时媒体框架是否明显改善 turn-taking。

候选项目：

- https://github.com/livekit/agents
- https://github.com/livekit/sip
- https://github.com/livekit-examples/outbound-caller-python

PoC 验证重点：

1. 配好 LiveKit 项目和 SIP outbound trunk。
2. 跑 `livekit-examples/outbound-caller-python`，先用官方示例打通一通外呼。
3. 把示例里的英文预约话术换成视频号团购销售指令。
4. 对比同一测试手机号、同一问题下的首包语音、打断恢复、复问理解和挂机稳定性。
5. 只有当 LiveKit 明显优于现有 Omni bridge，才进入正式适配。

LiveKit 的关键优势是：Agent 会话可以在拨号前启动，客户一接听就已经有实时听说能力，减少当前自建桥接里“接通后再等待多个子链路”的抖动。
