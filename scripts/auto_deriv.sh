#!/usr/bin/env bash
# BTC 파생 지표 수집 크론 러너 (2026-09-04) — 5m/15m 이력을 잃지 않게 자주 돈다.
# 바이낸스 파생 API 는 5m=1.7일·12h=30일만 주므로, 10분 간격으로 멱등 upsert 하여
# 과거를 '지금부터' 축적한다. 관측 전용 — 배포·커밋 없음(DB 원격 push 만).
set -u
cd "$(dirname "$0")/.." || exit 1
PY=".venv/bin/python"
LOG="out/auto_deriv.log"
LOCK="out/.auto_deriv.lock"
mkdir -p out

# 로그 로테이션(1MB 초과 시)
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 1048576 ]; then
  mv "$LOG" "$LOG.1"
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 이전 수집 실행 중 — 스킵" >> "$LOG"
  exit 0
fi

echo "[$(date '+%F %T')] 파생 수집 시작" >> "$LOG"
"$PY" scripts/collect_btc_deriv.py >> "$LOG" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "[$(date '+%F %T')] ALERT: 파생 수집 실패(exit $RC)" >> out/alerts.log
fi
echo "[$(date '+%F %T')] 완료(exit $RC)" >> "$LOG"
