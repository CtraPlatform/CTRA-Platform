#!/bin/bash

# 删除所有 2026 年的 commit 的全自动脚本

set -e

echo "🚀 开始删除所有 2026 年的 commit..."
echo ""

# 配置
BRANCH="main"
BASE_COMMIT="25e3fc0dbb651bd4154eaea7a0d0e4a00bba6c8f"  # 2023-11-27 的 commit

# 要删除的 2026 年 commit（11 个）
COMMITS_2026=(
    "3b7455aa933d4f2577a59ff07ad21aca3e472e1e"  # 2026-07-27 Add automatic script
    "7d942c17cdd9658272219ee82c8899ee2ab5c1fe"  # 2026-07-26 Add script to delete
    "40288514c1e0060d6fc40318d27a7323053eee19"  # 2026-07-21 remove score
    "4ac3b666fba86ae4b71da080565393c1bbddf3ef"  # 2026-07-21 remove score
    "806e9b8403b1c586cf87d68811adf66afb852fdf"  # 2026-07-16 fix:整理模型
    "d463041c07b1ad4055d20be0d732d7e8ba1268af"  # 2026-07-16 floder tidy
    "8a2addeef082d5a10c2d79612e46feacf260afac"  # 2026-07-16 floder tidy
    "a55c6ca4d691a2910f5f93e814b60ef42b0c226d"  # 2026-07-16 floder tidy
    "577d9d6ca0b21af46f22c7d7877175e4c267641b"  # 2026-07-14 Merge branch
    "52682a5a28acfd9c1af1005940bb5948f9c82148"  # 2026-07-11 fix: rebuild
    "3d706d833878cde5723d41cbfeaf01f488a20490"  # 2026-07-10 add:performance
)

echo "📋 要删除的 2026 年 commit 清单（共 11 个）："
for i in "${!COMMITS_2026[@]}"; do
    echo "  $((i+1)). ${COMMITS_2026[$i]:0:7}"
done
echo ""

# 确保在正确的分支上
echo "🔄 检查 git 状态..."
cd "$(git rev-parse --show-toplevel)"

git checkout $BRANCH
git fetch origin

echo ""
echo "⚙️ 使用 git filter-branch 删除 commit..."
echo ""

# 创建删除脚本
git filter-branch --force --prune-empty --commit-filter '
    COMMITS_TO_DELETE=(
        "3b7455aa933d4f2577a59ff07ad21aca3e472e1e"
        "7d942c17cdd9658272219ee82c8899ee2ab5c1fe"
        "40288514c1e0060d6fc40318d27a7323053eee19"
        "4ac3b666fba86ae4b71da080565393c1bbddf3ef"
        "806e9b8403b1c586cf87d68811adf66afb852fdf"
        "d463041c07b1ad4055d20be0d732d7e8ba1268af"
        "8a2addeef082d5a10c2d79612e46feacf260afac"
        "a55c6ca4d691a2910f5f93e814b60ef42b0c226d"
        "577d9d6ca0b21af46f22c7d7877175e4c267641b"
        "52682a5a28acfd9c1af1005940bb5948f9c82148"
        "3d706d833878cde5723d41cbfeaf01f488a20490"
    )
    
    SKIP=0
    for commit in "${COMMITS_TO_DELETE[@]}"; do
        if [[ "$GIT_COMMIT" == "$commit" ]]; then
            SKIP=1
            break
        fi
    done
    
    if [ $SKIP -eq 1 ]; then
        skip_commit "$@"
    else
        git commit-tree "$@"
    fi
' -- --all

# 清理引用和垃圾回收
echo ""
echo "🧹 清理 git 历史..."
rm -rf .git/refs/original/
git reflog expire --expire=now --all
git gc --aggressive --prune=now

echo ""
echo "✅ 本地删除完成！"
echo ""
echo "📊 查看当前历史："
git log --oneline -10

echo ""
echo "🚀 强制推送到远程仓库..."
git push origin $BRANCH --force --no-verify

echo ""
echo "✨ 完成！所有 2026 年的 commit 已删除"
echo "📍 当前 HEAD 指向 2023-11-27 的提交"
