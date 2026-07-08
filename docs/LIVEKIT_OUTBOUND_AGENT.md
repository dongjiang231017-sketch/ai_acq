# LiveKit Agent 外呼切换说明

当前 AudioSocket / Omni 真实拨测仍出现卡顿、误打断和声音链路不稳定后，正式外呼路线切到 LiveKit Agent。

## 需要配置

在 `backend/.env` 填入：

```env
REALTIME_CONVERSATION_MODE=livekit
LIVEKIT_URL=wss://你的-livekit-host
LIVEKIT_API_KEY=你的-key
LIVEKIT_API_SECRET=你的-secret
LIVEKIT_AGENT_NAME=ai-acq-outbound-agent
LIVEKIT_SIP_OUTBOUND_TRUNK_ID=你的-outbound-trunk-id
LIVEKIT_SIP_FROM_NUMBER=可选主叫号码
LIVEKIT_AGENT_MODE=openai_realtime
OPENAI_API_KEY=你的-openai-key
```

如果不用 OpenAI 官方 Realtime，而是使用 Qwen-Omni-Realtime，可改成：

```env
LIVEKIT_AGENT_MODE=openai_realtime
LIVEKIT_OPENAI_REALTIME_MODEL=qwen3.5-omni-plus-realtime
LIVEKIT_OPENAI_REALTIME_VOICE=Serena
LIVEKIT_OPENAI_REALTIME_BASE_URL=wss://dashscope.aliyuncs.com/api-ws/v1/realtime
LIVEKIT_OPENAI_REALTIME_API_KEY=你的-dashscope-key
```

`LIVEKIT_OPENAI_REALTIME_*` 使用 LiveKit 的 OpenAI-compatible Realtime 插件；字段名保留 OpenAI 是为了表示协议兼容层，不代表只能使用 OpenAI 官方服务。
如果后台「模型配置」里已经保存了 `dashscope_api_key`、`dashscope_omni_realtime_url`、`dashscope_omni_realtime_model` 和 `dashscope_omni_realtime_voice`，LiveKit Agent 会优先读取数据库里的 Qwen Omni Realtime 配置，不需要把百炼 key 再写入 `.env`。

如果不用实时大模型一体化路线，可改成：

```env
LIVEKIT_AGENT_MODE=inference
LIVEKIT_AGENT_STT_MODEL=deepgram/flux-general-multi
LIVEKIT_AGENT_STT_LANGUAGE=multi
LIVEKIT_AGENT_LLM_MODEL=openai/gpt-5-mini
LIVEKIT_AGENT_TTS_MODEL=elevenlabs/eleven_multilingual_v2
LIVEKIT_AGENT_TTS_VOICE=你的多语言音色ID
```

## 启动 Agent worker

```bash
cd backend
source .venv/bin/activate
python -m app.tools.livekit_outbound_agent dev
```

这个进程替代旧的：

```bash
python -m app.tools.realtime_audio_bridge --conversation-mode omni
```

## 单号试拨

后端启动后：

```bash
curl -X POST http://localhost:8001/api/outbound/telephony/test-call \
  -H 'Content-Type: application/json' \
  -d '{"phone":"18107090349","conversationRoute":"livekit"}'
```

前端「电话线路」里的实时路线也可以直接选 `LiveKit Agent 外呼`。

## 直连鼎信 8T 的网络要求

如果不经过 Asterisk/SBC，而是让 LiveKit Cloud 直接呼叫鼎信 8T，`LIVEKIT_SIP_OUTBOUND_TRUNK_ID`
对应的 outbound trunk `address` 必须是 LiveKit Cloud 能访问到的公网 SIP 地址，例如：

```text
公网IP或域名:5060
```

这个地址会收到 LiveKit 发出的 SIP INVITE。只把 8T 的「SIP 代理」改成 LiveKit 域名还不够，因为 outbound
方向仍然需要 LiveKit 主动连到 8T。路由器/防火墙至少要放通并转发：

- UDP 5060 到 8T 的 SIP 端口。
- 8T 配置的 RTP UDP 端口段到 8T。

诊断方式：

```bash
python - <<'PY'
import socket, uuid
host = "公网IP或域名"
msg = (
    f"OPTIONS sip:{host} SIP/2.0\r\n"
    f"Via: SIP/2.0/UDP 0.0.0.0:5062;branch=z9hG4bK{uuid.uuid4().hex[:12]};rport\r\n"
    "Max-Forwards: 70\r\n"
    f"From: <sip:probe@ai-acq>;tag={uuid.uuid4().hex[:8]}\r\n"
    f"To: <sip:{host}>\r\n"
    f"Call-ID: {uuid.uuid4().hex}@ai-acq-probe\r\n"
    "CSeq: 1 OPTIONS\r\n"
    "Contact: <sip:probe@0.0.0.0:5062>\r\n"
    "Content-Length: 0\r\n\r\n"
).encode()
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(5)
s.sendto(msg, (host, 5060))
print(s.recvfrom(4096)[0].decode(errors="replace"))
PY
```

如果本地局域网 `192.168.x.x:5060` 能返回 `SIP/2.0 200 OK`，但公网地址没有任何响应，说明代码、
LiveKit worker 和 8T SIP 服务本身没卡住，问题在公网端口转发/NAT。

## 当前架构

1. 后端创建 LiveKit Agent dispatch，并把手机号、room、SIP trunk 等写入 metadata。
2. `livekit_outbound_agent` worker 收到 dispatch，先进入 room 并启动 `AgentSession`。
3. worker 通过 LiveKit SIP outbound trunk 创建电话 participant。
4. 客户接通后，LiveKit 在同一个 room 内处理 VAD、打断、端点检测、转写、LLM/TTS 或 OpenAI Realtime。
5. 实时事件继续写入 `REALTIME_CALL_EVENT_LOG_PATH`，前端仍读同一份 live-events。

入呼直连也使用同一个 worker。LiveKit SIP inbound trunk 的 dispatch rule 需要在 `room_config.agents`
里指定 `ai-acq-outbound-agent`，这样 8T 发 INVITE 到 LiveKit SIP URI 后，LiveKit 会自动把 Agent 拉进房间接听。
