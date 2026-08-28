#!/usr/bin/env bash
# 자가학습 DB 일일 백업 (cron: 매일 23:30 KST)
#
# history.db 는 이 VM 에 사본이 하나뿐이고 재구성이 불가능하다(예측·채점 누적). 파이프라인이
# 쓰는 중일 수 있으므로 sqlite 온라인 백업 API 로 일관 스냅샷 → 무결성 검증 → gzip → 14벌 순환.
# 저장 위치는 repo 밖(~/overnight_report_backups, .env 의 backup_dir 로 변경 가능).
# 실패하면 alerts.log + 텔레그램으로 승격한다(조용히 실패하는 백업이 최악).
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
export LC_ALL=C.UTF-8

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

mkdir -p out
LOG="out/auto_backup.log"
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 1000000 ]; then
  mv -f "$LOG" "$LOG.1"
fi

exec 9>"out/.auto_backup.lock"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 이전 실행 진행 중 — 건너뜀" >> "$LOG"
  exit 0
fi

echo "───────── $(date '+%F %T') DB 백업 ─────────" >> "$LOG"
"$PY" scripts/backup_db.py >> "$LOG" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "[$(date '+%F %T')] ALERT: DB 백업 실패(exit $RC)" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock 자가학습 DB 백업 실패 — 유일본 무방비 상태. 서버 확인(out/auto_backup.log)." >> "$LOG" 2>&1 || true
  exit $RC
fi
echo "[$(date '+%F %T')] ✓ DB 백업 완료" >> "$LOG"
