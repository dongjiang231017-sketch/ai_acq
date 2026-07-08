# 电销系统稳定性审计报告（2026-07-08）

审计范围：`ai_acq` 仓库实时外呼链路（媒体桥、turn 管理、线路/网关、部署）。
所有行号对应当前工作区代码（含未提交改动）。

## 结论（一句话）

系统"总是出错"不是一个问题，而是 **A 媒体桥竞态、B 电话层无监管、C 部署裸奔** 三类问题叠加。其中两个"元凶"解释了大部分现象：

1. **Omni websocket 回调线程被播放逻辑阻塞**（A类，解释 47秒断线/打断不停嘴/事件滞后）
2. **媒体桥是手工启动的独立进程，部署无脚本无监管无冒烟**（C类，解释"一改就断"/接通即挂）

---

## A. 媒体桥/通话体验类（realtime_audio_bridge.py 等）

### A1【最严重】Omni 回调线程被"实时播放节拍"阻塞 → 47秒断线、打断不停嘴

- 位置：`backend/app/tools/realtime_audio_bridge.py:2786-2860`（play_omni_audio_delta）、`:1732-1734`（time.sleep 节拍）、`:491-492`
- dashscope SDK 的 websocket **接收线程**里直接持锁、按 20ms/帧 `time.sleep()` 逐帧写音频。AI 说 8 秒话就把接收线程堵 8 秒：打断信号（speech_started）、response.done、ws ping 全部排队 → 服务端心跳超时断开 = "47秒后失效"；打断事件延迟处理 = "客户插话 AI 不停嘴"。
- 修法：回调线程只做"解码+入有界队列"，独立播放线程负责节拍与写 socket；打断=清队列。回调链里禁止任何 sleep/文件IO/DB。

### A2 Pipeline：AI 说话期间 ASR 断粮 + ASR 死亡无重启 → 40-60秒后失聪

- 位置：`realtime_audio_bridge.py:841-866`、`:417-424`（on_error/on_close 只打日志）、`:764-778`
- AI 播放期间不给流式 ASR 喂帧，服务端超时关任务；ASR 死后无任何重连，send 无 try/except。
- 修法：播放期间持续喂帧（或静音帧保活）；ASR 看门狗自动重建会话。

### A3 speaking 状态可永久卡死 → 卡在 SPEAKING 回不到 LISTENING

- 位置：`realtime_audio_bridge.py:2654`、`:2862-2943`、`:2056-2071`、`:1580`
- 只有 response.done 才清 speech_jobs；连接断开/事件丢失后无人清理。Pipeline 侧在 TTS 连上之前就置位 speaking。
- 修法：handle_omni_closed 强制清零；speech job 加最大存活看门狗（30s）；拿到首块音频才置位 speaking。

### A4 TTS 每句新建连接、失败静默吞掉 → "说了'我在'就没声了"、装死不挂机

- 位置：`realtime_audio_bridge.py:1664-1667`（except 只打日志且丢失 close_after）、`:2975-3050`
- TTS websocket 握手失败/12s 无音频 → 本轮回复无声消失；close_after 丢失 → Omni 断线后的收尾话失败时电话既不挂断也不再回复。
- 修法：TTS 失败降级链（realtime→整段合成→固定兜底句）；保留 close_after 语义；连接预热复用。

### A5 打断恢复用陈旧旧句重新作答 + 1.15s 兜底句循环 → 旧回复复活

- 位置：`realtime_audio_bridge.py:2609-2613`（无时效判断）、`:70-73`、`:2662-2731`、`:2901-2918`
- 打断后 1s 内无新转写就拿几十秒前的 last_committed_customer_text 重答；首音频 deadline 1.15s 过紧导致固定兜底话术反复出现；response_id 为空的音频不判陈旧。
- 修法：旧句加时效（>5s 改通用接话）；deadline 放宽至 2s + 兜底句去重；空 response_id 音频严格校验。

### A6 开场被"接听分类等待"卡最长 7 秒 → 喊多次"喂"AI 才说话

