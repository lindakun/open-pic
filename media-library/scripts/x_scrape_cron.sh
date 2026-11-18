#!/usr/bin/env bash
set -euo pipefail

S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${MEDIA_LIB_DIR:-/vol1/picoclaw/.picoclaw/workspace/media-library}"
PY="$S/../venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"

if [[ ! -d "$DATA" ]]; then
  printf '图片库数据目录不存在：%s\n' "$DATA" >&2
  exit 2
fi

exec 9>"$DATA/x_scrape.lock"
flock -n 9 || exit 0

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run|-h|--help) DRY_RUN=1 ;;
  esac
done
if [[ "$DRY_RUN" == 0 ]]; then
  bash "$S/ensure.sh"
fi

exec "$PY" "$S/x_scrape.py" \
  --file "$DATA/x_accounts.txt" \
  --batch "${X_SCRAPE_BATCH:-7}" \
  --limit "${X_SCRAPE_LIMIT:-4}" \
  --max-mb "${X_SCRAPE_MAX_MB:-30}" \
  --tags "${X_SCRAPE_TAGS:-X抓取,人物}" \
  "$@"
