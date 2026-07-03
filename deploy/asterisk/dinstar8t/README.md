# Server Asterisk + Dinstar 8T

交付推荐结构：

1. 服务器运行 Asterisk 和后端实时 AudioSocket bridge。
2. 鼎信 8T 在客户现场主动注册到服务器公网 SIP 地址。
3. 客户端只负责配置、监控、发起任务和查看通话，不依赖本机 Asterisk runtime。

关键环境变量：

```env
TELEPHONY_GATEWAY_MODE=asterisk
ASTERISK_DEPLOYMENT_MODE=server
VOICE_GATEWAY_PROFILE=dinstar_8t_server
VOICE_GATEWAY_TRUNK_NAME=dinstar8t
VOICE_GATEWAY_MAX_CHANNELS=8
ASTERISK_HOST=127.0.0.1
ASTERISK_AMI_PORT=5038
ASTERISK_AMI_USERNAME=ai_acq
ASTERISK_AMI_PASSWORD=replace-with-generated-secret
ASTERISK_ORIGINATE_CHANNEL_TEMPLATE=PJSIP/{phone}@{trunk}
ASTERISK_AUDIO_SOCKET_HOST=127.0.0.1
ASTERISK_AUDIO_SOCKET_PORT=9019
ASTERISK_LIVE_CALL_ENABLED=false
ASTERISK_BULK_CALL_ENABLED=false
```

部署顺序：

1. 安装 Asterisk。
2. 把本目录模板合并到 `/etc/asterisk/`，替换 `REPLACE_*` 占位符。
3. 打开服务器安全组/防火墙：UDP 5060、UDP 10000-20000；AMI 5038 只允许本机访问。
4. 在鼎信 8T 后台配置 SIP Server 为服务器公网 IP，账号/密码对应 `pjsip.conf` 的 `dinstar8t`。
5. 后端启动实时桥：`python -m app.tools.realtime_audio_bridge --conversation-mode omni`。
6. 前端预检必须看到 AMI 登录通过、Trunk 注册/可达、AudioSocket 在线，再做单号试拨。

安全边界：

- 不要把 `manager.conf` 和 `pjsip.conf` 的真实密码提交到 Git。
- `ASTERISK_BULK_CALL_ENABLED` 默认保持 `false`，单号试拨稳定后再人工开启。
- 鼎信 8T 的 8 路并发只是物理上限，实际频率仍要受合规、卡风控和客户授权限制。
