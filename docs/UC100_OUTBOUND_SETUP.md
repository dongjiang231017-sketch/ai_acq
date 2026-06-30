# UC100 实体电话卡外呼接入准备

这份文档用于 UC100 到货前后的开发联调。当前系统已经有模拟电话网关、Redis 外呼队列、外呼 worker、通话网关字段、Asterisk AMI 健康检查、单号试拨接口、真实 originate 适配器，以及设备未识卡前可用的实时语音管线模拟接口。

## 当前可先做

1. 使用模拟网关跑通外呼任务。
2. 使用 Redis 队列验证 worker 消费任务。
3. 在通话记录中保存 `gateway_call_id`、`gateway_status`、`raw_payload`。
4. 准备 PostgreSQL、Redis、Asterisk 的本地或测试环境。
5. 在 AI 外呼系统的「真实线路接入」面板做无拨号预检。
6. 使用 `python -m app.tools.uc100_preflight` 做命令行无拨号预检。
7. 参考 `docs/UC100_ASTERISK_SNIPPETS.md` 准备 Asterisk AMI、PJSIP trunk 和 dialplan。
8. 在 AI 外呼系统的「实时语音管线」面板创建模拟通话，验证 ASR、意图路由、LLM、TTS 分块和打断状态机。
9. 约定人工接管和实时监听需要的 WebSocket/坐席方案。

## 推荐架构

```text
实体 SIM 卡
  -> UC100
  -> SIP trunk
  -> Asterisk
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

Asterisk/UC100 模式预留配置：

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
ASTERISK_ORIGINATE_TIMEOUT_MS=30000
ASTERISK_CALLER_ID=AI获客
ASTERISK_TRUNK_NAME=uc100
ASTERISK_MAX_CHANNELS=1
ASTERISK_LIVE_CALL_ENABLED=false
ASTERISK_BULK_CALL_ENABLED=false
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

这组接口不会真实拨号，也不会调用真实 ASR/LLM/TTS 供应商；它用于设备对接前先把外呼会话状态、音色选择、打断处理和前端操作闭环跑顺。音色来自「声音档案」：客户可选系统音色或已授权可用的复刻音色。

单号试拨：

```bash
curl -X POST http://localhost:8000/api/outbound/telephony/test-call \
  -H 'Content-Type: application/json' \
  -d '{"phone":"你的测试手机号"}'
```

## UC100 到货后的检查顺序

1. 插 SIM 卡并确认能正常注册运营商网络。
2. 给 UC100 配置固定局域网 IP。
3. 按 `docs/UC100_ASTERISK_SNIPPETS.md` 在 Asterisk 配置 UC100 SIP/PJSIP trunk。
4. 在 Asterisk 配置 AMI 用户，只开放测试环境访问。
5. 从 Asterisk CLI 手动拨一个测试号码。
6. 确认通话状态、挂断原因、录音或音频流是否可用。
7. 运行 `python -m app.tools.uc100_preflight --phone 你的测试手机号`，先让 AMI/trunk/Channel 检查通过。
8. 再把 `TELEPHONY_GATEWAY_MODE` 从 `simulator` 切到 `asterisk`。
9. 打开 `ASTERISK_LIVE_CALL_ENABLED=true`，在 AI 外呼系统里做单号试拨。
10. 单号试拨稳定后，再评估是否打开 `ASTERISK_BULK_CALL_ENABLED=true`。

## 现在还没做的硬件相关实现

- Asterisk 事件回调持久化：接通、忙线、未接、挂断、失败需要从 AMI event 更新通话记录。
- Asterisk ExternalMedia/AudioSocket 把真实电话音频流接入 ASR，再把 TTS 音频送回通话。
- 人工接管时从 AI 通话转人工坐席。

第一阶段代码已经提供 AMI 健康检查、预检 API/CLI、受开关保护的真实 originate 适配器、单号试拨接口和实时语音管线模拟通话。真实批量外呼仍需要在单号测试稳定后再开启。
