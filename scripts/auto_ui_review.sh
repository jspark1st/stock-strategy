#!/usr/bin/env bash
# 주간 사용자 관점 UI 자가비평 — LLM(Gemini) 제안 (cron: 매주 월 17:30 KST)
#
# 규칙 비평은 매일 auto_final 에서 돈다. 이건 그 위에 '초보자 관점 제안'을 주 1회만 얹는다.
# 강요된 비평 금지: 프롬프트가 '개선할 게 없으면 침묵·정직성 문구는 건드리지 않음·대안 없으면 버림'.
# 발견은 report_review(market='UI', source='llm')에 '제안'으로만 쌓인다(경보 없음·배포 없음·수정 없음).
# 사람이 /triage 로 '진짜 개선'만 골라 채택한다.
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
export LC_ALL=C.UTF-8

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

mkdir -p out
LOG="out/auto_ui_review.log"
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 2000000 ]; then
  mv -f "$LOG" "$LOG.1"
fi

exec 9>"out/.auto_ui_review.lock"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 이전 실행 진행 중 — 건너뜀" >> "$LOG"
  exit 0
fi

echo "───────── $(date '+%F %T') 주간 UI LLM 비평 시작 ─────────" >> "$LOG"
"$PY" scripts/run_ui_review.py --write >> "$LOG" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "[$(date '+%F %T')] (참고) UI LLM 비평 실패(exit $RC) — 무시(제안일 뿐, 배포 무관)" >> "$LOG"
fi
echo "[$(date '+%F %T')] ✓ 주간 UI 비평 완료(제안 누적 — /triage 로 선별)" >> "$LOG"
