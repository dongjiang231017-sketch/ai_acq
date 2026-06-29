# 平台私信系统接入说明

当前平台私信系统先使用模拟网关，已经可以验证账号、模板、任务、会话、消息、意向标记和人工接管链路。真实美团/饿了么/抖音账号自动化接入时，只需要替换网关层，不需要重做任务和数据表。

## 默认模拟模式

```env
DM_GATEWAY_MODE=simulator
DM_QUEUE_ENABLED=false
DM_QUEUE_NAME=ai_acq:dm_tasks
REDIS_URL=redis://localhost:6379/0
```

模拟模式会根据线索意向分生成私信结果：

- `>= 80`：已回复，A 意向，需人工接管。
- `>= 65`：已回复，B 意向，需人工接管。
- `>= 50`：已发送，C 意向，自动跟进。
- `< 50`：已发送，D 意向，低意向。

## API 验证入口

```text
GET  /api/direct-messages/config
GET  /api/direct-messages/overview
GET  /api/direct-messages/accounts
POST /api/direct-messages/accounts
GET  /api/direct-messages/templates
POST /api/direct-messages/templates
GET  /api/direct-messages/tasks
POST /api/direct-messages/tasks
POST /api/direct-messages/tasks/{task_id}/start
GET  /api/direct-messages/conversations
GET  /api/direct-messages/messages
```

## Redis worker

队列默认关闭。需要验证 Redis worker 时：

```env
DM_QUEUE_ENABLED=true
```

然后运行：

```bash
cd backend
source .venv/bin/activate
python -m app.workers.dm_worker --once
```

## 后续真实平台接入点

真实平台私信自动化应接在：

```text
backend/app/services/dm_gateway.py
```

推荐实现步骤：

1. 先为每个平台维护登录态、每日发送上限、失败原因和封控状态。
2. 在 `BrowserAutomationDmGateway` 中接入浏览器自动化或平台开放接口。
3. 保持输出统一为 `DmResult`，不要让平台原始字段泄漏到业务层。
4. 发送前做节流，失败时写 `raw_payload`，便于后台排查。
5. 遇到登录、验证码、风控、人机校验时停止任务并标记账号异常。
