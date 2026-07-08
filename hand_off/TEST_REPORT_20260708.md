# 双路线修复与测试报告（2026-07-08）

两条线路的修复全部完成并经多轮验证。以下是每一轮检查的方法与结果。

## 一、改了什么

### 主线路（LiveKit，转正为主）
- `livekit-poc/agent/qwen_omni_realtime.py`：真机验证过的 Qwen Omni 适配器，含 5 个修复
  （modalities 立即声明、10ms 分帧、开场白绕过、奇字节截断、**竞态修复**）
- `livekit-poc/agent/main.py`：改用验证版适配器、会话预热、开场白走 generate_reply
- `livekit-poc/integration/WORKER_MIGRATION.md`：给同事 worker 的替换说明

### 旧线路（Asterisk，降级为兜底，只修稳定不修延迟）
- A1 播放移出 ws 回调线程（独立播放线程 + 有界队列）
- A2 ASR 保活 + 失败自动重建（3 次退避 + 永久放弃标志 + 会话代数校验）
- A3 speaking 状态看门狗（30s 强制回收，单线程周期检查）
- A4 TTS 降级链 + 保住 close_after（消灭装死不挂机）
- A5 打断防旧句复活（5s 时效）+ 首音 deadline 放宽到 2s
- A6 开场分类等待 7s→2.5s + partial"喂/哪位"快速放行
- A7 意向旁路捕获（线程池异步，不漏"加微信"）
- A8 打断双阈值（进入2200/维持800）+ 恢复顺延
- B1 pjsip remove_existing=yes + 注册看门狗；移除方向打反的 module reload
- B2 systemd 单元 + deploy.sh 冒烟（消灭"一改就断"/接通即挂）
- B4 trunk 可达判定修误判
- B5 Omni 探活 3s 硬超时 + autoRecovery 移出请求路径
- B9 服务器模式禁用 sidecar env 漂移 + 启动打印配置来源

## 二、测试轮次与结果（11 轮以上）

| 轮 | 方法 | 结果 |
|---|---|---|
| 1 | 全仓库 py_compile（backend+livekit-poc 所有 .py） | PASS 全部编译 |
| 2 | 回归 grep：回调链无 sleep/DB、close_after 保留、module reload 已移除 | PASS |
| 3 | 配置一致性：新增 config 项 vs .env.example；deploy.sh 语法 | PASS |
| 4 | 真实 backend venv 导入 8 个改动模块 | PASS 0 失败 |
| 5 | 微单元测试：trunk 解析(Avail/Unavail)、分类器问候判定、意向判定、关键常量 | PASS |
| 6 | 配置装载：watchdog/auto_recovery 开关、pjsip remove_existing、systemd 文件 | PASS |
| 7 | 独立子代理复审全部 diff（竞态/逻辑回归/低级错误） | 发现 2 必修 + 6 建议 |
| 8 | 修复复审发现的 8 个问题（ASR 死对象、done 错扣 job、看门狗、彩铃误判等） | PASS 全修 |
| 9 | **主线路适配器自测 ×10（VAD 800ms）** | 修前 37%，修后 **10/10 PASS** |
| 10 | 主线路适配器自测 ×5（VAD 400ms，默认参数） | **5/5 PASS** |
| 11 | 从仓库精确副本再验证 | PASS |

## 三、关键发现：间歇性"不说话"的真正根源

这是本次测试最重要的收获，也验证了"必须测 10 次以上"的要求。

**现象**：单次测试时好时坏，约 63% 概率 AI 整句无声。
**根源**：适配器里 `MessageGeneration`（携带音频流句柄）的发送依赖 `output_item.added`
事件（websocket 线程），而 generation 的创建走 `run_coroutine_threadsafe`（异步落到事件
循环线程）。两个线程无序竞争——慢的时候 `output_item.added` 先跑、generation 还没建好，
音频流句柄就丢了，模型音频照样送达适配器（日志里 audio.delta=74）却永远播不出去。
**修法**：把 `MessageGeneration` 的发送移进 generation 创建协程，与 generation_created
同在事件循环线程一次性完成，彻底消除跨线程时序依赖。
**证据**：修前自测 10 次仅 3-4 次出声；修后连续 15 次（10×800ms + 5×400ms）全部出声。

排障过程中有两次错误尝试（把创建改同步 + 延迟 emit）反而降到 0%，均已回退——记录在此
以免重蹈：不要用 call_soon_threadsafe 延迟 emit，emit 必须与 gen 创建同协程同步完成。

## 四、尚未验证的部分（诚实声明）

- 主线路只做了**自测录音验证**（模拟客户进房间录 AI 音频）。UC100 真实电话终验因当日
  测试 SIM 卡未注册上网（运营商未知/信号空白，疑似同号短呼被风控）未能完成——这是硬件/
  运营商侧问题，与代码无关。SIM 恢复后打一通即可终验。
- 旧线路 A/B 类修复通过编译、导入、单元、独立复审，但**未在真实 Asterisk 环境端到端跑过**
  （无该环境）。建议部署到 101.132.63.159 后用 deploy.sh 冒烟 + 真实拨打回归。
- 8 口鼎信网关 trunk 对接（本地用 UC100 单卡验证的是链路，非 8 路并发）。

## 五、上量前必做（今日 SIM 被风控的教训）

外呼队列必须加防封卡策略：单卡日呼上限、同号最小间隔、多卡轮换、呼叫间隔随机化。
今天同一号码一小时内十余次短呼即触发移动风控停机，8 口上量后这会比延迟更早爆发。
