#!/usr/bin/env bash
# easystock 마감 후 '확정 재계산' 파이프라인 (리눅스 서버 cron 용, 평일 16:30 KST)
#
# 15:00 회차는 종가베팅 주문용이라 '장중 잠정'(지수·수급·거래량 미확정)이다. 장 마감 후
# 확정 일봉·확정 투자자 수급·확정 종가가 나오면, 같은 날 리포트를 확정치로 다시 계산해
# 덮어쓴다. run_close.py 는 실행 시각이 16:00 을 지나면 스스로 '마감 확정' 경로를 타므로
# (resolve_session → intraday=False), 이 스크립트는 그저 그 시각에 한 번 더 돌려주면 된다.
# 결과: out/report_<date>.html · public/index.html 이 확정본으로 갱신 → Vercel 재배포.
#
# 15:00 auto_close.sh 와 락/로그/커밋 메시지를 분리해 두 회차가 로그상 섞이지 않게 한다.
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
export LC_ALL=C.UTF-8
[ -f "$HOME/.ssh/easystock_deploy" ] && export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/easystock_deploy -o StrictHostKeyChecking=accept-new"

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

mkdir -p out
LOG="out/auto_final.log"
LOCK="out/.auto_final.lock"

if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 2000000 ]; then
  mv -f "$LOG" "$LOG.1"
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 이전 실행이 진행 중 — 이번 회차 건너뜀" >> "$LOG"
  exit 0
fi

echo "───────── $(date '+%F %T') 마감 확정 재계산 시작 ─────────" >> "$LOG"

"$PY" scripts/run_close.py --auto >> "$LOG" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "[$(date '+%F %T')] ✗ 재계산 실패(exit $RC) — 배포하지 않음" >> "$LOG"
  exit $RC
fi

git add public/index.html
if git diff --cached --quiet; then
  echo "[$(date '+%F %T')] 변경 없음 — 배포 생략" >> "$LOG"
  exit 0
fi

git commit -m "auto(마감확정): $(date +%F)" >> "$LOG" 2>&1
git pull --rebase --autostash origin main >> "$LOG" 2>&1
if git push origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✓ 마감 확정본 배포 완료(Vercel 재배포)" >> "$LOG"
else
  echo "[$(date '+%F %T')] ✗ git push 실패 — 커밋은 로컬에 남음" >> "$LOG"
  exit 1
fi
