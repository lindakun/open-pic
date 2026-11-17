#!/usr/bin/env bash
# media-library 服务守护：幂等拉起
# 用法： bash ensure.sh
#
# 注意：必须用 setsid 脱离当前会话。否则从 picoclaw exec 里拉起后，
# 命令结束时整个进程组会被回收，服务随之消失（表现为"拉起成功但几秒后又没响应"）。
set -u
S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${MEDIA_LIB_PORT:-18100}"
DATA="/vol1/picoclaw/.picoclaw/workspace/media-library"
LOG="$DATA/server.log"
PY="$S/../venv/bin/python3"
[ -x "$PY" ] || PY="python3"

if curl -sf -m 3 "http://127.0.0.1:${PORT}/api/stats" >/dev/null 2>&1; then
  exit 0
fi

mkdir -p "$DATA"
echo "$(date '+%F %T') 服务未响应，拉起中…" >> "$LOG"
setsid nohup "$PY" "$S/server.py" --port "$PORT" >> "$LOG" 2>&1 < /dev/null &
disown 2>/dev/null || true

for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 0.6
  if curl -sf -m 3 "http://127.0.0.1:${PORT}/api/stats" >/dev/null 2>&1; then
    echo "$(date '+%F %T') 拉起成功 pid=$(cat "$DATA/server.pid" 2>/dev/null)" >> "$LOG"
    exit 0
  fi
done

echo "$(date '+%F %T') 拉起失败" >> "$LOG"
exit 1
