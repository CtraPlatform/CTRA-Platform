#!/bin/bash

# 直接重置到 2023-11-27 的 commit，删除所有 2026 年的 commit
# 这是最简单直接的方法

set -e

echo "🚀 开始删除所有 2026 年的 commit..."
echo ""

BRANCH="main"
BASE_COMMIT="25e3fc0dbb651bd4154eaea7a0d0e4a00bba6c8f"  # 2023-11-27

echo "📍 目标 commit: $BASE_COMMIT (2023-11-27)"
echo ""

# 进入仓库根目录
cd "$(git rev-parse --show-toplevel)"

# 确保在 main 分支
git checkout $BRANCH

# 更新远程信息
git fetch origin

echo "⚠️  这将删除所有 2026 年的 commit（共 11 个）"
echo ""
read -p "确认继续吗？(y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ 已取消"
    exit 1
fi

echo ""
echo "🔄 重置到 2023-11-27 的状态..."

# 方法 1: 直接重置（最简单）
git reset --hard $BASE_COMMIT

echo "✅ 本地重置完成！"
echo ""
echo "📊 当前 git log:"
git log --oneline -5
echo ""

echo "🚀 强制推送到远程..."
git push origin $BRANCH --force-with-lease

echo ""
echo "✨ 完成！所有 2026 年的 commit 已删除"
echo "📍 仓库已回退到 2023-11-27 的状态"
