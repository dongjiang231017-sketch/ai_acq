# 客户端内置 Asterisk sidecar

AI 外呼系统的客户交付形态是：客户安装桌面客户端，客户端在客户电脑本机启动并管理 Asterisk sidecar，后端只连接 `127.0.0.1` 的 AMI。开发者本机只能作为联调环境，不能成为客户现场运行前提。

## 客户现场链路

```text
客户桌面客户端
  -> 内置 Asterisk sidecar
  -> 语音网关 SIP 监听地址
  -> VoLTE / SIM 卡 / 多卡蜂窝线路 / SIP 中继
  -> 被叫手机
```

默认 sidecar 会生成：

- Asterisk 配置目录：客户端用户数据目录下的 `asterisk-sidecar/etc`
- AMI 账号和随机密码：客户端用户数据目录下的 `asterisk-sidecar/state/sidecar.json`
- 后端环境文件：客户端用户数据目录下的 `asterisk-sidecar/state/backend-asterisk.env`
- 默认 AMI：`127.0.0.1:5038`
- 默认 SIP：`0.0.0.0:5060/udp`
- 默认语音网关目标：`192.168.10.100:5080`（UC100 测试档案）
- 默认 trunk：`uc100`
- 默认并发：`1` 路
- 默认实时媒体桥：`127.0.0.1:9019`

`backend-asterisk.env` 含有客户本机 AMI 密钥，只能留在客户电脑本地，不要提交到 Git，也不要截图给客户群。

## 开发和正式安装包差异

开发模式下，如果没有随客户端打包 Asterisk binary，外呼页会显示“缺少运行时”。可以临时设置：

```bash
AI_ACQ_ASTERISK_BIN=/absolute/path/to/asterisk npm run desktop
```

正式安装包必须把 Asterisk runtime 放到 Electron resources 中，并且必须包含 `binary + modules`，不是只放一个 `asterisk` 可执行文件。例如：

```text
resources/asterisk/darwin/bin/asterisk
resources/asterisk/darwin/lib/asterisk/modules/app_audiosocket.so
resources/asterisk/darwin/lib/asterisk/modules/res_pjsip.so
resources/asterisk/darwin/lib/asterisk/modules/res_pjsip_outbound_registration.so
resources/asterisk/darwin/lib/asterisk/modules/chan_pjsip.so
```

客户端会优先查找：

1. `AI_ACQ_ASTERISK_BIN`
2. `process.resourcesPath/asterisk/<platform>/bin/asterisk`
3. `process.resourcesPath/asterisk/bin/asterisk`
4. `frontend/electron/asterisk/<platform>/bin/asterisk`
5. `frontend/electron/asterisk/bin/asterisk`
6. 系统 PATH 中的 `asterisk`

正式打包命令：

```bash
cd frontend
npm run desktop:runtime:prepare
npm run desktop:runtime:check
npm run desktop:dist
```

`desktop:runtime:prepare` 会从以下来源复制 runtime 到 `frontend/electron/asterisk/<platform>`：

- `AI_ACQ_ASTERISK_RUNTIME_SOURCE=/path/to/asterisk-prefix`
- `AI_ACQ_ASTERISK_BIN=/path/to/asterisk`
- 系统 PATH 中的 `asterisk`

如果 modules 不在标准目录，额外设置：

```bash
AI_ACQ_ASTERISK_MODULE_DIR=/path/to/lib/asterisk/modules
```

`desktop:runtime:check` 会强制检查：

- `bin/asterisk`
- `app_audiosocket.so`
- `res_pjsip.so`
- `res_pjsip_outbound_registration.so`
- `chan_pjsip.so`

检查不通过时，正式安装包不能打出。这样客户不会拿到一个只能显示页面、不能启动本机 Asterisk 的半成品。

当前开发机可以继续用 Docker Asterisk 做联调，但 Docker 不能作为客户安装包的一部分，也不能作为客户现场运行前提。macOS 上如果没有可用的原生 Asterisk runtime，需要先准备一份可重分发的 macOS Asterisk runtime，再执行上面的 prepare/check/dist。

## 语音网关适配边界

UC100 是当前实机验证的测试档案。正式交付时可以替换为其他 SIP/VoLTE 网关、多卡 GSM/LTE 网关、FXO/FXS 网关或运营商 SIP 中继。客户端 sidecar 只要求最终能得到一个 Asterisk 可用的 SIP trunk、线路通道数和媒体桥。

