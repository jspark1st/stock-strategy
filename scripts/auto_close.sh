#!/usr/bin/env bash
# easystock 자동 마감 파이프라인 (리눅스 서버 cron 용, 평일 15:00 KST)
#
# 종가베팅 주문은 종가 단일가(15:20~15:30) 전에 넣어야 하므로 15:00 에 돈다.
# 파이프라인이 스스로 '오늘이 거래일인가'를 데이터로 판정하므로 공휴일에는
# 아무 것도 만들지 않고 종료한다(= public/index.html 무변경 → 배포 없음).
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
export LC_ALL=C.UTF-8
# 서버 배포용 SSH 키(있으면 사용) — GitHub push 인증
[ -f "$HOME/.ssh/easystock_deploy" ] && export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/easystock_deploy -o StrictHostKeyChecking=accept-new"

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

mkdir -p out
LOG="out/auto_close.log"
LOCK="out/.auto_close.lock"

# 로그 무한 증가 방지 — 2MB 넘으면 직전본 1개만 남기고 새로 시작
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 2000000 ]; then
  mv -f "$LOG" "$LOG.1"
fi

# 이전 실행이 아직 돌고 있으면(네트워크 지연 등) 겹쳐 돌지 않는다
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 이전 실행이 진행 중 — 이번 회차 건너뜀" >> "$LOG"
  exit 0
fi

{
  echo "───────── $(date '+%F %T') 마감 파이프라인 시작 ─────────"
} >> "$LOG"

"$PY" scripts/run_close.py --auto >> "$LOG" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "[$(date '+%F %T')] ✗ 파이프라인 실패(exit $RC) — 배포하지 않음" >> "$LOG"
  echo "[$(date '+%F %T')] ALERT: auto_close 파이프라인 실패(exit $RC)" >> out/alerts.log
  exit $RC
fi

git add public/index.html
if git diff --cached --quiet; then
  echo "[$(date '+%F %T')] 변경 없음(휴장일 등) — 배포 생략" >> "$LOG"
  exit 0
fi

git commit -m "auto(마감): $(date +%F)" >> "$LOG" 2>&1
# 원격이 앞서 있으면 push 가 거부된다 → rebase 로 맞춘 뒤 재시도
git pull --rebase --autostash origin main >> "$LOG" 2>&1
if git push origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✓ 마감 리포트 배포 완료(Vercel 자동배포 트리거)" >> "$LOG"
else
  echo "[$(date '+%F %T')] ✗ git push 실패 — 커밋은 로컬에 남음" >> "$LOG"
  echo "[$(date '+%F %T')] ALERT: auto_close git push 실패" >> out/alerts.log
  exit 1
fi
