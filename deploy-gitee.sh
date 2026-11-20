#!/usr/bin/env bash
# 发布 web/ 到 Gitee Pages（推到 pages 分支，不含源码）
# 用法: ./deploy-gitee.sh <你的Gitee用户名> [仓库名]
set -e

GITEE_USER="${1:-}"
REPO="${2:-asset-cycle-atlas}"
if [ -z "$GITEE_USER" ]; then
  echo "用法: ./deploy-gitee.sh <Gitee用户名> [仓库名]"
  echo "示例: ./deploy-gitee.sh saviorbill asset-cycle-atlas"
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cp -R "$HERE/web/." "$TMP/"
cd "$TMP"

git init -q -b pages
git add -A
git -c user.name="deploy" -c user.email="deploy@local" \
    commit -q -m "deploy: $(date '+%Y-%m-%d %H:%M')"

echo "==> 推送到 gitee.com/$GITEE_USER/$REPO 的 pages 分支 ..."
git push -f "https://gitee.com/$GITEE_USER/$REPO.git" pages

echo ""
echo "✅ 已推送。接下来（首次需要）："
echo "   1. 打开 https://gitee.com/$GITEE_USER/$REPO/pages"
echo "   2. 分支选 pages → 点「启动服务」"
echo "   3. 访问 https://$GITEE_USER.gitee.io/$REPO/"