设备后台地址会随客户网络变化。交付版应优先通过客户端的语音网关发现/绑定向导记录设备型号、MAC/序列号、当前 IP、SIP 端口和 trunk，而不是把某个 `192.168.x.x` 写死。

当前 UC100 实机已验证 WAN 地址可访问，移动卡在线后页面显示 `VoLTE网络 / 在线`。客户现场建议固定或保留语音网关局域网地址，并让客户端 sidecar 的语音网关目标指向设备 SIP 监听端口。

当前设备状态页显示 SIP 监听：

- `wan_default`: `192.168.10.100:5080`
- `lan_default`: `192.168.11.1:5060`

客户电脑和语音网关在同一上级网络时，优先使用设备的 WAN/LAN SIP 地址。如果客户改了设备地址，需要用通用环境变量覆盖：

```bash
AI_ACQ_VOICE_GATEWAY_PROFILE=uc100_sip_volte
AI_ACQ_VOICE_GATEWAY_LABEL=语音网关（UC100 测试档案）
AI_ACQ_VOICE_GATEWAY_HOST=客户现场语音网关地址
AI_ACQ_VOICE_GATEWAY_SIP_PORT=5080
```

旧版 `AI_ACQ_UC100_HOST` / `AI_ACQ_UC100_SIP_PORT` 仍可作为 UC100 兼容别名，但新交付优先使用 `AI_ACQ_VOICE_GATEWAY_*`。

如果客户电脑接的是 UC100 `WAN` 地址 `192.168.10.100:5080`，UC100 后台的 `分机 / SIP` 必须把 AI 分机的 `SIP配置` 选成 `2-< wan_default >`。如果接 UC100 `LAN` 地址 `192.168.11.1:5060`，才选 `1-< lan_default >`。选错会出现 Asterisk 能收到 401 challenge、但认证后被 UC100 返回 `403 Forbidden`。

需要 Asterisk 主动注册到 UC100 分机时，在启动桌面客户端前提供：

```bash
AI_ACQ_VOICE_GATEWAY_SIP_USERNAME=语音网关SIP账号
AI_ACQ_VOICE_GATEWAY_SIP_PASSWORD=语音网关SIP密码
AI_ACQ_ASTERISK_ADVERTISED_HOST=客户电脑局域网IP
AI_ACQ_ASTERISK_LOCAL_NET=172.16.0.0/12
```

`AI_ACQ_ASTERISK_ADVERTISED_HOST` 只在 Asterisk 运行在容器或网关看不到真实回连地址时需要；原生本机 Asterisk 通常可以留空。

### 换网络后的自动匹配

桌面客户端每次刷新 sidecar 状态或启动内置 Asterisk 时，会先检查当前 `voiceGatewayHost:sipPort` 是否可达。如果旧地址不可达，客户端会扫描当前电脑所在局域网，优先识别 UC100/语音网关后台页面，也会检查 SIP 端口；发现新地址后会自动更新 sidecar state，重写 `pjsip.conf` 和 `backend-asterisk.env`。如果 Asterisk 已经运行，会尝试热重载 `pjsip reload` 和 `dialplan reload`。

可选调参：

```bash
AI_ACQ_VOICE_GATEWAY_AUTO_DISCOVERY=true
AI_ACQ_VOICE_GATEWAY_HTTP_PORT=80
AI_ACQ_VOICE_GATEWAY_DISCOVERY_TIMEOUT_MS=420
AI_ACQ_VOICE_GATEWAY_DISCOVERY_CONCURRENCY=48
```

需要完全固定现场地址时可设 `AI_ACQ_VOICE_GATEWAY_AUTO_DISCOVERY=false`。

## 客户交付 SOP

交付给客户时不要让客户打开开发者网页预览或依赖开发机 Docker。标准路径是：

1. 客户电脑安装桌面客户端。
2. 语音网关和客户电脑接入同一个局域网，语音网关插卡并确认蜂窝/VoLTE 在线。
3. 客户打开 `AI外呼系统 -> 实时监听 -> 真实线路接入`。
4. 客户端自动发现或重新确认语音网关地址，并在 `客户交付状态` 中显示当前绑定地址、上一地址和自动匹配结果。
5. 客户点击 `启动内置Asterisk`，客户端生成本机 AMI 密钥、Asterisk 配置和后端环境文件。
6. 客户点击 `预检线路`，必须看到 AMI、Trunk、单号试拨开关通过。
7. 只做单号真实拨测。页面必须同时确认蜂窝侧、实时媒体桥、真人语音和 AI 首句，才算实时通话验收通过。
8. 单号稳定前，`ASTERISK_BULK_CALL_ENABLED` 必须保持关闭。

