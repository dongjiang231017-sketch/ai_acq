# 2026-07-10 Pipeline 克隆音色与 RTP 保活验收报告

> 后续路线变更（2026-07-10 14:29）：所有正式 LiveKit 外呼已强制使用 `qwen3.5-omni-plus-realtime` + `Aiden`，开场和后续回复共用同一 Omni 实时会话，不再播放固定开场录音，历史 `pipeline_clone` metadata 也会被强制归一为 Omni。当前 LiveKit agent Python PID `24702`；原生 LiveKit SIP PID `902` 未变。以下内容是切换前的 Pipeline 实施和验收记录，保留作历史证据。

## 结论

- LiveKit 外呼默认路由已从 Omni 切换为 `pipeline_clone`：DashScope Paraformer ASR -> Qwen/DeepSeek 兼容 LLM -> CosyVoice 克隆 TTS。
- 开场和全部动态回复统一使用 `cosyvoice-v3.5-flash` 及当前默认克隆 voice，不再进入 Omni `Cherry`。
- agent 全程发布 24 kHz mono、20 ms 静音保活轨。真机通话跨过 2 个整分钟统计点，SIP 无 `media-timeout`，最终因被叫发来 BYE 正常结束。
- 真机已验证新手册开场 A、整通 Pipeline 克隆 TTS 及“微信支付手续费千分之六”唯一费率口径。
- “服务多少钱”不报价和结束语主动挂断已在同一 worker 的本地 LiveKit 音频集成房实测通过。修复后针对手机的 3 次复验均在建呼阶段返回 `486 Busy Here`，未进入媒体链路，因此这两项尚缺修复后的手机侧最终听感/挂断复验。

## 实现

- 新增 `app/tools/livekit_cosyvoice_tts.py`：LiveKit streaming TTS 插件，调用 DashScope `SpeechSynthesizer`，输出 24 kHz mono PCM。
- 新增 `app/tools/livekit_dashscope_stt.py`：LiveKit streaming STT 插件，使用 `paraformer-realtime-8k-v2`，适配电话 8 kHz 输入。
- `livekit_outbound_agent.py` 默认构建 Pipeline AgentSession，保留 VAD/barge-in、新话术 instructions、结束语自动挂机和通话落库。
- 开场 A 通过 `session.say()` 走同一 CosyVoice TTS，不再使用“固定克隆开场 + Omni 内置动态音色”混合方案。
- 保活轨会在 job 启动后持续发送静音帧，停止时使用取消和 2 秒回收边界，避免房间删除后 `capture_frame` 卡住 worker 子进程。
- 结束语覆盖“微信见/回头见”等自然说法；客户说“拜拜”时明确要求 LLM 只用含“再见”的一句话结束。
- 收紧加微信意向触发词，避免“微信支付手续费”被误判为已询问加微信。

## 模型与音色

- STT 选型：`paraformer-realtime-8k-v2`。原因是当前 SIP 话音为 PCMU/8 kHz，该模型为电话场景 8 kHz 实时识别，且项目已有 DashScope 凭据和文本归一化逻辑。
- LLM：有 DeepSeek key 时优先使用已配置 DeepSeek；当前运行时无 DeepSeek key，使用 DashScope OpenAI-compatible `qwen-flash`。
- TTS：`cosyvoice-v3.5-flash`，运行时外部 clone voice `cosyvoice-v3.5-flash-jfx197-d0d02e6ee84f41779e00f56c1c94dfae`。
- 内部 voice profile：`视频号团购招商顾问克隆音色`，ID `810678b4006e42baa668514056cf8e08`；clone record `fd6bbefcbebe44459806c8d2f4087b99`。

## 真机验收

目标号码：`188****5208`。

### 成功接通

