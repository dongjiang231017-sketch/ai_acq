# 2026-07-10 新话术与克隆语音接入验收报告

## 结论

- 话术、语音库、运行配置和进程切换已完成。
- 事后更正（2026-07-10 12:07:16）：开场 A 已按新手册原文播出并进入正常对话；但通话结束原因不是“被叫主动挂断”。`logs/livekit-sip-native.log` 明确记录 `reason: media-timeout`，原报告对挂断主体的判定有误。
- 离线费用口径已通过：问“多少钱/服务费多少”命中不报价话术 `023`；问“抽成多少/怎么抽佣”命中 `010`，只说“微信支付手续费千分之六”。
- 仍需一次人工复验：接听后明确问“多少钱”，确认不报价；再问“抽成多少”，确认只回答千分之六。未在本次任务中擅自追加第三拨。

## 素材与入库

- 已通读并结构化抽取：
  - `docs/materials/视频号团购电销话术手册_主篇.docx`
  - `docs/materials/视频号团购话术手册_增补篇_不报服务价_保留千分之六.docx`
- ZIP 内确认语音共 74 条，编号与确认话术一一对应。
- 排除的 7 条未确认编号：`56`、`57`、`58`、`60`、`62`、`70`、`71`。这些编号未进入数据库、运行 instructions 或音频缓存。
- 新话术：`视频号团购电销话术手册 2026-07-10`，ID `52ad872240d4485aa0bdbfb6bff578a1`，启用，74 条结构化条目，74 条编号到音频映射。
- 旧话术：`视频号团购商家邀约话术`，ID `74384a299f164aeb8529cd151de628a1`，仅停用，未删除。
- 新增迁移 `20260710_0021`，为 `call_scripts` 增加 `entries` 和 `audio_mapping` JSON 字段；迁移已应用。

## 合规处理

- AI 主动话术不含本公司服务报价；价格异议统一转门店方案和微信收口。
- 抽成/手续费唯一口径为“微信支付手续费千分之六”。
- 为满足硬规则，使用同一克隆 voice 重生成 `03/05/09/10/11/45/77`：去掉免费服务暗示、其他平台抽成追问、金额算例和“零抽成”表述。
- 导入器会拒绝已知服务价格、其他抽成口径、零抽成、未确认占位符和 7 个待确认编号。
- DeepSeek 自由回复增加价格安全过滤；命中人民币金额、其他费率、零抽成或免费服务暗示时，自动回退本地合规话术。

## 语音接入

- 本机语音包：`backend/.voice_samples/packs/video_group_buying_20260710`，共 74 份源 MP3、74 份 24 kHz mono PCM WAV、74 份 8 kHz mono PCM WAV、74 份 8 kHz raw PCM，约 85 MB。
- 开场序号：`001`；费用序号：`023`；抽成序号：`010`。
- 默认 voice profile：`视频号团购招商顾问克隆音色`，ID `810678b4006e42baa668514056cf8e08`，74 个样本，状态可用。
- clone record：`fd6bbefcbebe44459806c8d2f4087b99`；模型 `cosyvoice-v3.5-flash`。
- LiveKit Omni 限制：固定开场优先播放克隆音频；Omni 动态回复仍使用 DashScope 内置 `Cherry`。Pipeline 的固定缓存和自由 TTS 均使用克隆音色。没有伪造 Omni 支持克隆 voice 的能力。
- ZIP、MP3、WAV、PCM 均位于 `.voice_samples`，由 `.gitignore` 排除，不进入 Git。

## 运行状态

- 重启前已退出旧 screen 并按模块名补杀，确认旧 agent worker 数为 0 后再启动。
- 新 LiveKit agent Python worker PID `83073`，已注册 `ai-acq-outbound-agent`。
- 新 realtime bridge Python worker PID `85716`，启动日志确认 `cosyvoice-v3.5-flash`、克隆 voice、Omni `Cherry`。
- 原生 `livekit-sip` PID `902` 从重启前到重启后未变化，仍使用 `infra/livekit/sip-native.yaml`；未切换为 Docker。
- 未修改鼎信网关配置；注册禁用状态保持不变。

## 真机拨测

目标号码：`188****5208`。

1. 首拨 action `lk-8d52b2d4e8934b7c895b16d044695bd3`：SIP `486 Busy Here`，未接通。
2. 按用户指令重拨 action `lk-04b4ccdd4d404998a7f3b92030b1fe7e`：业务记录时长 83 秒（包含建呼/回收阶段），记录 ID `3095530a4613416bb27155e8fcc4399a`；SIP 媒体链路于 12:07:16 因 `media-timeout` 关闭。
3. AI 完整播出开场 A：

   `喂，老板您好！耽误您半分钟。我是做视频号团购的，就是微信里刷视频那个视频号，现在能挂团购了，专门帮咱实体店从微信上拉客人到店。想问下，咱店里这块开了没？`

4. 被叫回答“啊！没有。”和“可以啊，你说。”，AI 正常进入获客渠道和视频号团购说明。
5. 被叫未问价格；AI 说到“平台手续费是微信支...”时，SIP 媒体超时导致通话中断，不得记为被叫主动挂断。故开场真机通过，价格/抽成真机项待复验，`media-timeout` 待后续 Pipeline + RTP 保活任务修复。

## 自动验证

- `python -m app.tools.import_script_voice_pack --dry-run`：74 条确认、7 条排除、ZIP 74 条，通过。
- `python -m app.tools.realtime_sales_eval`：56 个场景、76 个 gate，平均 100.0，通过。
- 费用探针：`多少钱` -> `023`，不报价并转微信；`抽成多少` -> `010`，只说千分之六。
- 数据库审计：新话术 74/74，待确认编号为空，已知服务价格为空，零抽成表述为空；旧话术仍在且停用。
- `python -m compileall app migrations`：通过。
- `alembic check`：`No new upgrade operations detected.`
- `pip check`：`No broken requirements found.`
- `npm run build`：通过，Vite 构建完成。
- `git diff --check`：通过。
- 仓库没有 `backend/tests` 或根目录 `tests`，因此无 pytest 套件可运行。
