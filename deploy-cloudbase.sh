#!/usr/bin/env bash
# 一键部署 web/ 到腾讯云 CloudBase 静态网站托管
# 用法: ./deploy-cloudbase.sh <你的环境ID>
set -e

ENV_ID="${1:-}"
if [ -z "$ENV_ID" ]; then
  echo "用法: ./deploy-cloudbase.sh <环境ID>"
  echo "环境ID 在 CloudBase 控制台 → 环境 → 环境ID（形如 app-xxxxxx）"
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/web"

echo "==> 部署 web/ 到环境 $ENV_ID ..."
npx --yes @cloudbase/cli hosting deploy . / -e "$ENV_ID"

echo ""
echo "✅ 完成。访问地址：https://${ENV_ID}.tcloudbaseapp.com/"
