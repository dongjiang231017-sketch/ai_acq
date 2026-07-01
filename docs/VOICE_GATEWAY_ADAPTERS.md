# 语音网关适配器说明

AI 外呼交付不要绑定某一个硬件型号。客户端交付链路统一抽象为：

```text
桌面客户端
  -> 内置 Asterisk sidecar
  -> 语音网关适配档案
  -> 运营商线路
  -> 实时 AudioSocket / ASR / Omni / TTS
```

## 当前适配档案

| profile | 用途 | 状态 |
| --- | --- | --- |
| `uc100_sip_volte` | 当前 UC100 实机测试档案，SIP 到 VoLTE/SIM 外呼 | 已实测 |
| `sip_volte_gateway` | 通用 SIP/VoLTE 语音网关 | 待现场验证 |
| `multi_sim_lte_gateway` | 多卡 GSM/LTE 语音网关 | 待现场验证 |
| `sip_trunk` | 运营商企业 SIP 中继 | 待现场验证 |

## 通用配置

后端 `.env` 使用：

```bash
VOICE_GATEWAY_PROFILE=uc100_sip_volte
VOICE_GATEWAY_LABEL=语音网关（UC100 测试档案）
VOICE_GATEWAY_VENDOR=ZHY
VOICE_GATEWAY_MODEL=UC100
VOICE_GATEWAY_CATEGORY=sip_volte_gateway
VOICE_GATEWAY_TRANSPORT=sip_udp
VOICE_GATEWAY_LINE_TYPE=sim_volte
VOICE_GATEWAY_HOST=192.168.10.100
VOICE_GATEWAY_SIP_PORT=5080
VOICE_GATEWAY_TRUNK_NAME=uc100
VOICE_GATEWAY_MAX_CHANNELS=1
VOICE_GATEWAY_ADMIN_URL=
VOICE_GATEWAY_DISCOVERY_MODE=manual_or_lan_scan
```

桌面 sidecar 使用同语义的 `AI_ACQ_VOICE_GATEWAY_*` 变量：

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

## 换网络后的处理

语音网关后台 IP 会随客户网络变化。交付版不能把 `192.168.x.x` 当作永久地址。

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