- 位置：`realtime_audio_bridge.py:1258-1318`、`:300`；`services/realtime_answer_classifier.py:75-76,111-116`
- 判 HUMAN 需要 ≥2 个语音段，ASR partial 的 HUMAN 信号被忽略。
- 修法：partial 出现"喂/你好"即放行开场；分类等待上限降到 ~2s；或边播开场边继续分类。

### A7 意向漏记（"加微信发资料"没进意向池）

- 位置：`realtime_audio_bridge.py:1497-1504`（drain 只留最新一条丢中间轮次）、`:2293-2318`（去重先于意向记录、命中即 return）；`services/realtime_intent_capture.py:159-163`
- 修法：意向捕获改独立旁路——每条 ASR partial/final 先做强标记扫描异步入库，不依赖轮次去重；DB 写移出 ws 回调线程。

### A8 打断阈值苛刻 + 恢复过快 → 打断体验不自然

- 位置：`realtime_audio_bridge.py:289-290`（RMS≥2200 连续6帧）、`:2517-2519`、`:2563-2578`；`realtime_turn_manager.py:173`
- 修法：双阈值（进入2200/维持~800）；恢复 watchdog 期间 VAD 报人声则顺延。

### A9 次级问题

- 全局日志锁内同步写文件+print（`:305-321`），极端情况可整进程卡死；改异步队列。
- `_read_exact`（`:3299-3309`）半帧超时丢字节 → AudioSocket 协议错位；应缓存续读。
- 8k→16k 升采样简单复制无插值（`:3092-3102`），拉低 Omni 识别率。
- 新 turn_manager 与桥内旧计时逻辑两套状态并存，是回归风险。
- 飞行记录仪 write_inbound 每 20ms 带锁磁盘写，应缓冲批量写。

---

## B. 电话层/线路网关类

### B1【P0】掉注册无监控无自愈，且 PJSIP 配置导致网关重启后注册被拒

- 位置：`deploy/asterisk/dinstar8t/pjsip.conf:52-56`（max_contacts=8 + remove_existing=no）；`backend/app/main.py`（无 watchdog）；`api/outbound.py:139-141`
- 网关重启换源端口重注册，旧 contact 残留满 8 个后新 REGISTER 被 403 拒——这就是"断网后必须人工处理"。且现有"自愈"命令（`telephony_cellular.py:180-188`）方向打反：那是让 Asterisk 向外注册，而本架构是网关注册进来，服务器端命令无效；`module reload res_pjsip.so` 还会波及在线通话，却被试拨失败自动触发。
- 修法：`remove_existing=yes`（或每口一账号 max_contacts=1）；后端加 30s 常驻 watchdog 轮询 contacts，消失即告警；module reload 移出自动路径。

### B2【P0】部署裸奔：媒体桥是手工启动的独立进程 → "一改就断"、接通即挂

- 位置：`deploy/` 只有 Asterisk 配置模板，无部署脚本/systemd/冒烟测试；dialplan 是 `Answer→AudioSocket→Hangup`
- 每次部署重启后端，bridge（9019端口）要么被杀没人拉起，要么跑旧代码。bridge 不在 → 电话接通后 AudioSocket 失败**立即 Hangup**。
- 修法：API+bridge 全部纳入 systemd；部署=原子重启+冒烟（探测9019、AMI登录、pjsip contacts、内部试拨），不过即告警/回滚。**这是性价比最高的一项。**

### B3【P0】预检不查 AudioSocket 和 SIM 侧，绿灯≠能通

- 位置：`services/telephony_preflight.py:32-206`
- 没查：bridge 存活、DashScope 连通、SIM/蜂窝状态（欠费/掉网/风控时预检全绿）。
- 修法：preflight 增加 audio_socket 探测、网关 HTTP API 查每口 GSM 状态。

### B4 trunk 可达判断是字符串启发式，stale contact 误判"可达"

- 位置：`services/asterisk_ami.py:515-531`
- 掉线后 qualify 判死前（最长~60s）仍显示 Avail；"Contact:"兜底 marker 会把 Unavail 误判可达。
- 修法：改结构化 AMI Action（ContactStatus/DeviceStateList）按字段判断。

### B5【P1】试拨接口单请求同步串行可阻塞 60s+ → 拨不出去、前端白屏

