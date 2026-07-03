# UC100 实体电话卡外呼接入准备

这份文档用于 UC100 或其他 SIP/VoLTE/GSM 语音网关到货前后的开发联调和客户交付。UC100 只是当前实测档案，不是产品交付的唯一设备。当前系统已经有模拟电话网关、Redis 外呼队列、外呼 worker、通话网关字段、Asterisk AMI 健康检查、单号试拨接口、真实 originate 适配器、云端 Asterisk 注册验收面板，以及设备未识卡前可用的实时语音管线模拟接口。

## 交付标准

生产交付优先使用云端接入：

```text
实体 SIM 卡
  -> 现场语音网关（UC100 或其他 SIP/VoLTE/GSM 网关）
  -> SIP REGISTER 到云端 Asterisk
  -> FastAPI / Redis worker / 实时媒体桥
  -> ASR / 意图路由 / LLM / TTS
  -> 通话记录 / 人工接管 / 实时监听
```

客户电脑不承担 Asterisk 运行时，也不让客户填写 AMI、SIP 密码、队列或防火墙配置。客户打开桌面客户端只看到三类信息：

1. 线路是否通畅。
2. 新设备是否被客户端发现。
3. 交付人员需要把现场语音网关注册到哪个云端 SIP 目标。

正式交付顺序必须是：

1. 交付人员在云服务器确认 Asterisk/AMI 正常。
2. 云安全组和上游网络放通 `UDP 5060` 和 `UDP 10000-20000`。
3. 交付人员在现场语音网关后台配置 SIP Server/Registrar、账号和密码，让设备主动注册到云端。
4. 后端 `/api/outbound/telephony/health` 显示 `trunkReachable=true`，客户端显示 `线路通畅`。
5. 只开启 `ASTERISK_LIVE_CALL_ENABLED=true` 做单号试拨。
6. 单号试拨、媒体链路、AI 首句和实时监听都通过后，才考虑开启批量外呼。

如果 `pjsip show contacts` 没有现场语音网关 contact，或者服务器抓不到 `UDP 5060` 入站包，不允许宣称外呼交付完成，也不应该启动真实拨号任务。

## 当前可先做

1. 使用模拟网关跑通外呼任务。
2. 使用 Redis 队列验证 worker 消费任务。
3. 在通话记录中保存 `gateway_call_id`、`gateway_status`、`raw_payload`。
4. 客户交付版使用云端 Asterisk；桌面客户端只展示线路状态和现场设备对接指引，本机 Asterisk 只用于开发验证。
5. 在 AI 外呼系统的「真实线路接入」面板做无拨号预检。
6. 使用 `python -m app.tools.uc100_preflight` 做命令行无拨号预检。
7. 参考 `docs/CUSTOMER_OUTBOUND_USAGE.md`、`docs/CLIENT_ASTERISK_SIDECAR.md` 和 `docs/UC100_ASTERISK_SNIPPETS.md` 准备客户交付、sidecar、PJSIP trunk 和 dialplan。
8. 在 AI 外呼系统的「实时语音管线」面板创建模拟通话，验证 ASR、意图路由、LLM、TTS 分块和打断状态机。
9. 约定人工接管和实时监听需要的 WebSocket/坐席方案。

## 开发备选架构

```text
实体 SIM 卡
  -> 现场语音网关
  -> SIP trunk
  -> 客户端内置 Asterisk sidecar
  -> FastAPI / Redis worker / 实时媒体桥
  -> 流式 ASR / 快速意图路由 / LLM / 流式 TTS
  -> 通话记录 / 人工接管
```

## 环境变量

先复制：

```bash
cd backend
cp .env.example .env
```

模拟模式：

```env
TELEPHONY_GATEWAY_MODE=simulator
OUTBOUND_QUEUE_ENABLED=false
REDIS_URL=redis://localhost:6379/0
OUTBOUND_QUEUE_NAME=ai_acq:outbound_tasks
```

启用队列：

```env
OUTBOUND_QUEUE_ENABLED=true
```

Asterisk/UC100 模式预留配置。客户交付版优先由桌面客户端生成 `backend-asterisk.env`，开发调试才手工写入：

