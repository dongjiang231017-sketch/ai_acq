# 给 worker 开发者：必改两处 + 真机验证记录（2026-07-08）

对象：`feature/auth-and-leads` 分支的 `backend/app/tools/livekit_outbound_agent.py`。
整体架构没问题（dispatch-first、worker 建呼、`__main__` 保护、号码规范化都是对的），
但有两处会在真实通话里出问题——**都是今天本地真机踩过并修复验证过的**。

## 必改 1：开场白 `session.say()` 会失败

`livekit_outbound_agent.py` 用 `session.say(opening_text)` 说开场白。
`say()` 需要 TTS 引擎；你的 session 只配了 realtime 模型没配 TTS，会直接抛错，
开场白永远不响（客户接通只听到沉默，几秒就挂——今天真机复现过这个体验）。

改法：

```python
# 不要：
speech = session.say(opening_text, allow_interruptions=True)
# 要：
session.generate_reply(instructions=f"用一句话自然开场，不要多说：{opening_text}")
```

注意 generate_reply 走 DashScope 还有第二个坑，见下条。

## 必改 2：OpenAI 插件直连 DashScope 未经验证，改用验证过的适配器

`_build_openai_realtime_agent_session` 用 `livekit.plugins.openai.realtime.RealtimeModel`
指向 DashScope 兼容端点。今天真机验证发现 DashScope 协议有两个暗坑，
OpenAI 插件不处理：

1. **空上下文的手动 `response.create` 被静默忽略**（连 error 都不回）——
   开场白类主动发言必须先 `conversation.item.create` 塞一条 user 文本再 create。
2. 音频/事件时序细节与 OpenAI 有差异，需要按 DashScope 实际行为处理。

`livekit-poc/agent/qwen_omni_realtime.py` 是**当天真机验证通过**的适配器
（自测录到 AI 出声 4.7s、客户语音逐字识别、打断正常），内含 4 个修复：

| # | 修复 | 不修的症状 |
|---|---|---|
| 1 | generation 创建时立即声明 modalities | 框架把 AI 音频整句憋住不播（AI 无声） |
| 2 | 输出音频按 10ms 分帧 | 框架对大帧静默丢弃（AI 无声） |
| 3 | generate_reply 转 item.create + response.create | 开场白被 DashScope 忽略 |
| 4 | 输入重采样奇数字节截断 | 偶发 struct.error 崩溃 |

改法：把 `qwen_omni_realtime.py` 拷进 backend（或 import livekit-poc 的），
`_build_openai_realtime_agent_session` 里 DashScope 分支换成：

```python
from qwen_omni_realtime import QwenOmniRealtimeModel
return AgentSession(llm=QwenOmniRealtimeModel(
    model=model, api_key=api_key, voice=voice, base_url=base_url,
    instructions=instructions,
))
```

OpenAI 官方端点的分支可以保留原样（插件对 OpenAI 自家协议没问题）。

## 参数与运维要点（同样是今天实测的）

- `VAD_SILENCE_MS`：判停静音毫秒。800 时实测转向延迟 ~1.3s，改 400 目标 ~0.9s，
  <300 会抢客户话。适配器已读这个环境变量。
- 号码必须 `+86` 前缀（你已处理 ✅）。
- worker 必须常驻且被 systemd/supervisor 管理——今天 UC100 测试环境里
  worker 没起时，电话表现为"接通即挂"。别让主线路的 B2 部署问题在新线路重演。
- SIM 风控是真实威胁：今天测试用的 SIM 因同号短呼十来次被移动停机。
  上量前外呼队列必须加：单卡日呼上限、号码去重间隔、多卡轮换。

## 今天真机测试的完整时间线（供排查参考）

1. 先修 run_agent 的 `__main__` 保护（macOS spawn 重复起 worker）→ 你的文件已有 ✅
2. 修编排顺序（原来先拨号等30秒再派agent，客户听半分钟静音）→ 你的架构已对 ✅
3. 修 modalities + 10ms 分帧 → AI 从无声变有声（自测录音验证）
4. 修开场白空上下文问题 → 开场白正常生成
5. 当前唯一遗留：测试 SIM 被风控/未注册（硬件侧，与代码无关）