- action：`lk-53ba6c5a88d448ea8393dfb2f30174b3`；SIP call：`SCL_iLTHaEbxQyfM`。
- 12:54:20 建立媒体，12:56:34 收到被叫 BYE，实际媒体时长约 134 秒。
- 开场为新手册开场 A 原文。开场和后续 8 次动态语音均记录 `provider=dashscope-cosyvoice`、`model=cosyvoice-v3.5-flash`，无 Omni/Cherry 调用。
- 客户问“什么手续费比较高？”，AI 回答“平台侧是微信支付手续费千分之六”，未出现其他费率。
- native SIP 在第 1 分钟和第 2 分钟均输出 `call statistics`，`mixer.tracks=2`（`roomio_audio` + `rtp_keepalive`），全程没有 `media-timeout`。
- 结束原因为 `BYE from remote` / `reason=bye`，不是 `media-timeout`。

### 性能

- 真机 TTS 共 9 次，首包延迟：`772/698/696/678/680/705/720/582/746 ms`，P50 `698 ms`；开场首包 `772 ms`。
- 真机客户停话到 AI 出声共 5 次：`2255/1904/1987/2103/1793 ms`，P50 `1987 ms`。
- 离线 TTS -> ASR 回环：克隆 TTS 生成“您好，请问现在方便说两句吗”，Paraformer 完整识别为同文。

### 本地 LiveKit 音频集成复验

- action `local-pipeline-3d7ebb66ce`：用克隆语音从真实 LiveKit 麦克风轨发问“你们这个服务多少钱”，AI 回答“不同门店要做的内容不一样，电话里直接报一个数不准”并转微信，未报价。
- 同一 action 随后输入“拜拜”，AI 只回“再见”，1.5 秒后记录 `livekit_agent_hangup`，测试客户被 agent 主动移出房间。
- action `local-hangup-03fdea0b95`：在保活回收修复后再次验证道别挂断，出现 `livekit_agent_hangup`、`livekit_agent_shutdown reason=agent_hangup_after_farewell`和 `rtp_keepalive_stopped`，job 日志为正常 `process exiting`。
- action `local-close-final-f19a7c1cf4`：客户主动断开后立即出现 `livekit_agent_session_closed`，随后完成落库和 `rtp_keepalive_stopped`；job 同秒正常 `process exiting`，不再等待框架 15 秒取消窗口。
- 最终 action `local-shutdown-final-a0abf01d26`：“拜拜” -> AI “再见” -> `livekit_agent_hangup` -> 会话关闭 -> job 同秒 `process exiting`，确认主动挂断和子进程清理在最终代码上同时生效。

### 未接通复验

- 修复结束语后的 action `lk-6fc22ecfae2a4a3b95715b9bf2e21e24`、`lk-8378775d7a7f4c1aa849da6304f749b2`、`lk-37be1a7441f24c9e81605479a4f1348b` 均在约 48 秒后返回 SIP `486 Busy Here`。
- 三次均没有接通、没有进入 RTP 媒体，不计为业务验收失败，也不计为通过。

## 运维与红线

- 每次重启前都已退出旧 screen，按模块名补杀，并用 `ps` 确认旧 agent worker 为 0。
- 最终 LiveKit agent Python PID `64793`，仅一组 worker，已注册 `ai-acq-outbound-agent`。
- native `livekit-sip` PID `902` 全程未重启，仍使用 `infra/livekit/sip-native.yaml`；未切 Docker SIP。
- realtime bridge PID `85716` 未切换为外呼主链路；未退回 Asterisk/AudioSocket。
- 未修改鼎信网关任何配置；注册禁用状态保持不变。
- 未修改 `sip-native.yaml` 的超时值；`media-timeout` 修复依靠 RTP 静音保活，不是放宽超时。
- 未新增或修改数据库迁移。本任务没有新音频入 Git。

## 自动验证

- `python -m compileall app migrations`：通过。
- `alembic check`：`No new upgrade operations detected.`
- `pip check`：`No broken requirements found.`
- `python -m app.tools.realtime_sales_eval`：56 个场景、76 个 gate，平均 100.0，通过。
- `npm run build`：通过，Vite 构建完成。
- 离线 Pipeline 探针：TTS 开场首包约 0.73 秒；TTS -> Paraformer 回环识别通过；LLM “多少钱/抽成”口径通过。
- `git diff --check`：通过。
