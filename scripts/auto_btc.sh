#!/usr/bin/env bash
# easystock BTC 선물 자동 파이프라인 (cron 09:30·22:00 KST 매일)
# 배포 git 은 여기만. TUI 는 파이프라인 후 `push-only` 로 이 경로를 탄다.
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
export LC_ALL=C.UTF-8
[ -f "$HOME/.ssh/easystock_deploy" ] && export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/easystock_deploy -o StrictHostKeyChecking=accept-new"

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

mkdir -p out
LOG="out/auto_btc.log"
LOCK="out/.auto_btc.lock"

if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 2000000 ]; then
  mv -f "$LOG" "$LOG.1"
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 이전 실행이 진행 중 — 이번 회차 건너뜀" >> "$LOG"
  exit 0
fi

MODE="${1:-}"
{
  echo "───────── $(date '+%F %T') BTC 파이프라인 시작 (${MODE:-cron}) ─────────"
} >> "$LOG"

if [ "$MODE" = "push-only" ]; then
  :
elif [ "$MODE" = "manual" ]; then
  LEV="${2:-5}"
  MAR="${3:-1000}"
  "$PY" scripts/run_btc.py --manual --leverage "$LEV" --margin "$MAR" >> "$LOG" 2>&1
  RC=$?
  if [ $RC -ne 0 ]; then
    echo "[$(date '+%F %T')] ✗ 수동 파이프라인 실패(exit $RC) — 배포하지 않음" >> "$LOG"
    echo "[$(date '+%F %T')] ALERT: auto_btc 수동 실패(exit $RC)" >> out/alerts.log
    "$PY" scripts/notify.py "🔴 easystock BTC 선물 수동 발행 실패(exit $RC)." >> "$LOG" 2>&1 || true
    exit $RC
  fi
else
  "$PY" scripts/run_btc.py --auto >> "$LOG" 2>&1
  RC=$?
  if [ $RC -ne 0 ]; then
    echo "[$(date '+%F %T')] ✗ 파이프라인 실패(exit $RC) — 배포하지 않음" >> "$LOG"
    echo "[$(date '+%F %T')] ALERT: auto_btc 파이프라인 실패(exit $RC)" >> out/alerts.log
    "$PY" scripts/notify.py "🔴 easystock BTC 선물 파이프라인 실패(exit $RC) — 배포 안 됨. out/auto_btc.log 확인." >> "$LOG" 2>&1 || true
    exit $RC
  fi
fi

# 크로스트랙 배포 직렬화(공유 락, 대기 120s — auto_close.sh 주석 참조). BTC 는 주식 크론과
# 스케줄이 다르지만 지연 시 겹칠 수 있어 같은 락을 쓴다. git add(로컬 인덱스)부터 락 안에서.
exec 8>"out/.deploy.lock"
if ! flock -w 120 8; then
  echo "[$(date '+%F %T')] 배포 락 대기 초과(다른 트랙 배포 중) — 이번 배포 보류" >> "$LOG"
  exit 0
fi

git add public/index.html public/archive public/vendor 2>/dev/null || git add public/index.html
if git diff --cached --quiet; then
  echo "[$(date '+%F %T')] 변경 없음 — 배포 생략" >> "$LOG"
  exit 0
fi

git commit -m "auto(BTC): $(date '+%F %H:%M')" >> "$LOG" 2>&1
# rebase 충돌 시 반쪽 상태·autostash 미복원 방지(auto_close.sh 주석 참조) → 중단·복구·배포 보류.
if ! git pull --rebase --autostash origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✗ git pull --rebase 충돌 — rebase 중단·워킹트리 복구, 배포 보류" >> "$LOG"
  git rebase --abort >> "$LOG" 2>&1 || true
  echo "[$(date '+%F %T')] ALERT: auto_btc git rebase 충돌 — 수동 확인 필요" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock BTC 선물 git rebase 충돌 — 배포 보류·워킹트리 복구. 서버 확인." >> "$LOG" 2>&1 || true
  exit 1
fi
if git push origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✓ BTC 리포트 배포 완료(Vercel)" >> "$LOG"
else
  echo "[$(date '+%F %T')] ✗ git push 실패 — 커밋은 로컬에 남음" >> "$LOG"
  echo "[$(date '+%F %T')] ALERT: auto_btc git push 실패" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock BTC 선물 git push 실패 — 사이트 미갱신." >> "$LOG" 2>&1 || true
  exit 1
fi
