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
  setsid nohup bash "$S/library_postprocess_cron.sh" --foreground "$@" </dev/null >/dev/null 2>&1 &
  exit 0
fi

exec 9>"$DATA/postprocess.lock"
flock -n 9 || exit 0

if [[ "$DRY_RUN" == 0 ]]; then
  exec >"$DATA/postprocess_runner.log" 2>&1
  trap 'rc=$?; printf "[%s] 后台后处理退出 rc=%s\n" "$(date "+%F %T")" "$rc"' EXIT
  printf '[%s] 后台后处理启动 pid=%s\n' "$(date '+%F %T')" "$$"
fi

EXTRA_ARGS=()
[[ -n "${X_POSTPROCESS_BATCH:-}" ]] && EXTRA_ARGS+=(--batch "$X_POSTPROCESS_BATCH")
[[ -n "${X_POSTPROCESS_PHASH_LIMIT:-}" ]] && EXTRA_ARGS+=(--phash-limit "$X_POSTPROCESS_PHASH_LIMIT")
[[ -n "${X_POSTPROCESS_MAX_DIST:-}" ]] && EXTRA_ARGS+=(--max-dist "$X_POSTPROCESS_MAX_DIST")

"$PY" "$S/library_postprocess.py" \
  ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
  "$@"