桌面客户端 sidecar 生成 Asterisk 配置前，可用这些变量覆盖 UC100 现场参数：

```env
AI_ACQ_UC100_HOST=192.168.10.100
AI_ACQ_UC100_SIP_PORT=5080
AI_ACQ_UC100_SIP_USERNAME=1000
AI_ACQ_UC100_SIP_PASSWORD=现场分机密码
# Asterisk 运行在 Docker/虚拟网卡时填写客户电脑局域网 IP；原生本机 Asterisk 可留空。
AI_ACQ_ASTERISK_ADVERTISED_HOST=192.168.10.50
AI_ACQ_ASTERISK_LOCAL_NET=172.16.0.0/12
```

UC100 后台也要匹配接入方向：客户电脑接 UC100 `WAN` 地址 `192.168.10.100:5080` 时，`分机 / SIP` 的 AI 分机选择 `2-< wan_default >`；接 UC100 `LAN` 地址 `192.168.11.1:5060` 时才选择 `1-< lan_default >`。

```env
TELEPHONY_GATEWAY_MODE=asterisk
ASTERISK_HOST=127.0.0.1
ASTERISK_AMI_PORT=5038
ASTERISK_AMI_USERNAME=your-ami-user
ASTERISK_AMI_PASSWORD=your-ami-password
ASTERISK_AMI_TIMEOUT_SECONDS=5
ASTERISK_ORIGINATE_CONTEXT=from-ai-acq
ASTERISK_ORIGINATE_EXTENSION=s
ASTERISK_ORIGINATE_CHANNEL_TEMPLATE=PJSIP/{phone}@{trunk}
ASTERISK_ORIGINATE_TIMEOUT_MS=90000
ASTERISK_TEST_CALL_RESULT_WAIT_SECONDS=12
ASTERISK_CALLER_ID=AI获客
ASTERISK_TRUNK_NAME=uc100
ASTERISK_MAX_CHANNELS=1
ASTERISK_LIVE_CALL_ENABLED=false
ASTERISK_BULK_CALL_ENABLED=false
ASTERISK_AUDIO_SOCKET_BIND_HOST=127.0.0.1
ASTERISK_AUDIO_SOCKET_HOST=127.0.0.1
ASTERISK_AUDIO_SOCKET_PORT=9019
REALTIME_ASR_MODEL=paraformer-realtime-v2
REALTIME_TTS_VOICE_ID=
REALTIME_TTS_VOICE_NAME=
REALTIME_TTS_VOICE_TYPE=system
REALTIME_CONVERSATION_MODE=pipeline
REALTIME_LLM_TIMEOUT_SECONDS=0.9
REALTIME_CALL_OPENING_TEXT=您好，我是本地生活服务顾问，想跟您聊下视频号团购获客，方便吗？
REALTIME_CALL_EVENT_LOG_PATH=/tmp/ai-acq-realtime-call-events.jsonl
REALTIME_REPLY_MAX_CHARS=48
DASHSCOPE_REALTIME_TTS_MODEL=qwen3-tts-flash-realtime
DASHSCOPE_REALTIME_TTS_VOICE=Ethan
DASHSCOPE_OMNI_REALTIME_MODEL=qwen3.5-omni-flash-realtime-2026-03-15
DASHSCOPE_OMNI_REALTIME_URL=wss://dashscope.aliyuncs.com/api-ws/v1/realtime
DASHSCOPE_OMNI_REALTIME_VOICE=Serena
DASHSCOPE_OMNI_INPUT_TRANSCRIPTION_MODEL=qwen3-asr-flash-realtime

# DeepSeek 实时电话短回复。不要提交真实 API Key。
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_CHAT_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=5
DEEPSEEK_MAX_TOKENS=80
DEEPSEEK_STREAM_FIRST_SENTENCE=true
```

不要提交 `.env`，不要把 AMI 密码写进 Git。

安全开关：

- `ASTERISK_LIVE_CALL_ENABLED=true` 只允许单号试拨接口提交真实拨号。
- `ASTERISK_BULK_CALL_ENABLED=true` 才允许外呼任务批量使用真实线路。
- 设备首次联调时保持 `ASTERISK_BULK_CALL_ENABLED=false`，先确认一个号码能稳定接通。

