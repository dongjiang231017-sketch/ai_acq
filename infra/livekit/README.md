# 本地自部署 LiveKit 外呼

这套配置用于本地开发/联调：

- `livekit`: 自部署 LiveKit server，监听 `ws://127.0.0.1:7880`
- `sip`: 自部署 LiveKit SIP，监听本机 `5062/udp`
- `redis`: LiveKit 与 SIP 共用状态

本机 Asterisk 已占用 `5060/udp`，所以本地 LiveKit SIP 使用 `5062/udp`。出站 trunk 仍然拨到 8T：`192.168.10.114:5060`。

启动：

```bash
./scripts/livekit-selfhost-up.sh
```

查看日志：

```bash
docker compose -f infra/livekit/docker-compose.yml logs -f livekit sip
tail -f /tmp/ai-acq-livekit-agent.log
```

本地开发默认 API key/secret：

```text
LIVEKIT_URL=ws://127.0.0.1:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devsecret-key-for-ai-acq-local-20260709
```

生产部署到公网服务器时，不要直接使用这里的 dev key/secret。需要换成自己的强随机 key/secret，并开放：

- LiveKit HTTP/WebSocket: `7880/tcp`
- LiveKit TCP fallback: `7881/tcp`
- LiveKit RTC UDP: `50000-50100/udp` 或更大的端口段
- LiveKit SIP: `5060/udp`
- LiveKit SIP RTP: `10000-20000/udp` 或配置中的端口段
