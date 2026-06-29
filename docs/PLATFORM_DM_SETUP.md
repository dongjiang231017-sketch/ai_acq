# 平台私信系统接入说明

当前平台私信系统先使用模拟网关，已经可以验证账号、模板、任务、会话、消息、意向标记和人工接管链路。真实美团/饿了么/抖音账号自动化接入时，只需要替换网关层，不需要重做任务和数据表。

## 默认模拟模式

```env
DM_GATEWAY_MODE=simulator
DM_QUEUE_ENABLED=false
DM_QUEUE_NAME=ai_acq:dm_tasks
DM_BROWSER_PROFILE_ROOT=.dm_browser_profiles
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
PATCH /api/direct-messages/accounts/{account_id}
POST /api/direct-messages/accounts/{account_id}/preflight
GET  /api/direct-messages/platform-configs
POST /api/direct-messages/platform-configs
GET  /api/direct-messages/templates
POST /api/direct-messages/templates
GET  /api/direct-messages/tasks
POST /api/direct-messages/tasks
POST /api/direct-messages/tasks/{task_id}/start
GET  /api/direct-messages/conversations
POST /api/direct-messages/sync-replies
GET  /api/direct-messages/messages
```

## 账号池轮转和风控

平台私信任务支持两种模式：

- 指定账号：任务只使用指定平台账号，但仍检查登录态、风险状态、日额度和发送间隔。
- 账号池轮转：任务不绑定账号，每条线索发送前自动选择一个可用账号。

发送前置校验在 `backend/app/services/dm_policy.py`：

- `status` 必须为 `可用`。
- `session_status` 必须为 `已登录` 或 `模拟可用`。
- `risk_status` 不能是 `需验证`、`风控暂停`、`封禁`、`异常`。
- `sent_today` 不能超过 `daily_limit`。
- `last_sent_at + min_send_interval_seconds` 不能晚于当前时间。
- 同一商家如果已有 `已发送` 或 `已回复` 会话，会跳过重复触达。

## 浏览器 Profile

每个平台账号都会生成一个独立 Profile 标识：

```text
.dm_browser_profiles/{platform-account-id}
```

真实客户端接入时，每个账号要使用独立浏览器上下文或独立用户目录，避免多个账号共享 Cookie。不要把 Profile 目录、Cookie、验证码、密码提交到 Git。

登录态检测入口：

```text
POST /api/direct-messages/accounts/{account_id}/preflight
```

模拟模式会把账号标记为 `可用 / 模拟可用 / 正常`。真实浏览器模式下，应在这里检测扫码登录、验证码、风控页、人机校验，并把账号状态写回。

## 平台页面选择器

真实网页自动化所需的地址和选择器保存在：

```text
dm_platform_configs
```

字段包括首页、收件箱、商家搜索页、私信按钮、输入框、发送按钮和未读消息选择器。当前默认平台配置为 `enabled=false`，需要实测页面后再启用。

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
6. 真实回复监听接入 `/api/direct-messages/sync-replies` 对应的服务层，按账号轮询 inbox 后写入 `dm_messages` 和 `dm_conversations`。
