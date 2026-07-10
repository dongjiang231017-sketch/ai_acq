#!/usr/bin/env bash
# 切换到远端最新分支并覆盖本地代码（切换前自动备份当前状态）
# 用法: bash scripts/switch-branch.sh [origin/分支名]   不带参数则自动选最近更新的远程分支
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "==> 1. 备份当前本地状态"
git add -A
git commit -m "backup: switch-branch 前的本地快照" >/dev/null 2>&1 || echo "(没有需要备份的改动)"
BK="backup/pre-switch-$(date +%m%d-%H%M%S)"
git branch -f "${BK}" HEAD
echo "已备份到分支: ${BK}"

echo "==> 2. 拉取远端"
git fetch --all --prune

echo "==> 3. 选择目标分支"
TARGET="${1:-$(git for-each-ref --sort=-committerdate refs/remotes/origin --format='%(refname:short)' | grep -v 'origin/HEAD' | head -1)}"
echo "目标分支: ${TARGET}"

echo "==> 4. 覆盖切换"
LOCAL_BRANCH="${TARGET#origin/}"
git checkout -B "${LOCAL_BRANCH}" "${TARGET}"

echo ""
echo "完成。当前分支: $(git branch --show-current)"
git log --oneline -5
echo ""
echo "如需回滚: git checkout ${BK}"
