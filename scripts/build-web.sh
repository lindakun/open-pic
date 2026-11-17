#!/usr/bin/env bash
# MediaLib 前端构建脚本
#
# 用途：本地或 CI 构建新前端，产物落至 media-library/scripts/static/app/
# 设计取舍：构建产物纳入版本库，NAS 端只需 git pull，无需安装 Node 工具链。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/web"

if [ ! -d "$WEB" ]; then
  echo "错误：未找到前端目录 $WEB" >&2
  exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "错误：未安装 pnpm。请先安装：npm i -g pnpm" >&2
  exit 1
fi

cd "$WEB"

# 首次或依赖变更时安装
if [ ! -d node_modules ]; then
  echo "==> 安装依赖"
  pnpm install
fi

echo "==> 类型检查并构建"
pnpm build

echo
echo "构建完成，产物位于："
echo "  $ROOT/media-library/scripts/static/app/"
echo
echo "切换前端（服务端环境变量）："
echo "  MEDIA_LIB_FRONTEND=next   # 使用新前端（默认，产物存在时自动启用）"
echo "  MEDIA_LIB_FRONTEND=legacy # 回退到旧单页"
