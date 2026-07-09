# 会话交接文档（2026-07-08，2026-07-09 更新）

> 给下一个接手的人/模型（新对话、Fable 5、或协作同事）。
> 目的：不用重讲，读完这份 + `git pull` 就能接着干。
> 配套文档：`STABILITY_AUDIT_20260708.md`（问题清单）、`TEST_REPORT_20260708.md`（测试记录）、
> `livekit-poc/README.md`（主线路部署）、`livekit-poc/integration/WORKER_MIGRATION.md`（同事 worker 改法）。

## 一句话背景

AI 电销外呼系统（视频号团购到店获客话术）。核心痛点：延迟高（客户说完等 2-5 秒）、
"间歇性不说话"、一改代码就断、网关掉注册要人工恢复。目标：延迟压进 1 秒、稳定可用。

## 现在的架构（两条线路）

```
客户手机 ↔ GSM ↔ 8口鼎信网关(生产) / UC100单卡(本地测试)
                      ↓ SIP
   ┌── 主线路 LiveKit（转正）: 网关SIP → LiveKit → Qwen Omni Realtime 直连
   └── 旧线路 Asterisk（降级兜底）: 网关 → 云Asterisk → AudioSocket → Python bridge
                      ↓
              ai_acq 业务层（销售状态机/意向池/CRM，两条线路共用）
```

生产服务器：101.132.63.159（阿里云上海，与 DashScope 同区，内网延迟低）。
DashScope 模型：`qwen3-omni-flash-realtime`。

## 两条线路的状态

### 主线路 LiveKit —— 已验证，转正为主
- 代码在 `livekit-poc/`。适配器 `agent/qwen_omni_realtime.py` 是**真机验证过**的（自测 15/15 出声）。
- 延迟：判停 800ms 时约 1.3s，默认已调 400ms 目标约 0.9s（`VAD_SILENCE_MS` 环境变量）。
- **本地实测环境在 Workbuddy 文件夹**：`~/Workbuddy/2026-07-07-15-55-19/livekit-local/`
  （docker compose 起 LiveKit+SIP+Redis，`.venv` 已装依赖，`run_agent.py` 起 agent，
  `outbound_call.py <号码>` 拨号，`test_agent_audio.py` 不打电话的出声自测）。
- 同事在 `feature/auth-and-leads` 分支也做了 LiveKit 对接（worker `livekit_outbound_agent.py`），
  但用的是**未验证**的 OpenAI 插件直连 + 会失败的 `say()` 开场白 —— 必须按
  `integration/WORKER_MIGRATION.md` 换成本仓库验证版适配器。

### 旧线路 Asterisk —— 只修了稳定，没修延迟，当兜底
- 审计 18 问题里的 A 类（媒体桥）+ B 类（电话层）已全部修复并静态/单元/复审验证。
- **但没在真实 Asterisk 环境端到端跑过**（本地无该环境）。部署要用新加的 `deploy/deploy.sh` 冒烟。
- 定位就是兜底/降级，别再投精力优化它的延迟——那等于重写，而 LiveKit 已经给了。

## 已知的坑（血泪，别重踩）

1. **"间歇性不说话"的真凶是适配器线程竞态**（已修）：MessageGeneration 的发送不能依赖
   `output_item.added`（ws 线程）时 `_current_gen` 是否就绪，必须移进 `response.created`
   协程里同步发。修前自测仅 37% 出声。**这类 bug 单次测试看不出来，必须测 10 次以上。**
2. 改这个适配器时，两次"优化"（同步创建+延迟emit / 按response_id管理生命周期）都把通过率
   干到 0%，已回退。**不要用 call_soon_threadsafe 延迟 emit；emit 必须与 gen 创建同协程。**
3. **拨号编排顺序**：必须先 dispatch agent 进房预热，再发起 SIP 呼叫；反了客户会听 30 秒静音。
4. **号码必须带 +86 前缀**，否则 UC100/GSM 直接拒接（SIP 480）。
5. **macOS 跑 agent 要有 `if __name__=="__main__"` 保护**，否则 spawn 子进程重复起 worker 崩溃。
6. **SIM 卡风控**：同一号码一小时内十几通短呼会被移动停机（运营商未知/信号空白）。这是今天
   真机终验没做成的唯一原因，代码无关。上量前外呼队列必须加：单卡日呼上限、同号间隔、
   多卡轮换、间隔随机化。
   →【2026-07-09 已做】`dial_policy.py`（backend/app/services/ 与 livekit-poc/agent/ 各一份，
   单一来源是 backend）。已接入三个拨号入口：livekit-poc `dial_api.py`（429+Retry-After，
   另加 GET /policy 观测）、backend `outbound_runner.py`（跳过并写回拨时间）、
   `/telephony/test-call` 试拨（429）。默认：单卡 6 通/时、50 通/日；同号间隔 30min、3 通/日；
   同卡随机间隔 60-150s；多口配 `DIAL_PORTS` 自动 LRU 轮换。参数见 .env.example「防封卡」段。
   单测 13 项含事故回放（一小时 15 通只放行 6 通）：`backend/tests/test_dial_policy.py`。
