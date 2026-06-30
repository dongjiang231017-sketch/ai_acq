# 平台私信系统接入说明

当前平台私信系统先使用模拟网关，已经可以验证账号、模板、任务、会话、消息、意向标记和人工接管链路。真实美团/饿了么/抖音账号自动化接入时，只需要替换网关层，不需要重做任务和数据表。

## 默认模拟模式

```env
DM_GATEWAY_MODE=simulator
DM_QUEUE_ENABLED=false
DM_QUEUE_NAME=ai_acq:dm_tasks
DM_BROWSER_PROFILE_ROOT=.dm_browser_profiles
DM_BROWSER_HEADLESS=true
DM_BROWSER_CHANNEL=chrome
DM_BROWSER_TIMEOUT_MS=15000
DM_BROWSER_SLOW_MO_MS=0
DM_BROWSER_LIVE_SEND_ENABLED=false
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
PATCH /api/direct-messages/platform-configs/{config_id}
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
- `session_status` 必须为 `已登录`，不能用模拟状态放行发送。
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

浏览器模式：

```env
DM_GATEWAY_MODE=browser
DM_BROWSER_CHANNEL=chrome
```

真实点击发送还有一个独立安全闸门，默认关闭：

```env
DM_BROWSER_LIVE_SEND_ENABLED=true
```

未开启时，系统可以做账号检测和配置校验，但启动私信任务不会真的点击平台发送按钮。

登录态检测入口：

```text
POST /api/direct-messages/accounts/{account_id}/preflight
```

检测时会优先读取该账号独立 Profile 下的 Cookie、localStorage、Session Storage 等登录痕迹；浏览器模式下还会结合平台页面登录标识选择器。只有检测成功才写回 `可用 / 已登录 / 正常`，否则保持 `待登录 / 未登录`。

## 平台页面选择器

真实网页自动化所需的地址和选择器保存在：

```text
dm_platform_configs
```

字段包括：

- `home_url`：平台工作台首页。
- `inbox_url`：平台站内信或会话列表地址。
- `merchant_search_url`：商家搜索 URL 模板，支持 `{商家名称}`、`{城市}`、`{品类}`、`{平台}`。
- `login_check_selector`：已登录页面上稳定存在的元素。
- `risk_check_selector`：验证码、风控、人机校验页面元素。
- `merchant_link_selector`：搜索结果里的目标商家入口。
- `message_button_selector`：进入私信窗口按钮。
- `input_selector`：私信文本输入框。
- `send_button_selector`：发送按钮。
- `sent_success_selector`：发送成功后的确认元素，可为空。
- `unread_selector`：未读会话条目。
- `conversation_item_selector`：会话列表条目。
- `conversation_title_selector`：当前会话商家名称。
- `message_text_selector`：会话里的消息文本。

当前默认平台配置为 `enabled=false`，需要实测页面后再启用。客户端“平台私信系统 / 账号管理 / 真实平台适配器配置”可以维护这些字段。

线索表新增 `platform_url`，用于保存美团/饿了么/抖音商家页或私信入口。发送时优先使用 `platform_url`；没有时才使用 `merchant_search_url` 模板。

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
2. 在平台配置中填好 URL 和选择器，先保持 `enabled=false`。
3. 把账号切到 `DM_GATEWAY_MODE=browser`，用 `POST /accounts/{account_id}/preflight` 检测登录态。
4. 单账号、单商家、低频测试通过后，再启用平台配置。
5. 最后显式开启 `DM_BROWSER_LIVE_SEND_ENABLED=true`，启动真实私信任务。
6. 保持输出统一为 `DmResult`，不要让平台原始字段泄漏到业务层。
7. 发送前做节流，失败时写 `raw_payload`，便于后台排查。
8. 遇到登录、验证码、风控、人机校验时停止任务并标记账号异常。
9. 真实回复监听接入 `/api/direct-messages/sync-replies` 对应的服务层，按账号轮询 inbox 后写入 `dm_messages` 和 `dm_conversations`。