- 位置：`api/outbound.py:154-275`；Omni probe 无超时（`realtime_route_health.py:74-97`）；批量路径可阻塞 120s（`outbound_gateway.py:147-152`）
- 修法：试拨改异步任务（POST 返回 callId + 轮询/SSE）；probe 加 2-3s 硬超时；autoRecovery 移出请求路径。

### B6【P1】"实际线路"靠翻 /tmp 日志最后一条 bridge_start 推断 → "线路不能选/不可用"

- 位置：`services/realtime_outbound.py:140-156,177-204`；`api/outbound.py:157-173`（不匹配直接 409）
- bridge 死了旧日志还在、日志窗口冲掉就回退配置值，与实际脱节；用户选 omni 被 409"请先重启 bridge"。
- 修法：bridge 加健康/控制端口（pid、mode、版本、在线通话数），API 实时询问；大部分 409 可取消。

### B7【P1】Omni 在客户接通后才建连，失败兜底是沉默或道歉挂断

- 位置：`realtime_audio_bridge.py:1897-1934,1961-1986,2056-2078`
- 客户接通后现场连 Omni，这几秒只有静音；中途断连直接道歉挂断而非热切 Pipeline。熔断状态存 /tmp、TTL 90s、重启即丢。
- 修法：拨号发起时并行预热 Omni 会话；connect 加 2s 超时；断连热切 Pipeline 继续对话。

### B8【P1】AMI 事件归属不严、批量呼叫无跟踪

- 位置：`asterisk_ami.py:402-465,632`；`outbound_gateway.py:153-162`
- 等结果时 Hangup/Busy 事件不按 channel/Uniqueid 过滤，并发下张冠李戴（"接通后立刻被挂断"的假诊断来源之一）；`Up` 即判 answered 虚报接通；批量提交后无人跟踪状态。
- 修法：常驻 AMI 事件消费进程，按 Uniqueid 关联；事件按本次 channel 过滤。

### B9【P2】配置三来源叠加，残留 sidecar env 覆盖 .env → "改了不生效"

- 位置：`services/telephony_runtime_config.py:36-46,59-75`；`config.py:75` 与 `.env.example:107` 默认值不一致
- 修法：服务器模式禁用 sidecar 自动发现；启动时打印每个电话参数的最终来源。

### B10【P2】线路选项的可用状态/成本/延迟是硬编码估值，前端显示与实际不符

- 位置：`realtime_outbound.py:163-204`
- 修法：随 B6 改为实时询问 bridge；前端以试拨响应的 effectiveRoute 为唯一事实来源。

---

## 故障 → 根源对照表

| 线上现象 | 主根源 | 次根源 |
|---|---|---|
| 40-60秒后失聪/不回复 | A1、A2 | A3、A4 |
| 喊多次"喂"才说话 | A6 | B7 |
| 重复很早之前的话 | A5 | — |
| 打断不停嘴/不自然 | A1、A8 | — |
| "加微信"漏记意向 | A7 | 上游失聪 |
| 一改代码就断 | B2 | B9、B4、B3 |
| 接通后立刻被挂断 | B2 | B7、B8 |
| 网关断网后需人工恢复 | B1 | — |
| 选线路显示不可用 | B6 | B10 |
| 拨号1分钟没反应/白屏 | B5 | — |

## 建议修复顺序

1. **B2 部署监管+冒烟**（半天~1天，直接消灭"一改就断"）
2. **B1 pjsip remove_existing + 注册 watchdog**（几小时，消灭人工恢复）
3. **A1 播放移出回调线程**（1-2天，核心竞态，连带改善打断/断线）
4. **A2+A3 ASR保活/看门狗 + speaking 状态兜底**（1天，消灭失聪）
5. **A4 TTS 降级链**（半天）
6. **B5+B6 试拨异步化 + bridge 健康端口**（1天，消灭白屏和409）
7. **A5/A6/A8 体验调优**（deadline、分类等待、打断阈值）
8. **A7 意向旁路捕获**（半天）

修完 1-4 后再跑真实拨打回归；每一步都应先在飞行记录仪里可观测。
