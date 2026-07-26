#!/bin/bash

# 删除所有 liujinzan 提交的 commit 的脚本
# 使用方式：bash DELETE_LIUJINZAN_COMMITS.sh

set -e

echo "🚀 开始删除 liujinzan 的所有 commit..."
echo ""

# 要删除的 commit SHA（按时间顺序，从最早到最新）
COMMITS_TO_DELETE=(
    "3d706d833878cde5723d41cbfeaf01f488a20490"  # 2026-07-10 add:performance
    "2cf06e201dbe5d7b272eee46905e712c4a482ee4"  # 2026-07-14 add:预训练模型
    "9a744181764d4446f2d55badce83951be67814dd"  # 2026-07-14 aaaa
    "173ed9ec25fc5c5582ae2cbfb7f27b4a357b082e"  # 2026-07-14 Merge branch 'main' into feature
    "0a17351ea800ae3d64449395bbc196e1eed0c150"  # 2026-07-14 fix:readme
    "806e9b8403b1c586cf87d68811adf66afb852fdf"  # 2026-07-16 fix:整理模型
)

# 基础 commit（不删除，在它之前）
BASE_COMMIT="25e3fc0dbb651bd4154eaea7a0d0e4a00bba6c8f"

echo "📝 要删除的 commit 列表："
for commit in "${COMMITS_TO_DELETE[@]}"; do
    echo "  - $commit"
done
echo ""

# 确认
read -p "确认删除这 6 个 commit 吗？(y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ 已取消"
    exit 1
fi

# 确保在 main 分支上
echo "🔄 切换到 main 分支..."
git checkout main

# 更新到最新
echo "🔄 拉取最新代码..."
git fetch origin

# 开始交互式 rebase
echo ""
echo "📋 启动交互式 rebase..."
echo "将打开编辑器，请按照以下步骤操作："
echo "1. 找到下面 6 个 commit（commit message 包含 liujinzan 的内容）"
echo "2. 将 'pick' 改为 'drop'"
echo "3. 保存并退出编辑器"
echo ""
echo "要删除的 commit 信息："
echo "  - add:performance"
echo "  - add:预训练模型"
echo "  - aaaa"
echo "  - Merge branch 'main' into feature"
echo "  - fix:readme"
echo "  - fix:整理模型"
echo ""
read -p "按 Enter 继续..." -r

git rebase -i ${BASE_COMMIT}

# 检查 rebase 是否成功
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Rebase 成功！"
    echo ""
    echo "📊 变更统计："
    echo "原始提交: $(git rev-list --count origin/main..HEAD) 个新 commit"
    echo ""
    echo "🚀 开始强制推送到远程仓库..."
    read -p "确认强制推送到 origin/main 吗？(y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git push origin main --force
        echo "✅ 强制推送完成！"
        echo ""
        echo "✨ 所有 liujinzan 的 commit 已删除！"
    else
        echo "⚠️  Rebase 已完成，但未推送。请手动执行："
        echo "   git push origin main --force"
    fi
else
    echo "❌ Rebase 过程中出错！"
    echo "您可以使用以下命令中止 rebase："
    echo "   git rebase --abort"
    exit 1
fi
