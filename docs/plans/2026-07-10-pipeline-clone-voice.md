# 方案：外呼切 Pipeline 路线（整通克隆音色）+ 修复中途 media-timeout 挂断

> 交接给 Codex 执行。方案作者：Claude（Cowork）。用户已拍板：整通电话必须用克隆音色，接受 pipeline 路线的取舍。

## 问题定性（已诊断，不要重复排查）

1. **声音只有第一句是克隆音色**：这是架构限制不是 bug。当前走 LiveKit **Omni 实时路线**（`qwen_omni_realtime.py`），DashScope omni realtime 会话只能用内置音色（当前 Cherry），**不支持克隆音色**。只有固定开场用克隆音频放音，AI 一进入动态生成就切回 Cherry。→ 必须改走 **Pipeline 路线（ASR→LLM→克隆TTS）**，整通才能是克隆音色。
2. **说到一半自动挂断**：Codex 上一版报告写"被叫主动挂断"是**误判**。SIP 日志实锤 `reason: media-timeout`（`logs/livekit-sip-native.log` 12:07:16，room `...04b4ccdd...`，接通后约 49 秒媒体流中断触发 timeout）。这是媒体链路 bug，必须一并修。

## 已知事实（直接用，省去摸索）

- 克隆 TTS 代码已存在：`app/tools/realtime_audio_bridge.py` 的 `synthesize_tts_pcm()` / `stream_qwen_realtime_tts_pcm()`，用 `dashscope.audio.tts_v2.SpeechSynthesizer(model="cosyvoice-v3.5-flash", voice=<克隆voice_id>)`，输出 PCM。这是老 AudioSocket bridge 用的，**逻辑可直接复用**。
- 克隆音色已就绪：voice profile `视频号团购招商顾问克隆音色` id `810678b4006e42baa668514056cf8e08`，clone record `fd6bbefcbebe44459806c8d2f4087b99`，模型 `cosyvoice-v3.5-flash`（见上一份验收报告）。
- LiveKit agent 的 `_build_inference_agent_session()`（`livekit_outbound_agent.py` 约 713 行）已是 STT+LLM+TTS pipeline 结构，但 TTS 用的是 `inference.TTS(elevenlabs...)`——**要替换成 CosyVoice 克隆 TTS**。
- 新话术已入库、`realtime_sales_playbook` 已重写（上一任务完成），本任务不改话术内容。
- 链路：本机 livekit-sip（`infra/livekit/sip-native.yaml`）→ 鼎信 8T。**不要退回 Asterisk AudioSocket，不要切回 Docker SIP，不要动网关。**

## 任务

### 1. 写一个 LiveKit 自定义 TTS 插件包克隆音色
新建 `app/tools/livekit_cosyvoice_tts.py`：继承 `livekit.agents.tts.TTS`，内部调用 CosyVoice 流式合成（复用 `realtime_audio_bridge` 里的 SpeechSynthesizer 调用方式），流式吐 PCM 帧给 LiveKit。采样率对齐 LiveKit agent 音频管线（24k/mono）。voice_id 读运行时配置的默认克隆音色。

### 2. 外呼默认走 pipeline + 克隆 TTS
- 改 `livekit_outbound_agent.py`：把外呼默认 `agent_mode` 从 omni 切成 pipeline（新模式名如 `pipeline_clone`），`AgentSession` 用 `STT(中文 ASR) + LLM(现有 DeepSeek/话术模型) + 克隆CosyVoiceTTS + VAD(silero)`。STT 选当前可用的中文识别（LiveKit inference 的多语 STT，或复用阿里云 ASR，哪个延迟低选哪个，在报告里说明选型）。
- 保留 barge-in 打断（客户说话立刻停 TTS）、保留上一任务加的**结束语自动挂机**（`_FAREWELL_PATTERN` 逻辑）。
- 开场白也走同一个克隆 TTS（不再用"固定克隆音频 + omni 动态"两套混合），全程单一音色来源。

### 3. 修 media-timeout
- 根因方向：AI 不说话的空档 / 音频源切换的间隙，SIP 侧一段时间收不到 RTP → 触发 media-timeout。修法：agent 侧在无 TTS 输出时持续推**静音保活帧**保持 RTP 不断流；确保开场与后续回复之间无静默空窗。
- 复核 `sip-native.yaml` 的 `media_timeout` 相关值是否过紧，必要时放宽运行时媒体超时（但根因是保活，不能只靠调大超时糊弄）。
- 验收标准：通话跨过至少一个整分钟、且 AI 连续说话 + 客户沉默 15 秒以上都不掉线。

### 4. 拨测验收（18850625208）
- **整通克隆音色**：开场到结尾每一句都是克隆音色，不再出现中途变声。（这是本任务第一验收项）
- 不中途挂断：跨分钟、含客户沉默段，均不 media-timeout。
- 开场是新手册开场A；问"多少钱"不报价转微信；问"抽成"只说千分之六。
- 结束语后 AI 主动挂机仍生效。
- 报告写 `docs/plans/2026-07-10-pipeline-clone-voice-report.md`，如实写明：STT 选型、TTS 首包延迟实测、转向延迟 P50、media-timeout 是否根治、哪些环节确认是克隆音色。

### 5. 提交推送
代码提交 git（音频仍不进 git）。commit 后 push。

## 红线
- 不退回 Asterisk / AudioSocket；不切回 Docker SIP；不动鼎信网关配置（注册保持禁用）。
- 重启 agent 前杀干净旧 worker，确认只有一组进程再拨测。
- 不报服务价、抽成只讲千分之六、⚠未确认条目不入库（延续上一任务红线）。
- media-timeout 必须靠 RTP 保活根治，不允许只调大超时数值蒙混。
