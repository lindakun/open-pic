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

FOREGROUND=0
if [[ "${1:-}" == --foreground ]]; then
  FOREGROUND=1
  shift
fi
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run|-h|--help) DRY_RUN=1 ;;
  esac
done

if [[ "$DRY_RUN" == 0 && "$FOREGROUND" == 0 ]]; then
  setsid nohup bash "$S/x_scrape_cron.sh" --foreground "$@" </dev/null >/dev/null 2>&1 &
  exit 0
fi

exec 9>"$DATA/x_scrape.lock"
flock -n 9 || exit 0

if [[ "$DRY_RUN" == 0 ]]; then
  exec >"$DATA/x_scrape_runner.log" 2>&1
  trap 'rc=$?; printf "[%s] 后台采集退出 rc=%s\n" "$(date "+%F %T")" "$rc"' EXIT
  printf '[%s] 后台采集启动 pid=%s\n' "$(date '+%F %T')" "$$"
  bash "$S/ensure.sh" 9>&-
fi

EXTRA_ARGS=()
[[ -n "${X_SCRAPE_BATCH:-}" ]] && EXTRA_ARGS+=(--batch "$X_SCRAPE_BATCH")
[[ -n "${X_SCRAPE_LIMIT:-}" ]] && EXTRA_ARGS+=(--limit "$X_SCRAPE_LIMIT")
[[ -n "${X_SCRAPE_MAX_MB:-}" ]] && EXTRA_ARGS+=(--max-mb "$X_SCRAPE_MAX_MB")
[[ -n "${X_SCRAPE_TAGS:-}" ]] && EXTRA_ARGS+=(--tags "$X_SCRAPE_TAGS")

"$PY" "$S/x_scrape.py" \
  --file "$DATA/x_accounts.txt" \
  ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
  "$@"
