# 语音网关适配器说明

AI 外呼交付不要绑定某一个硬件型号。客户端交付链路统一抽象为：

```text
桌面客户端
  -> 服务器 Asterisk（默认）/ 内置 Asterisk sidecar（备选）
  -> 语音网关适配档案
  -> 运营商线路
  -> 实时 AudioSocket / ASR / Omni / TTS
```

## 当前适配档案

| profile | 用途 | 状态 |
| --- | --- | --- |
| `dinstar_8t_server` | 交付默认档案，鼎信 8T 多卡网关主动注册到服务器 Asterisk | 待客户现场验证 |
| `uc100_sip_volte` | 当前 UC100 实机测试档案，SIP 到 VoLTE/SIM 外呼 | 已实测 |
| `sip_volte_gateway` | 通用 SIP/VoLTE 语音网关 | 待现场验证 |
| `multi_sim_lte_gateway` | 多卡 GSM/LTE 语音网关 | 待现场验证 |
| `sip_trunk` | 运营商企业 SIP 中继 | 待现场验证 |

## 通用配置

后端 `.env` 使用：

```bash
ASTERISK_DEPLOYMENT_MODE=server
VOICE_GATEWAY_PROFILE=dinstar_8t_server
VOICE_GATEWAY_LABEL=鼎信 8T 多卡网关（服务器 Asterisk）
VOICE_GATEWAY_VENDOR=Dinstar/鼎信
VOICE_GATEWAY_MODEL=8T GSM/LTE VoIP Gateway
VOICE_GATEWAY_CATEGORY=multi_sim_lte_gateway
VOICE_GATEWAY_TRANSPORT=sip_udp_server_registered
VOICE_GATEWAY_LINE_TYPE=multi_sim_cellular
VOICE_GATEWAY_HOST=
VOICE_GATEWAY_SIP_PORT=5060
VOICE_GATEWAY_TRUNK_NAME=dinstar8t
VOICE_GATEWAY_MAX_CHANNELS=8
VOICE_GATEWAY_ADMIN_URL=
VOICE_GATEWAY_DISCOVERY_MODE=gateway_registers_to_server
```

客户端内置 Asterisk 备选模式才使用同语义的 `AI_ACQ_VOICE_GATEWAY_*` 变量：

```bash
AI_ACQ_VOICE_GATEWAY_PROFILE=uc100_sip_volte
AI_ACQ_VOICE_GATEWAY_LABEL=语音网关（UC100 测试档案）
AI_ACQ_VOICE_GATEWAY_HOST=192.168.10.100
AI_ACQ_VOICE_GATEWAY_SIP_PORT=5080
AI_ACQ_VOICE_GATEWAY_SIP_USERNAME=1000
AI_ACQ_VOICE_GATEWAY_SIP_PASSWORD=现场密码
AI_ACQ_VOICE_GATEWAY_TRUNK_NAME=uc100
AI_ACQ_VOICE_GATEWAY_MAX_CHANNELS=1
```

旧的 `AI_ACQ_UC100_*` 变量仍是兼容别名，只用于当前 UC100 测试档案。

## 服务器 Asterisk 默认交付

鼎信 8T 交付时推荐让网关主动注册到服务器：

1. 服务器部署 Asterisk、后端 API、实时 AudioSocket bridge。
2. 服务器安全组放行 UDP 5060 和 RTP 10000-20000；AMI 5038 只监听 127.0.0.1。
3. 服务器后台按客户、按设备预生成语音网关线路配置卡。每条线路都有独立 SIP User、Auth User、密码、trunk 和通道数。
4. 交付电脑在客户现场发现设备后台地址后，把当前后台地址、MAC、序列号回写到对应线路；这个地址只用于现场管理，云端不依赖它完成拨号。
5. 鼎信 8T 后台配置 SIP Server 为服务器公网 IP，账号/密码匹配这条线路的配置卡。
6. 后端 `.env` 里 `ASTERISK_HOST=127.0.0.1`，因为后端和 Asterisk 在同一台服务器。
7. 前端预检通过 AMI、Trunk、AudioSocket 后，再做单号试拨。

### 多客户/多设备预配置

正式交付不要复用测试 trunk。服务器后台支持先为多个客户、多台设备批量预生成线路：

```text
客户A / 门店1 / 鼎信8T -> sip_a_xxx / tg_a_xxx / 8通道
客户A / 门店2 / 鼎信8T -> sip_a_yyy / tg_a_yyy / 8通道
客户B / 总部 / 通用语音网关 -> sip_b_zzz / tg_b_zzz / 4通道
```

到现场后只需要做两件事：

1. 找到这台设备的本地管理后台地址，并回写到对应线路。
2. 按配置卡把 SIP 注册和路由填进设备后台。

设备后台地址会随客户网络变化；长期识别应依赖客户、线路、设备 MAC/序列号和云端 SIP 注册结果，而不是依赖某个固定 `192.168.x.x`。

## 换网络后的处理

服务器 Asterisk 模式下，客户现场网关 IP 不再作为系统永久地址；只要鼎信 8T 能访问服务器公网 SIP/RTP，换网络后重新注册即可。

客户端内置 Asterisk 备选模式才需要处理现场网关 IP 变化：

正确流程：

1. 客户端发现当前局域网网段。
2. 扫描可能的网关管理端口和 SIP 端口。
3. 用设备型号、MAC、序列号、SIP 注册结果识别已绑定设备。
4. 更新当前 `VOICE_GATEWAY_HOST` / `SIP_PORT`。
5. 重新生成 Asterisk sidecar 配置。
6. 重新跑 `python -m app.tools.voice_gateway_preflight --phone <测试号码>`。

## 并发原则

并发按真实线路通道算，不按页面宣传值直接算：

- 单 SIM / 单 VoLTE 通道：通常 1 路。
- 多卡网关：最多等于可用 SIM/蜂窝模块数。
- SIP 中继：按运营商合同并发数。

`ASTERISK_BULK_CALL_ENABLED` 必须等单号实时通话稳定后才能开启。
