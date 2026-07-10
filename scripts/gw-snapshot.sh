#!/usr/bin/env bash
# 只读抓取鼎信网关配置页到 logs/gateway/，供分析，不做任何修改
set -uo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/logs/gateway"
GW="${GW:-192.168.10.114}"
USER_PASS="${GW_AUTH:-admin:admin}"
mkdir -p "$OUT_DIR"

fetch() {
  local page="$1"
  local out="$OUT_DIR/${page//[\/?]/_}.txt"
  # 先试 digest，再试 basic，再试无认证
  for auth in "--digest -u $USER_PASS" "-u $USER_PASS" ""; do
    code=$(curl -s -m 8 $auth -o "$out.raw" -w "%{http_code}" "http://$GW/$page" 2>/dev/null)
    [[ "$code" == "200" ]] && break
  done
  if [[ "${code:-000}" == "200" ]]; then
    iconv -f GB2312 -t UTF-8 "$out.raw" > "$out" 2>/dev/null || cp "$out.raw" "$out"
    echo "OK  $page ($(wc -c < "$out.raw") bytes)"
  else
    echo "FAIL $page (HTTP ${code:-000})"
  fi
  rm -f "$out.raw"
}

echo "== 抓取网关 $GW 配置页 =="
for p in SIPCfg.htm IpCfg.htm IpGroup.htm PortGroup.htm RouteIP2PSTNList.htm \
         ServiceCfg.htm SysInfo.htm Menu.htm MediaParamCfg.htm SMSCfg.htm; do
  fetch "$p"
done
echo "完成，文件在 $OUT_DIR/"
