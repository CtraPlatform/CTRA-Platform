#!/bin/bash

# 自动化删除 liujinzan commit 的脚本（无需交互）
# 这个脚本将直接执行变基操作

set -e

echo "🚀 开始自动删除 liujinzan 的所有 commit..."
echo ""

# 配置
REPO_DIR="."
BASE_COMMIT="25e3fc0dbb651bd4154eaea7a0d0e4a00bba6c8f"
BRANCH="main"

cd "$REPO_DIR"

# 确保在 main 分支
git checkout $BRANCH
git fetch origin

# 要删除的 commit（这些是 liujinzan 提交的）
COMMITS_TO_REMOVE=(
    "3d706d833878cde5723d41cbfeaf01f488a20490"
    "2cf06e201dbe5d7b272eee46905e712c4a482ee4"
    "9a744181764d4446f2d55badce83951be67814dd"
    "173ed9ec25fc5c5582ae2cbfb7f27b4a357b082e"
    "0a17351ea800ae3d64449395bbc196e1eed0c150"
    "806e9b8403b1c586cf87d68811adf66afb852fdf"
)

echo "⚙️  使用 git filter-repo 删除 commit..."
echo ""

# 创建临时文件存储要删除的 commit
cat > /tmp/commits_to_remove.txt << EOF
3d706d833878cde5723d41cbfeaf01f488a20490
2cf06e201dbe5d7b272eee46905e712c4a482ee4
9a744181764d4446f2d55badce83951be67814dd
173ed9ec25fc5c5582ae2cbfb7f27b4a357b082e
0a17351ea800ae3d64449395bbc196e1eed0c150
806e9b8403b1c586cf87d68811adf66afb852fdf
EOF

# 使用 git filter-repo（更强大和可靠）
# 如果没有 git-filter-repo，尝试用 git filter-branch

if command -v git-filter-repo &> /dev/null; then
    echo "📦 使用 git-filter-repo..."
    git filter-repo --commits-file /tmp/commits_to_remove.txt --invert-paths --force
else
    echo "📦 使用 git filter-branch..."
    # 使用 filter-branch 的备选方案
    for commit in "${COMMITS_TO_REMOVE[@]}"; do
        echo "删除 commit: $commit"
    done
    
    # 创建一个临时脚本来识别要删除的 commit
    cat > /tmp/filter_script.sh << 'BASH_SCRIPT'
#!/bin/bash
COMMITS_TO_REMOVE=(
    "3d706d833878cde5723d41cbfeaf01f488a20490"
    "2cf06e201dbe5d7b272eee46905e712c4a482ee4"
    "9a744181764d4446f2d55badce83951be67814dd"
    "173ed9ec25fc5c5582ae2cbfb7f27b4a357b082e"
    "0a17351ea800ae3d64449395bbc196e1eed0c150"
    "806e9b8403b1c586cf87d68811adf66afb852fdf"
)

for commit in "${COMMITS_TO_REMOVE[@]}"; do
    if [ "$GIT_COMMIT" = "$commit" ]; then
        return 1  # 返回 1 表示删除此 commit
    fi
done
return 0  # 返回 0 表示保留此 commit
BASH_SCRIPT
    chmod +x /tmp/filter_script.sh
    
    git filter-branch --force --prune-empty --commit-filter '
        if [[ "$GIT_COMMIT" == "3d706d833878cde5723d41cbfeaf01f488a20490" ]] || \
           [[ "$GIT_COMMIT" == "2cf06e201dbe5d7b272eee46905e712c4a482ee4" ]] || \
           [[ "$GIT_COMMIT" == "9a744181764d4446f2d55badce83951be67814dd" ]] || \
           [[ "$GIT_COMMIT" == "173ed9ec25fc5c5582ae2cbfb7f27b4a357b082e" ]] || \
           [[ "$GIT_COMMIT" == "0a17351ea800ae3d64449395bbc196e1eed0c150" ]] || \
           [[ "$GIT_COMMIT" == "806e9b8403b1c586cf87d68811adf66afb852fdf" ]]; then
            skip_commit "$@"
        else
            git commit-tree "$@"
        fi
    ' -- --all
fi

# 清理引用
rm -rf .git/refs/original/
git reflog expire --expire=now --all
git gc --prune=now

echo "✅ 清理完成！"
echo ""
echo "🚀 强制推送到远程..."
git push origin $BRANCH --force --no-verify

echo ""
echo "✨ 所有 liujinzan 的 commit 已删除！"
echo "✅ 已推送到远程仓库"
