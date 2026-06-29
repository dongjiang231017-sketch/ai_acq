# UC100 实体电话卡外呼接入准备

这份文档用于 UC100 到货前后的开发联调。当前系统已经有模拟电话网关、Redis 外呼队列、外呼 worker 和通话网关字段；硬件到货后主要补 Asterisk/UC100 连通和真实 originate 适配器。

## 当前可先做

1. 使用模拟网关跑通外呼任务。
2. 使用 Redis 队列验证 worker 消费任务。
3. 在通话记录中保存 `gateway_call_id`、`gateway_status`、`raw_payload`。
4. 准备 PostgreSQL、Redis、Asterisk 的本地或测试环境。
5. 约定人工接管和实时监听需要的 WebSocket/坐席方案。

## 推荐架构

```text
实体 SIM 卡
  -> UC100
  -> SIP trunk
  -> Asterisk
  -> FastAPI / Redis worker
  -> ASR / LLM / TTS
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
ASTERISK_ORIGINATE_CONTEXT=from-ai-acq
ASTERISK_TRUNK_NAME=uc100
```

不要提交 `.env`，不要把 AMI 密码写进 Git。

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

## UC100 到货后的检查顺序

1. 插 SIM 卡并确认能正常注册运营商网络。
2. 给 UC100 配置固定局域网 IP。
3. 在 Asterisk 配置 UC100 SIP trunk。
4. 在 Asterisk 配置 AMI 用户，只开放测试环境访问。
5. 从 Asterisk CLI 手动拨一个测试号码。
6. 确认通话状态、挂断原因、录音或音频流是否可用。
7. 再把 `TELEPHONY_GATEWAY_MODE` 从 `simulator` 切到 `asterisk`。
8. 接入真实 originate 适配器前，先用 1 张卡、1 路并发测试。

## 现在还没做的硬件相关实现

- Asterisk AMI originate 的真实拨号适配器。
- Asterisk 事件回调解析：接通、忙线、未接、挂断、失败。
- 实时音频流进入 ASR，再把 TTS 音频送回通话。
- 人工接管时从 AI 通话转人工坐席。

这些必须等 UC100 和 Asterisk 能互通后再做真实联调。现在代码里 `AsteriskGateway` 会故意报错，避免误以为已经接上真实线路。
