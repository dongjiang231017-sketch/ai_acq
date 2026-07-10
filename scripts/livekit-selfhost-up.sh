#!/usr/bin/env bash
# 自建 LiveKit 外呼链路一键启动（2026-07-09 验证过的配置）
# 链路：后端(8001) -> LiveKit Server(Docker 7880) -> livekit-sip(Mac 本机进程 5062/udp)
#       -> 鼎信 8T 网关(192.168.10.114:5060) -> SIM 外呼
# 注意：SIP 必须跑本机进程，不能跑 Docker（Docker bridge 会导致 RTP media-timeout）。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/livekit/docker-compose.yml"
LOG_DIR="$ROOT_DIR/logs"
SIP_BIN="${LK_SIP_BIN:-/tmp/ai-acq-go-bin/livekit-sip}"
SIP_CONF="$ROOT_DIR/infra/livekit/sip-native.yaml"
TRUNK_ADDRESS="${TRUNK_ADDRESS:-192.168.10.114:5060}"
FROM_NUMBER="${FROM_NUMBER:-+8617750280920}"
LK_API_KEY="devkey"
LK_API_SECRET="devsecret-key-for-ai-acq-local-20260709"

mkdir -p "$LOG_DIR"

# ---------- 0. 本机局域网 IP（SIP 信令/媒体公告地址，必须是鼎信可达的地址） ----------
LAN_IP="${LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)}"
if [[ -z "$LAN_IP" ]]; then
  echo "无法检测局域网 IP，请手动指定：LAN_IP=192.168.10.147 $0" >&2
  exit 1
fi
echo "本机局域网 IP: ${LAN_IP}"

# ---------- 1. Docker：只起 redis + livekit-server，明确停掉 Docker 版 SIP ----------
if ! docker info >/dev/null 2>&1; then
  [[ "$(uname)" == "Darwin" ]] && open -a Docker || true
  echo "等待 Docker 启动..."
  for _ in $(seq 1 90); do
    docker info >/dev/null 2>&1 && break
    sleep 2
  done
fi
docker info >/dev/null 2>&1 || { echo "Docker 未启动，请先打开 Docker Desktop。" >&2; exit 1; }

docker compose -f "$COMPOSE_FILE" up -d redis livekit
docker compose -f "$COMPOSE_FILE" stop sip >/dev/null 2>&1 || true

echo "等待 LiveKit server 监听 7880..."
for _ in $(seq 1 90); do
  nc -z 127.0.0.1 7880 >/dev/null 2>&1 && { echo "LiveKit server 已监听 127.0.0.1:7880"; break; }
  sleep 1
done
nc -z 127.0.0.1 7880 || { echo "LiveKit server 启动超时，请看 docker compose 日志。" >&2; exit 1; }

# ---------- 2. 本机 livekit-sip：没有就编译 ----------
if [[ ! -x "$SIP_BIN" ]]; then
  echo "未找到本机 livekit-sip（$SIP_BIN），开始编译..."
  command -v go >/dev/null 2>&1 || { echo "缺少 Go，请先 brew install go" >&2; exit 1; }
  HOMEBREW_NO_AUTO_UPDATE=1 brew install opusfile libsoxr >/dev/null 2>&1 || true
  PKG_CONFIG_PATH="/opt/homebrew/lib/pkgconfig:/opt/homebrew/opt/libsoxr/lib/pkgconfig:/opt/homebrew/opt/opusfile/lib/pkgconfig:/opt/homebrew/opt/opus/lib/pkgconfig" \
    GOPROXY=https://goproxy.cn,direct \
    GOBIN="$(dirname "$SIP_BIN")" \
    go install github.com/livekit/sip/cmd/livekit-sip@latest
fi
echo "livekit-sip 二进制：$SIP_BIN"

# ---------- 3. 生成本机 SIP 配置（关键：公告局域网 IP，解决 RTP 回流） ----------
cat > "$SIP_CONF" <<EOF
ws_url: ws://127.0.0.1:7880
api_key: $LK_API_KEY
api_secret: $LK_API_SECRET
redis:
  address: 127.0.0.1:6379