7. **本地网络拓扑**：Mac 和 UC100 必须同网段（UC100 在 192.168.1.4）。Mac 连到别的路由器
   （如中国移动 cmcc.wifi 192.168.10.x）时，SIP 去程通但回程被 NAT 挡，表现为"电话响了但 AI 不说话"。
   另：UC100 在 WAN 侧（192.168.1.4）的 SIP 监听端口是 **5080**（5060 在它 LAN 口 192.168.11.1），
   outbound trunk 必须指 5080；网关中继注册状态显示"重试"失败不影响呼出（IP 直连按来源匹配）。
8. git push 在某些环境要走本机代理：`export https_proxy=http://127.0.0.1:7890` 再 push。
9. **"只说开场白，之后不说话"的真凶是 user_initiated 误标**（2026-07-09 已修，真机复现）：
   适配器原来把所有 response 的 GenerationCreatedEvent 都标 `user_initiated=True`，而框架
   `agent_activity._on_generation_created` 对 True 直接 return（只有 pending 的 generate_reply
   会消费），VAD 触发的轮次回复全被丢弃——模型明明生成了音频（日志 audio.delta 一堆）却永远
   不播。修法：仅当存在未完成的 reply future 时才标 True。**旧自测只测开场白，测不出这个**，
   多轮自测用 `livekit-poc/scripts/test_multiturn.py`（模拟客户说话两轮，5/5 通过）。
10. **DashScope 暗坑3**（2026-07-09 发现并修复）：server_vad 模式下、输入音频流活跃时，
    手动 `conversation.item.create`+`response.create` 被**静默忽略**（不回事件不回 error）——
    开场白因此间歇性不响（电话里能响是靠 RTP 音频晚到几百毫秒的运气）。修法：适配器加输入
    门控，首个 response.done 之前不向 DashScope 喂音频（12s 失效保护）。代价：开场那几秒
    检测不到客户插话。最小复现脚本在 Workbuddy 测试台 probe_v2.py。

## 待办（按优先级）

1. **主线路真机终验**：SIM 恢复后，Workbuddy 环境 `outbound_call.py 18107090349` 打一通，
   确认接通即出声、可打断、延迟达标。达标后主线路即"拿下来能用"。
   注意：终验拨测建议走 dial_api（已带防封卡节流）；按默认 6 通/时，10 通连测约需 2 小时，
   赶时间可当天临时调 DIAL_PORT_HOURLY_CAP，测完改回。
2. ~~同事按 `WORKER_MIGRATION.md` 把他 worker 的适配器换成验证版~~
   →【2026-07-09 代码已改完，提交在 feature/auth-and-leads `0c3e8b8`】：
   验证版适配器拷入 backend/app/tools/、DashScope 分支弃用 openai 插件改裸
   AgentSession、say()→generate_reply、outbound 强制 wait_until_answered=True、
   模型默认统一回 qwen3-omni-flash-realtime/Cherry、补硬上限（LIVEKIT_MAX_CALL_SECONDS）
   与 turn_latency 打点（待办6 A/B 依赖）。
   剩余动作：同事 pull + review，部署到 101.132.63.159（worker 必须 systemd 常驻）。
   ⚠️ 顺带发现：dev 分支 config.py 的 dashscope_omni_realtime_model 默认也是
   qwen3.5-omni-flash-realtime-2026-03-15（旧线路 Omni 桥在用），该模型串未见验证记录，
   需确认生产 .env 实际值后再决定是否同样统一。
3. 8 口鼎信网关的 trunk 对接（本地只验证了 UC100 单卡链路，非 8 路并发）。
   接好后把 8 个口配进 `DIAL_PORTS`，防封卡轮换即生效。
4. ~~外呼队列加防封卡策略（见坑 6）~~ →【2026-07-09 完成】见坑 6 的更新说明。
5. 旧线路用 `deploy/deploy.sh` 部署冒烟 + 真实拨打回归。
6. 两条线路同批号码各打 50 通 A/B，比 P50/P95/接通率/意向率，定最终主链路。

## 验收标准

转向延迟 P50 ≤ 800ms、P95 ≤ 1500ms；打断后停嘴 ≤ 300ms；接通即出声（不用客户先喂）；
真实电话连续 10 通达标。测延迟用 `livekit-poc/scripts/measure_report.py`。

## git 状态

分支 `dev`，最新 `25b1caa`。本次相关提交：
`5c4ee84`/`03745d3`/`b7933c4`/`25b1caa`（主线路+对接+竞态修复）、
`2a4ad1e`（旧线路底座+审计）。同事的 LiveKit 对接在 `feature/auth-and-leads`。
2026-07-09 新增：dev `f3f11d1`（防封卡策略）、feature/auth-and-leads `0c3e8b8`
（worker 迁移到验证版适配器）。两个提交均未 push（push 记得走本机代理，见坑 8）。

## 关键路径速查

- 主线路适配器：`livekit-poc/agent/qwen_omni_realtime.py`
- 主线路 agent 主流程：`livekit-poc/agent/main.py`
- 话术：`livekit-poc/agent/sales_prompt.py`
- 后台对接：`livekit-poc/integration/livekit_route.py` + `INTEGRATION.md`
- 旧线路媒体桥：`backend/app/tools/realtime_audio_bridge.py`
- 防封卡策略：`backend/app/services/dial_policy.py`（单一来源）+ 同名拷贝在 `livekit-poc/agent/`
- 本地测试环境：`~/Workbuddy/2026-07-07-15-55-19/livekit-local/`（不在 git，是本地实测台）
