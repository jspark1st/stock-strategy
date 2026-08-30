#!/usr/bin/env bash
# 월간 엣지 재검증 (cron: 매월 1일 07:00 KST)
#
# 표본을 최신 데이터로 재생성 → walk-forward 재측정 → AUC 추세를 텔레그램 보고(revalidate.py 가
# 자체 전송). 배포/커밋 없음(분석·알림만). 하락/횡보 레짐이 데이터에 담기면 엣지 변화가 여기 드러난다.
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
export LC_ALL=C.UTF-8

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

mkdir -p out
LOG="out/auto_revalidate.log"
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 2000000 ]; then
  mv -f "$LOG" "$LOG.1"
fi

exec 9>"out/.auto_revalidate.lock"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 이전 실행 진행 중 — 건너뜀" >> "$LOG"
  exit 0
fi

echo "───────── $(date '+%F %T') 월간 엣지 재검증 시작 ─────────" >> "$LOG"
"$PY" scripts/revalidate.py >> "$LOG" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "[$(date '+%F %T')] ✗ 재검증 실패(exit $RC)" >> "$LOG"
  echo "[$(date '+%F %T')] ALERT: auto_revalidate 실패(exit $RC)" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 월간 엣지 재검증 실패(exit $RC) — out/auto_revalidate.log 확인." >> "$LOG" 2>&1 || true
  exit $RC
fi
echo "[$(date '+%F %T')] ✓ 재검증 완료(텔레그램 전송)" >> "$LOG"

# 문서 드리프트 가드 — 문서가 현실(테스트 수·링크·크론)과 어긋나면 경보(비치명적)
"$PY" scripts/check_docs.py >> "$LOG" 2>&1
DRC=$?
if [ $DRC -ne 0 ]; then
  echo "[$(date '+%F %T')] ALERT: 문서 드리프트 감지(check_docs exit $DRC)" >> out/alerts.log
  "$PY" scripts/notify.py "🟡 문서 드리프트 — check_docs 불일치. out/auto_revalidate.log 확인 후 문서를 현실에 맞춰라." >> "$LOG" 2>&1 || true
fi
