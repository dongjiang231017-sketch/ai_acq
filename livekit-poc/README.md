# LiveKit 外呼 PoC（网关 SIP 直连 + Qwen Omni）

对照线路：现有 Asterisk+AudioSocket 链路（另一位同事在修）。
本线路目标：**真实转向延迟 P50 ≤ 800ms、P95 ≤ 1500ms，垫词后体感 ~0.4s**。
两条线路用同一批号码各打 50 通，拿 `measure_report.py` 的数据对比后定主链路。

## 架构

```
客户手机 ⇦GSM⇨ 鼎信8口网关 ⇦SIP/RTP⇨ livekit-sip(5060) ⇔ livekit-server(7880)
                                                              ⇕ (房间音频)
                                          agent/main.py ⇔ Qwen Omni Realtime (DashScope)
                                              ⇑ dispatch
                                   dial_api.py (POST /calls) ← 你们的业务后台
```

与旧链路的区别：Asterisk、AudioSocket、手写媒体桥整层没有了；打断、播放清空、
jitter buffer 由 LiveKit 处理；判停由 Omni server_vad 处理（毫秒数可调）。

## 部署步骤（阿里云 ECS，Ubuntu 22+）

### 1. LiveKit 三件套

```bash
cd livekit-poc/deploy
# 先改 livekit.yaml 的 keys（openssl rand -hex 16 生成 secret），
# 同步改 sip.yaml 的 api_key/api_secret
docker compose up -d
docker compose logs -f --tail=20   # 确认三个容器都健康
```

安全组放行：`7880/tcp`（API/WS）、`7881/tcp`、`50000-50200/udp`（WebRTC RTP）、
`5060/udp`（SIP，只对网关IP放行）、`10000-12000/udp`（SIP RTP，只对网关IP放行）。

### 2. 外呼 trunk

```bash
# 改 deploy/trunk-outbound.json：address=网关IP:5060，numbers=主叫号
LIVEKIT_URL=http://127.0.0.1:7880 LIVEKIT_API_KEY=xxx LIVEKIT_API_SECRET=xxx \
  bash scripts/create_trunk.sh
# 记下输出的 ST_xxx
```

### 3. 网关侧（鼎信）配置

- 新建一个 **IP 中继/SIP Trunk**，对端地址 = 本服务器IP:5060，无需注册（IP互信）。
- 路由规则：**IP->Tel**，把来自该中继的呼叫路由到 GSM 端口组（8口轮选）。
- 编解码：保留 G.711 A-law/µ-law（PCMA/PCMU），关掉 G.729 避免协商失败。
- 若网关在 NAT 后，开启网关的 NAT 穿透或把 RTP 固定到公网可达地址。

### 4. Agent

```bash
cd livekit-poc/agent
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填 LiveKit keys、trunk id、DASHSCOPE_API_KEY
python ../scripts/gen_fillers.py     # 生成垫词音频（一次性）
python main.py dev                   # 开发模式，前台跑，看日志
```

### 5. 外呼接口

```bash
uvicorn dial_api:app --host 0.0.0.0 --port 8100
# 发起测试呼叫：
curl -X POST http://127.0.0.1:8100/calls \
  -H 'Content-Type: application/json' \
  -d '{"phone_number": "181xxxxxxxx", "merchant_name": "测试商家"}'
# 查看通话事件：
curl http://127.0.0.1:8100/calls/<call_id>
```

### 6. 验收

打 50 通真实电话后：

```bash
python scripts/measure_report.py agent/metrics_logs/
```

报告直接给出 P50/P95 和 PASS/FAIL。

## 对接点（给业务后台）

| 对接项 | 说明 |
|---|---|
| 发起外呼 | `POST /calls`，body 里带 `phone_number`、`merchant_name`，返回 `call_id` |
| 通话状态/转写 | `GET /calls/{call_id}`，events 里有 `call_connected`、`transcript`（含客户原话，可做意向识别）、`callee_hangup`、`turn_latency` |
| 意向捕获 | PoC 里未内置。建议：后台轮询 transcript，命中"加微信/发资料"等强标记时写意向池（沿用现有 `realtime_intent_capture` 的标记表） |
| 批量外呼 | 循环调 `POST /calls` 即可；并发上限=网关口数(8)，超发会拨号失败，后台自行排队 |

## 已知风险与调参点（重要，先读再测）

1. **DashScope 的 OpenAI Realtime 兼容性**：`main.py` 复用 livekit openai 插件直连
   DashScope 兼容端点。若连接报协议错误（字段/事件名不一致），改 `_build_realtime_model`，
   必要时按 DashScope 文档写薄适配层——这是本 PoC 最可能要动手的地方。
2. **判停毫秒数**：`.env` 的 `VAD_SILENCE_MS`，300=快但容易抢话，500=稳但慢。
   从 400 起步，用真实电话调。第二阶段可上 LiveKit 语义判停（turn-detector 插件）对照。
3. **垫词节制**：目前每次判停都垫。若听感太密，在 `FillerPlayer.play_once` 里加
   "距上次垫词 <8s 则跳过"的逻辑。
4. **音质**：网关到服务器走公网时 RTP 可能抖动，优先同 VPC 内网直连。
5. **本地规则兜底未移植**：PoC 全部回复走 Omni。若 Omni 断连，当前行为是通话静默
   （LiveKit 会重连一次）。迁移阶段再把旧系统的本地规则脑接进来做兜底。
6. **成本**：Omni 按 token 计费，测试期每天看一眼百炼账单。

## 文件清单

```
deploy/          docker-compose + livekit/sip 配置 + trunk 模板
agent/main.py    外呼 agent（拨号、会话、垫词、打点、挂断收尾）
agent/sales_prompt.py    电销话术（业务口径与旧系统一致）
agent/metrics_recorder.py 延迟打点 JSONL
agent/dial_api.py         外呼 HTTP 接口（业务后台对接这个）
scripts/create_trunk.sh   建 trunk
scripts/gen_fillers.py    生成垫词音频
scripts/measure_report.py P50/P95 验收报告
```

## 状态声明

本 PoC 为**未经真实环境运行的脚手架**（写作环境无法连 LiveKit/网关/DashScope）。
预期首次部署需要现场调整的位置已在上面"已知风险"里标注，其中第 1 条（协议兼容）
概率最高。代码全部通过语法检查。
