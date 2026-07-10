#!/bin/bash
# 双击运行：拉代码 + 重启自建 LiveKit 外呼全链路
cd "$(dirname "$0")"

echo "==> git pull"
git pull --ff-only || echo "（git pull 失败或有本地改动，继续用当前代码）"

echo
echo "==> 重启外呼链路"
bash scripts/livekit-selfhost-up.sh

echo
read -p "跑完了。按回车关闭窗口..."