换网络时，客户不应该重新找代码或手改 `.env`。桌面客户端刷新 sidecar 状态后会重新扫描局域网；如果 `客户交付状态` 显示 `没有在当前网络发现语音网关`，现场只需要按提示检查三件事：客户电脑和网关是否同网段、网关是否通电/网线正确、后台页面能否从客户电脑打开。

如果页面只显示 `网关侧响应，未证明手机响铃`，说明 Asterisk/SIP 已经把呼叫交给语音网关，但没有进入蜂窝接通和实时媒体层。这时优先检查网关后台的当前呼叫/话单、SIM 状态、运营商线路、SIP 分机到 VoLTE 的路由规则，而不是调整 AI/ASR/TTS 代码。

### `RINGING/PROGRESS` 但没有 AudioSocket 的处理

`RINGING/PROGRESS` 是接通前状态。此时 Asterisk 还没有执行 `[from-ai-acq]` 里的 `AudioSocket(...)`，所以不能通过改 ASR、LLM、TTS 或打断逻辑解决。

排查顺序：

1. 确认 Asterisk trunk 注册：`pjsip show registrations` 必须是 `Registered`，`pjsip show contacts` 必须是 `Avail`。
2. 前端单号试拨后，立即打开语音网关后台 `当前呼叫` 或 `话单`。
3. 如果话单没有 VoLTE 蜂窝呼出记录，检查 SIP 分机到 VoLTE 的路由来源是否是 `SIP分机 / AI_ACQ_Asterisk / 1000`，不是 `SIP中继`。
4. 如果话单有记录但时长 `0`，原因是 `通道不可用`、`CONGESTION` 或类似错误，优先处理 SIM/VoLTE/运营商通道：重连 VoLTE、重启网关、换卡、确认号码是否被运营商或手机侧拦截。
5. 如果手机真实响铃并接通，Asterisk 才会进入 `[from-ai-acq]`，然后应看到非空 `AudioSocket callId`、`call_connected`、ASR/TTS/打断事件。

所以：

- `接通后没 AI`：先查桌面 sidecar 的 `extensions.conf` 是否包含 `AudioSocket(...)`。
- `一直 RINGING/PROGRESS`：先查语音网关话单和蜂窝通道，不是 AI 链路问题。

## 安全开关

内置 Asterisk 启动不等于允许真实外呼。真实拨号仍受后端开关保护：

- `ASTERISK_LIVE_CALL_ENABLED=true` 只开放单号试拨
- `ASTERISK_BULK_CALL_ENABLED=true` 才开放批量任务真实拨号

交付前必须先完成无拨号预检，再由客户明确确认单号试拨号码。

## 实时媒体桥

sidecar 的拨号上下文会在电话接通后执行：

```text
Set(AI_ACQ_CALL_UUID=${UUID()})
AudioSocket(${AI_ACQ_CALL_UUID},127.0.0.1:9019)
```

后端实时桥由客户本机 Python 后端启动：

```bash
cd backend
source .venv/bin/activate
python -m app.tools.realtime_audio_bridge --check
python -m app.tools.realtime_audio_bridge
```

`--check` 只打印非密钥配置，不拨号、不监听电话。正式监听时会把事件写入 `REALTIME_CALL_EVENT_LOG_PATH`，默认 `/tmp/ai-acq-realtime-call-events.jsonl`。

实时桥启动需要：

- `DASHSCOPE_API_KEY` 已配置。
- `DEEPSEEK_API_KEY` 已配置时，实时桥会使用 DeepSeek 生成电话短句；未配置时走本地规则兜底。
- 每通电话使用 Asterisk `${UUID()}` 生成独立 `callId`，接通、ASR、TTS、打断、挂断事件都按该 `callId` 串联。
- 至少一个可用的实时 TTS voice：优先 `REALTIME_TTS_VOICE_ID`，否则使用声音档案中最新的可用复刻 `external_voice_id`。
- `ASTERISK_AUDIO_SOCKET_HOST` 和 `ASTERISK_AUDIO_SOCKET_PORT` 与 sidecar 生成的 `backend-asterisk.env` 一致。

如果外呼页的 `客户端内置 Asterisk` 检查显示 AMI 已运行但 `实时媒体桥` 是 WARN，说明 Asterisk 能拨号，但接通后还不能把电话音频送进 ASR/TTS 回路。