sip_port: 5062
sip_port_listen: 5062
sip_hostname: $LAN_IP
listen_ip: 0.0.0.0
local_net: ${LAN_IP%.*}.0/24
nat_1_to_1_ip: $LAN_IP
media_nat_1_to_1_ip: $LAN_IP
rtp_port: 10000-10100
use_external_ip: false
media_use_external_ip: false
symmetric_rtp: true
ignore_local_addr_in_sdp: true
media_timeout_initial: 60s
logging:
  level: info
EOF

# ---------- 4. 重启本机 SIP 进程（清干净旧的） ----------
screen -S ai-acq-livekit-sip -X quit >/dev/null 2>&1 || true
pkill -f "$SIP_BIN" >/dev/null 2>&1 || true
sleep 1
screen -dmS ai-acq-livekit-sip zsh -lc "'$SIP_BIN' --config '$SIP_CONF' > '$LOG_DIR/livekit-sip-native.log' 2>&1"
sleep 3
if ! pgrep -f "$SIP_BIN" >/dev/null; then
  echo "本机 livekit-sip 启动失败，日志：$LOG_DIR/livekit-sip-native.log" >&2
  tail -n 30 "$LOG_DIR/livekit-sip-native.log" >&2 || true
  exit 1
fi
echo "本机 livekit-sip 已启动: 5062/udp, 公告 ${LAN_IP}"

# ---------- 5. 创建/复用 outbound trunk，并写入 backend/.env ----------
cd "$ROOT_DIR/backend"
source .venv/bin/activate
python -m app.tools.livekit_selfhost_bootstrap \
  --livekit-url ws://127.0.0.1:7880 \
  --api-key "$LK_API_KEY" \
  --api-secret "$LK_API_SECRET" \
  --trunk-address "$TRUNK_ADDRESS" \
  --from-number "$FROM_NUMBER" \
  --write-env

# ---------- 6. 后端：不健康才重启（RESTART_BACKEND=1 强制重启） ----------
backend_healthy() { curl -sf -m 3 http://127.0.0.1:8001/api/health >/dev/null 2>&1; }
if [[ "${RESTART_BACKEND:-0}" == "1" ]] || ! backend_healthy; then
  pkill -f "uvicorn app.main:app" >/dev/null 2>&1 || true
  screen -S ai-acq-backend -X quit >/dev/null 2>&1 || true
  sleep 1
  screen -dmS ai-acq-backend zsh -lc "cd '$ROOT_DIR/backend' && source .venv/bin/activate && uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 > '$LOG_DIR/backend.log' 2>&1"
  for _ in $(seq 1 30); do backend_healthy && break; sleep 1; done
fi
backend_healthy && echo "后端健康：http://127.0.0.1:8001" || { echo "后端未就绪，日志：$LOG_DIR/backend.log" >&2; exit 1; }

# ---------- 7. Agent：先杀光所有旧 worker，再只起一个 ----------
screen -S ai-acq-livekit -X quit >/dev/null 2>&1 || true
pkill -f "app.tools.livekit_outbound_agent" >/dev/null 2>&1 || true
sleep 1
screen -dmS ai-acq-livekit zsh -lc "cd '$ROOT_DIR/backend' && source .venv/bin/activate && python -u -m app.tools.livekit_outbound_agent dev > '$LOG_DIR/livekit-agent.log' 2>&1"
sleep 4

AGENT_COUNT=$(pgrep -f "app.tools.livekit_outbound_agent" | wc -l | tr -d ' ')
echo ""
echo "================= 状态汇总 ================="
echo "Agent worker 数量：$AGENT_COUNT（必须是 1）"
grep -m1 -E "registered worker|starting worker" "$LOG_DIR/livekit-agent.log" 2>/dev/null || echo "（agent 日志还没出注册行，稍后看 $LOG_DIR/livekit-agent.log）"
screen -ls | grep ai-acq || true
echo ""
echo "日志（都在仓库 logs/ 下）："
echo "  SIP:    $LOG_DIR/livekit-sip-native.log"
echo "  Agent:  $LOG_DIR/livekit-agent.log"
echo "  后端:   $LOG_DIR/backend.log"
echo ""
echo "试拨命令："
echo "  curl -sS -X POST http://127.0.0.1:8001/api/outbound/telephony/test-call \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"phone\":\"18850625208\",\"conversationRoute\":\"livekit\",\"merchantName\":\"南昌本地生活招商项目\"}'"
