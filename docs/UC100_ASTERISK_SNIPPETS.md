# UC100 / Asterisk 配置样例

这份样例用于把 UC100 作为客户端内置 Asterisk sidecar 的 `PJSIP` trunk，再由 AI 外呼系统通过本机 AMI 提交 `Originate`。

实际字段会因 UC100 固件和现场网络不同而变化。客户交付版优先由桌面客户端生成配置和 AMI 密钥；手工调试时请把 `UC100_IP`、`AMI_PASSWORD`、`UC100_SIP_USER`、`UC100_SIP_PASSWORD` 替换为现场值，不要提交真实密码。

## 1. manager.conf

```ini
[general]
enabled = yes
webenabled = no
port = 5038
bindaddr = 127.0.0.1

[ai_acq]
secret = AMI_PASSWORD
read = system,call,command,agent,user,originate
write = system,call,command,agent,user,originate
; 客户端 sidecar 只允许客户电脑本机后端访问
permit = 127.0.0.1/255.255.255.255
```

对应 `backend/.env`：

```env
ASTERISK_AMI_USERNAME=ai_acq
ASTERISK_AMI_PASSWORD=AMI_PASSWORD
ASTERISK_AMI_PORT=5038
```

## 2. pjsip.conf：Asterisk 主动呼叫 UC100 IP

如果 UC100 在局域网有固定 IP，且客户端内置 Asterisk 直接把呼叫送到 UC100：

```ini
[transport-udp]
type = transport
protocol = udp
bind = 0.0.0.0:5060

[uc100]
type = endpoint
transport = transport-udp
context = from-uc100
disallow = all
allow = alaw,ulaw
aors = uc100
outbound_auth = uc100-auth
from_user = UC100_SIP_USER

[uc100]
type = aor
; 当前 UC100 实机 WAN SIP 常见监听是 5080；如果接 UC100 LAN 侧再改为 5060。
contact = sip:UC100_IP:5080
qualify_frequency = 30

[uc100-auth]
type = auth
auth_type = userpass
username = UC100_SIP_USER
password = UC100_SIP_PASSWORD

[uc100]
type = identify
endpoint = uc100
match = UC100_IP
```

对应系统默认拨号通道：

```env
ASTERISK_TRUNK_NAME=uc100
ASTERISK_ORIGINATE_CHANNEL_TEMPLATE=PJSIP/{phone}@{trunk}
```

## 3. pjsip.conf：UC100 注册到 Asterisk

如果 UC100 配置为向客户端内置 Asterisk 注册，常见写法是：

```ini
[uc100]
type = endpoint
transport = transport-udp
context = from-uc100
disallow = all
allow = alaw,ulaw
auth = uc100-auth
aors = uc100

[uc100-auth]
type = auth
auth_type = userpass
username = UC100_SIP_USER
password = UC100_SIP_PASSWORD

[uc100]
type = aor
max_contacts = 1
remove_existing = yes
qualify_frequency = 30
```

## 4. extensions.conf

第一阶段只是验证真实线路能拨通。被叫接通后进入 `from-ai-acq,s,1`：

```ini
[from-ai-acq]
exten => s,1,NoOp(AI ACQ originated call answered)
 same => n,Answer()
 same => n,Wait(1)
 same => n,Playback(hello-world)
 same => n,Hangup()

[from-uc100]
exten => _X.,1,NoOp(Inbound call from UC100: ${CALLERID(all)})
 same => n,Hangup()
```

后续接实时 ASR/TTS 时，再把 `Playback(hello-world)` 换成音频桥接、ARI/ExternalMedia 或其它实时媒体方案。

## 5. Asterisk CLI 检查

```bash
asterisk -rx "manager show users"
asterisk -rx "pjsip show endpoint uc100"
asterisk -rx "pjsip show contacts"
asterisk -rx "dialplan show from-ai-acq"
```

手动 originate 测试：

```bash
asterisk -rx "channel originate PJSIP/你的测试手机号@uc100 extension s@from-ai-acq"
```

如果这条命令不能让手机响铃，先修客户端 sidecar、UC100、SIM 卡链路，不要改 AI 外呼系统。

## 6. 系统预检

```bash
cd backend
source .venv/bin/activate
python -m app.tools.uc100_preflight --phone 你的测试手机号
```

预检全部通过后，再启动后端并打开 AI 外呼系统里的 `真实线路接入` 面板做单号试拨。
