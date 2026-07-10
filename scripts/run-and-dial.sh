#!/usr/bin/env bash
# 一条命令：确保外呼链路在跑 -> 拨测试电话 -> 抓全程日志到 logs/
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
PHONE="${PHONE:-18850625208}"
TS="$(date +%H%M%S)"
OUT="$LOG_DIR/dial-$TS.log"
mkdir -p "$LOG_DIR"

log() { echo "$@" | tee -a "$OUT"; }
api() { curl -sf -m 5 "http://127.0.0.1:8001$1"; }

log "===== 拨测开始 $(date '+%F %T')  号码: $PHONE ====="

# 1. 服务体检
BACKEND_OK=0; api /api/health >/dev/null && BACKEND_OK=1
SIP_OK=0; pgrep -f "livekit-sip" >/dev/null && SIP_OK=1
LK_OK=0; nc -z 127.0.0.1 7880 >/dev/null 2>&1 && LK_OK=1
AGENT_N=$(pgrep -f "app.tools.livekit_outbound_agent" | wc -l | tr -d ' ')
log "体检: backend=$BACKEND_OK livekit=$LK_OK sip=$SIP_OK agent_workers=$AGENT_N"

# 2. 不健康就整套重启
if [[ "$BACKEND_OK" != 1 || "$LK_OK" != 1 || "$SIP_OK" != 1 || "$AGENT_N" != 1 ]]; then
  log ">> 服务不完整，执行 livekit-selfhost-up.sh 重启整套链路..."
  bash "$ROOT_DIR/scripts/livekit-selfhost-up.sh" 2>&1 | tee -a "$OUT"
  sleep 3
fi

# 2.5 切换千问 Omni 实时模型（默认 plus 版；OMNI_MODEL=skip 则跳过）
OMNI_MODEL="${OMNI_MODEL:-qwen3.5-omni-plus-realtime}"
if [[ "$OMNI_MODEL" != "skip" ]]; then
  log ""
  log ">> 设置千问 Omni 实时模型: $OMNI_MODEL"
  (cd "$ROOT_DIR/backend" && source .venv/bin/activate && python - "$OMNI_MODEL" <<'PY'
import sys
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.operations import SystemSetting

model = sys.argv[1]
with SessionLocal() as db:
    row = db.scalars(
        select(SystemSetting).where(
            SystemSetting.group_key == "model",
            SystemSetting.item_key == "dashscope_omni_realtime_model",
        )
    ).first()
    if row:
        row.value = model
        row.updated_by = "claude"
    else:
        db.add(SystemSetting(
            group_key="model",
            item_key="dashscope_omni_realtime_model",
            label="千问Omni实时模型",
            value=model,
            updated_by="claude",
        ))
    db.commit()

from app.services.runtime_ai_config import get_runtime_ai_config
cfg = get_runtime_ai_config()
print(f"当前生效: 模型={cfg.dashscope_omni_realtime_model} 音色={cfg.dashscope_omni_realtime_voice}")
PY
  ) 2>&1 | tee -a "$OUT"

  # 重启 agent 确保新模型生效，并保证只有一个 worker
  screen -S ai-acq-livekit -X quit >/dev/null 2>&1 || true
  pkill -f "app.tools.livekit_outbound_agent" >/dev/null 2>&1 || true
  sleep 1
  screen -dmS ai-acq-livekit zsh -lc "cd '$ROOT_DIR/backend' && source .venv/bin/activate && python -u -m app.tools.livekit_outbound_agent dev > '$LOG_DIR/livekit-agent.log' 2>&1"
  sleep 5
  log "agent 已重启, worker 数: $(pgrep -f app.tools.livekit_outbound_agent | wc -l | tr -d ' ')（应为 1）"
fi

# 3. 拨号
log ""
log ">> 发起 LiveKit 试拨 $PHONE"
RESP=$(curl -sS -m 30 -X POST http://127.0.0.1:8001/api/outbound/telephony/test-call \
  -H 'Content-Type: application/json' \
  -d "{\"phone\":\"$PHONE\",\"conversationRoute\":\"livekit\",\"merchantName\":\"南昌本地生活招商项目\"}")
log "接口返回: $RESP"

# 4. 抓 90 秒全程日志
log ""
log ">> 监听 90 秒（请接听电话并按话术对话）..."
for i in $(seq 1 9); do
  sleep 10
  {
    echo "----- +$((i*10))s live-events -----"
    api "/api/outbound/realtime/live-events?limit=40" || echo "(live-events 接口无响应)"
  } >> "$OUT" 2>&1
done

# 5. 收尾快照
{
  echo ""
  echo "===== agent 日志（尾部 120 行）====="
  tail -n 120 "$LOG_DIR/livekit-agent.log" 2>/dev/null || tail -n 120 /tmp/ai-acq-livekit-agent.log 2>/dev/null || echo "(无 agent 日志)"
  echo ""
  echo "===== 本机 SIP 日志（尾部 80 行）====="
  tail -n 80 "$LOG_DIR/livekit-sip-native.log" 2>/dev/null || tail -n 80 /tmp/ai-acq-livekit-sip-native.log 2>/dev/null || echo "(无 SIP 日志)"
  echo ""
  echo "===== 实时事件（尾部 60 行）====="
  tail -n 60 /tmp/ai-acq-realtime-call-events.jsonl 2>/dev/null || echo "(无事件文件)"
  echo ""
  echo "===== 拨测结束 $(date '+%F %T') ====="
} >> "$OUT" 2>&1

echo ""
echo "全部日志已写入: $OUT"
