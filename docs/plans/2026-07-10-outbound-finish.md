# 方案：外呼板块收尾（自动挂机移植 + 运维脚本恢复 + 验证提交）

> 交接给 Codex 执行。方案作者：Claude（Cowork）。执行前先通读一遍。

## 背景（当前已确认的状态，不要重复排查）

- 当前分支：`feature/req-v1-alignment`（最新）。
- 通话链路已打通并真机验证过完整多轮对话：
  `后端(8001) → LiveKit Server(Docker, ws://127.0.0.1:7880) → livekit-sip(Mac 本机进程, 5062/udp, 二进制在 /tmp/ai-acq-go-bin/livekit-sip) → 鼎信 8T 网关(192.168.10.114:5060) → SIM 外呼`
- 鼎信网关的 SIP 注册已**故意禁用**（管理页 SIP 代理已清空）。这是修复不是故障：网关每 60 秒注册 LiveKit 被拒后会挂断进行中的通话（昨天所有"说一句就断"的根因）。IP→Tel 路由=任意来源→端口组0，呼叫不依赖注册。**不要恢复网关注册，不要动网关配置。**
- 后端网关模式已切 `TELEPHONY_GATEWAY_MODE=livekit`，改了三处（都已生效）：
  `~/.ai-acq-client/asterisk-sidecar/state/backend-asterisk.env`（真正生效的运行时覆盖文件）、`backend/.runtime/asterisk/backend-asterisk.env`、`backend/.env`。
  优先级：进程环境变量 > sidecar 运行时文件 > backend/.env(pydantic fallback)。
- 千问模型：后台 DB 配置 `qwen3.5-omni-plus-realtime` + 音色 Aiden（真机通过）。适配器 `app/tools/qwen_omni_realtime.py` 注释推荐 flash+Cherry；若拨测异常，先切回 flash 对照再排查。
- 分支 `backup/pre-switch-0710-102223` 保存了切分支前的本地成果，本方案就是把其中两样移植回来。

## 任务 1：恢复运维脚本（直接 checkout，无冲突风险）

```bash
git checkout backup/pre-switch-0710-102223 -- \
  scripts infra restart_outbound.command \
  backend/app/tools/livekit_selfhost_bootstrap.py
```

再确认 `.gitignore` 含有 `logs/` 和 `infra/livekit/sip-native.yaml` 两条（backup 分支的 .gitignore 里有，缺就补）。

脚本用途：`scripts/livekit-selfhost-up.sh` 一键起整套链路（本机 SIP 方式，勿改回 Docker SIP——bridge 网络会导致 RTP media-timeout）；`scripts/run-and-dial.sh` 体检+拨测+日志落 `logs/`；其余两个是辅助工具。

## 任务 2：移植"结束语自动挂机"功能（手工合并，勿整文件覆盖）

参考实现：`git show backup/pre-switch-0710-102223:backend/app/tools/livekit_outbound_agent.py`

合并到当前分支的 `backend/app/tools/livekit_outbound_agent.py`，共三块：

1. 顶部 import 加 `re`；模块常量区加：
   - `_FAREWELL_PATTERN = re.compile(r"再见|拜拜|不多打扰|不打扰了|不打扰您|感谢接听")`
   - `_HANGUP_GRACE_SECONDS = float(os.getenv("LIVEKIT_HANGUP_GRACE_SECONDS", "1.5"))`
2. `entrypoint` 里 session 建好后，加"结束语自动挂机"代码块（backup 版本里搜 `---- 结束语自动挂机 ----`，整块照搬）：
   - `conversation_item_added`：assistant 文本命中结束语 → `hangup_state["pending"]=True`
   - `user_state_changed` → speaking：取消挂机（客户反悔窗口）
   - `agent_state_changed` → listening/idle 且 pending：起 `_hangup_after_grace()` 任务
   - `_hangup_after_grace`：等 `_HANGUP_GRACE_SECONDS` 秒 → 发 `livekit_agent_hangup` 事件 → `ctx.api.room.remove_participant(...)` → `ctx.shutdown("agent_hangup_after_farewell")`
3. 事件名保持：`livekit_agent_hangup` / `livekit_agent_hangup_error`。

## 任务 3：验证

1. `cd backend && source .venv/bin/activate && python -m compileall app migrations && alembic check && pip check`
2. 重启 agent，**必须先杀干净旧 worker**（历史上多次残留导致新旧代码混跑）：
   `screen -S ai-acq-livekit -X quit; pkill -f "app.tools.livekit_outbound_agent"; sleep 1;` 再起一个，日志写 `logs/livekit-agent.log`，`pgrep` 确认只有一组进程。
3. 拨 `18850625208`（POST `/api/outbound/telephony/test-call`，body `{"phone":"18850625208","conversationRoute":"livekit","merchantName":"南昌本地生活招商项目"}`），让用户完整走话术到互道再见后**不要挂机**，验收标准：
   - 事件流出现 `livekit_agent_hangup`，AI 先挂断；
   - 客户在结束语后又说话时不挂，继续对话（可选验证）。
4. 通话不足 60 秒不算过——必须跨过一个整分钟边界仍不断（回归网关注册误杀）。

## 任务 4：提交推送

```bash
git add -A
git commit -m "feat: 外呼结束语自动挂机 + 自建LiveKit运维脚本（从backup分支移植）"
git push
```

## 红线

- 不动鼎信网关配置；不把 SIP 切回 Docker 容器；不删 `backup/pre-switch-0710-102223` 分支。
- Agent 重启后必须确认无旧 worker 残留再拨测。
