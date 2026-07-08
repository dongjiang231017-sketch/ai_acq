#!/usr/bin/env bash
# 创建指向鼎信网关的外呼 trunk（只需执行一次）
# 前提：已安装 lk CLI（https://github.com/livekit/livekit-cli）
#   curl -sSL https://get.livekit.io/cli | bash
# 用法：先改 deploy/trunk-outbound.json 里的网关IP和主叫号，再执行：
#   LIVEKIT_URL=http://127.0.0.1:7880 LIVEKIT_API_KEY=APIxxxxxxxx LIVEKIT_API_SECRET=xxx ./create_trunk.sh
set -euo pipefail
cd "$(dirname "$0")/.."

lk sip outbound create deploy/trunk-outbound.json

echo ""
echo "记下上面输出的 trunk id（ST_xxxx），填到 agent/.env 的 SIP_OUTBOUND_TRUNK_ID"