## 本地验证命令

后端迁移和检查：

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
python -m compileall app migrations
alembic check
pip check
```

启动 API：

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

启动 worker：

```bash
cd backend
source .venv/bin/activate
python -m app.workers.outbound_worker
```

只消费一个任务就退出：

```bash
python -m app.workers.outbound_worker --once
```

查看网关配置：

```bash
curl http://localhost:8000/api/outbound/telephony/config
```

运行完整预检：

```bash
curl "http://localhost:8000/api/outbound/telephony/preflight?phone=你的测试手机号"
```

前端也已经接入同一套预检逻辑：打开 AI 外呼系统，进入「实时监听」页顶部的「真实线路接入」面板，输入测试号码后点「预检线路」。这个动作只检查配置、AMI、trunk 和 Channel 渲染，不会拨号。

不启动 API 的本地预检：

```bash
cd backend
source .venv/bin/activate
python -m app.tools.uc100_preflight --phone 你的测试手机号
python -m app.tools.uc100_preflight --phone 你的测试手机号 --json
```

检查 UC100/Asterisk 线路：

```bash
curl http://localhost:8000/api/outbound/telephony/health
```

实时语音管线模拟验证：

```bash
curl http://localhost:8000/api/outbound/realtime/pipeline
```

读取真实 AudioSocket 通话事件：

```bash
curl "http://localhost:8000/api/outbound/realtime/live-events?limit=80"
```

低延迟外呼默认使用 Qwen-TTS 实时系统音色增量播放。只有客户在声音档案明确选择复刻音色，或现场设置 `REALTIME_TTS_VOICE_TYPE=clone` / `REALTIME_TTS_VOICE_ID=cosyvoice...` 时，才切到 CosyVoice 克隆音色。克隆音色更像本人，但首包延迟通常明显高于系统实时音色。

创建模拟实时通话：

```bash
curl -X POST http://localhost:8000/api/outbound/realtime/sessions \
  -H 'Content-Type: application/json' \
  -d '{
    "merchantName": "模拟火锅店",
    "phone": "13800000000",
    "voice": {
      "voiceId": "qwen_tts_ethan",
      "voiceName": "晨煦（Ethan）",
      "voiceType": "system",
      "provider": "Qwen-TTS",
      "externalVoiceId": "Ethan"
    }
  }'
```

发送客户一句话，模拟 ASR 最终文本、意图路由、回复生成和 TTS 分块：

```bash
curl -X POST http://localhost:8000/api/outbound/realtime/sessions/会话ID/utterances \
  -H 'Content-Type: application/json' \
  -d '{"text":"你们这个怎么收费？","bargeIn":true}'
```

客户插话或人工触发打断：

```bash
curl -X POST http://localhost:8000/api/outbound/realtime/sessions/会话ID/interrupt
```

模拟 AI 播放完成并回到监听：

```bash
curl -X POST http://localhost:8000/api/outbound/realtime/sessions/会话ID/playback-complete
```

这组接口不会真实拨号；配置 `DEEPSEEK_API_KEY` 后，模拟会话和真实 AudioSocket 桥都会使用同一套 DeepSeek 短回复逻辑，失败时回退本地规则。音色来自「声音档案」：客户可选系统音色或已授权可用的复刻音色。

启动真实 AudioSocket 实时桥：

```bash
cd backend
source .venv/bin/activate
python -m app.tools.realtime_audio_bridge --check
python -m app.tools.realtime_audio_bridge
```

`--check` 只验证非密钥配置并输出 voice、ASR/TTS 模型、日志路径，不拨号。正式启动后，Asterisk 在电话接通时连接 `ASTERISK_AUDIO_SOCKET_HOST:ASTERISK_AUDIO_SOCKET_PORT`，把 8k PCM 电话音频送入实时 ASR/TTS 回路，桥会把事件写入 `REALTIME_CALL_EVENT_LOG_PATH`。前端「实时语音管线」会读取同一份事件，显示 ASR、DeepSeek 回复、TTS 播放和打断结果。

测试 Qwen Omni 端到端实时方案：

```bash
cd backend
source .venv/bin/activate
python -m app.tools.qwen_omni_realtime_smoke \
  --model qwen3.5-omni-flash-realtime-2026-03-15 \
  --voice Serena
