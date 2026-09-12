#!/usr/bin/env bash
# 레벨 스캔 스냅샷 (cron */15) — future 스캐너로 지지/저항 인근 후보를 JSON 으로만 남긴다.
# 주문 없음. 대시보드 '레벨 스캔' 페이지가 /scan_latest.json 을 읽어 표를 그린다.
# 배포는 이 JSON 만 git push (index.html 은 리포트 회차가 담당).
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
export LC_ALL=C.UTF-8
[ -f "$HOME/.ssh/easystock_deploy" ] && export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/easystock_deploy -o StrictHostKeyChecking=accept-new"

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

mkdir -p out public
LOG="out/auto_level_scan.log"
LOCK="out/.auto_level_scan.lock"

if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 2000000 ]; then
  mv -f "$LOG" "$LOG.1"
fi

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 이전 스캔 진행 중 — 건너뜀" >> "$LOG"
  exit 0
fi

echo "───────── $(date '+%F %T') 레벨 스캔 시작 ─────────" >> "$LOG"
"$PY" scripts/run_level_scan.py --auto >> "$LOG" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "[$(date '+%F %T')] ✗ 스캔 실패(exit $RC) — 배포하지 않음(직전 JSON 유지)" >> "$LOG"
  echo "[$(date '+%F %T')] ALERT: auto_level_scan 실패(exit $RC)" >> out/alerts.log
  exit $RC
fi

exec 8>"out/.deploy.lock"
if ! flock -w 120 8; then
  echo "[$(date '+%F %T')] 배포 락 대기 초과 — JSON 은 기록됨, 이번 push 보류" >> "$LOG"
  exit 0
fi

git add public/scan_latest.json
if git diff --cached --quiet; then
  echo "[$(date '+%F %T')] 변경 없음 — 배포 생략" >> "$LOG"
  exit 0
fi

git commit -m "auto(스캔): $(date '+%F %H:%M')" >> "$LOG" 2>&1
if ! git pull --rebase --autostash origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✗ git pull --rebase 충돌 — rebase 중단, 배포 보류" >> "$LOG"
  git rebase --abort >> "$LOG" 2>&1 || true
  echo "[$(date '+%F %T')] ALERT: auto_level_scan git rebase 충돌" >> out/alerts.log
  exit 1
fi
if git push origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✓ 스캔 스냅샷 배포" >> "$LOG"
else
  echo "[$(date '+%F %T')] ✗ git push 실패 — 커밋은 로컬에 남음" >> "$LOG"
  echo "[$(date '+%F %T')] ALERT: auto_level_scan git push 실패" >> out/alerts.log
  exit 1
fi
