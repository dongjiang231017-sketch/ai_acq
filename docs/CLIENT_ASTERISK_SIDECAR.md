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

正式安装包必须把 Asterisk runtime 放到 Electron resources 中，例如：

```text
resources/asterisk/bin/asterisk
```

客户端会优先查找：

1. `AI_ACQ_ASTERISK_BIN`
2. `process.resourcesPath/asterisk/bin/asterisk`
3. `frontend/electron/asterisk/<platform>/bin/asterisk`
4. 系统 PATH 中的 `asterisk`

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