```

`ok=true` 且输出 `inputTranscript`、`assistantTranscript`、`firstAudioMs`、`outputAudioBytes` 才算通过。当前实测裸 `qwen3.5-omni-flash-realtime` alias 在 `session.update` 后会断连，客户交付默认固定到 `qwen3.5-omni-flash-realtime-2026-03-15` snapshot。

启动 Omni 真实电话桥：

```bash
cd backend
source .venv/bin/activate
REALTIME_CONVERSATION_MODE=omni python -m app.tools.realtime_audio_bridge --check
REALTIME_CONVERSATION_MODE=omni python -m app.tools.realtime_audio_bridge
```

Omni 模式下，Asterisk AudioSocket 仍接收 8k 电话音频；桥会自动上采样到 16k 送入 Qwen Omni，再把模型输出的 24k PCM 降到 8k 播回电话。事件日志仍写入 `REALTIME_CALL_EVENT_LOG_PATH`，前端会显示 `omni_realtime_interruptible` 链路。

现场电话链路调音参数：

```env
REALTIME_BARGE_RMS_THRESHOLD=2200
REALTIME_BARGE_FRAMES=6
REALTIME_TTS_GAIN=1.4
```

AI 播放期间，普通回声和底噪不会送入 ASR；只有连续达到阈值的来音才触发打断。客户现场如果频繁误打断，先上调 `REALTIME_BARGE_RMS_THRESHOLD`；如果客户听到的 AI 声音偏小，可以小幅上调 `REALTIME_TTS_GAIN`。

单号试拨：

```bash
curl -X POST http://localhost:8000/api/outbound/telephony/test-call \
  -H 'Content-Type: application/json' \
  -d '{"phone":"你的测试手机号"}'
```

## 现场语音网关到货后的检查顺序

1. 插 SIM 卡并确认能正常注册运营商网络。
2. 确认云安全组/上游网络已放通 `UDP 5060` 和 `UDP 10000-20000`。
3. 在现场语音网关后台配置 SIP Server/Registrar、账号、密码和注册周期，让设备主动注册到云端 Asterisk。
4. 在云服务器运行 `tcpdump -nni any udp port 5060`，确认能看到设备 REGISTER 包。
5. 运行 `asterisk -rx "pjsip show contacts"`，确认能看到对应 trunk 的 contact。
6. 确认通话状态、挂断原因、录音或音频流是否可用。
7. 运行 `python -m app.tools.uc100_preflight --phone 你的测试手机号`，先让 AMI/trunk/Channel 检查通过。
8. 再把 `TELEPHONY_GATEWAY_MODE` 从 `simulator` 切到 `asterisk`。
9. 打开 `ASTERISK_LIVE_CALL_ENABLED=true`，在 AI 外呼系统里做单号试拨。
10. 在语音网关后台同时确认 `当前呼叫` 或 `话单` 有 VoLTE/GSM 蜂窝外呼记录；只有 SIP `ringing` 不算手机真实响铃。
11. 如果前端显示 `404 Not Found / NO_ROUTE_DESTINATION`，先修语音网关的 SIP 到 VoLTE/GSM 外呼路由、号码匹配规则和线路选择。
12. 单号试拨稳定后，再评估是否打开 `ASTERISK_BULK_CALL_ENABLED=true`。

## 现在还没做完的硬件相关实现

- Asterisk 事件回调持久化：接通、忙线、未接、挂断、失败需要从 AMI event 更新通话记录。
- AudioSocket 实时桥已具备独立进程和事件日志；还需要在客户现场完成真实单号电话测试，确认电话音频进入 ASR、TTS 音频回写电话、打断事件可观测。
- 人工接管时从 AI 通话转人工坐席。

第一阶段代码已经提供客户端内置 Asterisk sidecar 状态/启动入口、AMI 健康检查、预检 API/CLI、受开关保护的真实 originate 适配器、带 AMI 事件等待的单号试拨接口、实时语音管线模拟通话，以及独立 AudioSocket 实时桥。真实批量外呼仍需要在单号测试稳定后再开启。
