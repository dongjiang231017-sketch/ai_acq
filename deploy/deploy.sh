#!/usr/bin/env bash
# 【审计B2】统一部署脚本：git pull -> pip install -> 原子重启两个 systemd 服务 -> 冒烟测试。
# 任一步失败立即 exit 1；冒烟不过说明线路不可用，不要继续放量拨打。
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/ai_acq}"
BACKEND_DIR="$REPO_DIR/backend"
PYTHON_BIN="${PYTHON_BIN:-$BACKEND_DIR/.venv/bin/python}"
PIP_BIN="${PIP_BIN:-$BACKEND_DIR/.venv/bin/pip}"
API_HEALTH_URL="${API_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
AUDIO_SOCKET_HOST="${AUDIO_SOCKET_HOST:-127.0.0.1}"
AUDIO_SOCKET_PORT="${AUDIO_SOCKET_PORT:-9019}"

log() { echo "[deploy] $*"; }
fail() { echo "[deploy][FAIL] $*" >&2; exit 1; }

log "== 1/4 git pull =="
git -C "$REPO_DIR" pull --ff-only || fail "git pull 失败"

log "== 2/4 pip install =="
"$PIP_BIN" install --quiet -r "$BACKEND_DIR/requirements.txt" || fail "pip install 失败"

log "== 3/4 restart services =="
systemctl restart ai-acq-api.service || fail "重启 ai-acq-api.service 失败"
systemctl restart ai-acq-bridge.service || fail "重启 ai-acq-bridge.service 失败"
sleep 3
systemctl is-active --quiet ai-acq-api.service || fail "ai-acq-api.service 重启后未处于 active 状态"
systemctl is-active --quiet ai-acq-bridge.service || fail "ai-acq-bridge.service 重启后未处于 active 状态"

log "== 4/4 smoke tests =="

# 冒烟1：AudioSocket 端口探测（bridge 不在 -> 电话接通即挂）
# 评审修复5：改为最多重试5次、间隔2秒（对齐 API 健康检查的重试方式），等待 bridge 完成启动监听。
log "smoke: AudioSocket ${AUDIO_SOCKET_HOST}:${AUDIO_SOCKET_PORT}"
bridge_ok=0
for _ in 1 2 3 4 5; do
    if "$PYTHON_BIN" -c "
import socket
s = socket.socket()
s.settimeout(3)
try:
    s.connect(('${AUDIO_SOCKET_HOST}', ${AUDIO_SOCKET_PORT}))
finally:
    s.close()
" >/dev/null 2>&1; then
        bridge_ok=1
        break
    fi
    sleep 2
done
[ "$bridge_ok" = "1" ] || fail "AudioSocket ${AUDIO_SOCKET_HOST}:${AUDIO_SOCKET_PORT} 探测失败（bridge 未监听）"

# 冒烟2：API 健康检查（带重试，等待 uvicorn 完成启动）
log "smoke: GET ${API_HEALTH_URL}"
health_ok=0
for _ in 1 2 3 4 5; do
    if curl -fsS --max-time 5 "$API_HEALTH_URL" >/dev/null 2>&1; then
        health_ok=1
        break
    fi
    sleep 2
done
[ "$health_ok" = "1" ] || fail "API 健康检查失败：${API_HEALTH_URL}"

# 冒烟3：AMI 登录 + pjsip contacts（网关掉注册时部署冒烟直接亮红灯）
log "smoke: AMI login + pjsip show contacts"
(
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" - <<'PY'
import sys

from app.services.asterisk_ami import AsteriskAmiClient
from app.services.voice_gateway_profiles import current_voice_gateway_profile

trunk = (current_voice_gateway_profile().trunk_name or "").strip()
with AsteriskAmiClient() as client:
    ping = client.ping()
    if not ping.ok:
        print(f"[deploy][smoke] AMI Ping 失败: {ping.message}", file=sys.stderr)
        sys.exit(1)
    response = client.command("pjsip show contacts")
    output = response.field_text("Output") or response.message
print("[deploy][smoke] pjsip show contacts:")
print(output)
if trunk and trunk.lower() not in output.lower():
    print(f"[deploy][smoke] pjsip contacts 中没有 trunk={trunk} 的 contact，网关未注册", file=sys.stderr)
    sys.exit(1)
PY
) || fail "AMI 登录 / pjsip contacts 冒烟失败（检查 AMI 配置与网关注册）"

log "部署完成，全部冒烟通过。"
