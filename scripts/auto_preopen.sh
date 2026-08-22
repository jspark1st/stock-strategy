#!/usr/bin/env bash
# easystock 자동 개장 전 파이프라인 (리눅스 서버 cron 용, 평일 08:00 KST)
#
# 직전 마감 리포트를 앵커로, 간밤 해외장·환율·재료를 반영해 개장 전에 판단을 재검토한다.
# 앵커가 오래됐으면(마감 파이프라인 실패/연휴) 리포트 상단에 경고가 박힌다.
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
export LC_ALL=C.UTF-8
# 서버 배포용 SSH 키(있으면 사용) — GitHub push 인증
[ -f "$HOME/.ssh/easystock_deploy" ] && export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/easystock_deploy -o StrictHostKeyChecking=accept-new"

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

mkdir -p out
LOG="out/auto_preopen.log"
LOCK="out/.auto_preopen.lock"

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
  echo "───────── $(date '+%F %T') 개장 전 파이프라인 시작 ─────────"
} >> "$LOG"

"$PY" scripts/run_preopen.py --auto >> "$LOG" 2>&1
RC=$?
if [ $RC -ne 0 ]; then
  echo "[$(date '+%F %T')] ✗ 파이프라인 실패(exit $RC) — 배포하지 않음" >> "$LOG"
  echo "[$(date '+%F %T')] ALERT: auto_preopen 파이프라인 실패(exit $RC)" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock 개장전(08:00) 파이프라인 실패(exit $RC) — 배포 안 됨. out/auto_preopen.log 확인." >> "$LOG" 2>&1 || true
  exit $RC
fi

# 크로스트랙 배포 직렬화(공유 락, 대기 120s — auto_close.sh 주석 참조).
exec 8>"out/.deploy.lock"
if ! flock -w 120 8; then
  echo "[$(date '+%F %T')] 배포 락 대기 초과(다른 트랙 배포 중) — 이번 배포 보류" >> "$LOG"
  exit 0
fi

git add public/index.html
if git diff --cached --quiet; then
  echo "[$(date '+%F %T')] 변경 없음 — 배포 생략" >> "$LOG"
  exit 0
fi

git commit -m "auto(개장전): $(date +%F)" >> "$LOG" 2>&1
# 원격이 앞서 있으면 push 가 거부된다 → rebase 로 맞춘 뒤 재시도
# rebase 충돌 시 반쪽 상태·autostash 미복원 방지(auto_close.sh 주석 참조) → 중단·복구·배포 보류.
if ! git pull --rebase --autostash origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✗ git pull --rebase 충돌 — rebase 중단·워킹트리 복구, 배포 보류" >> "$LOG"
  git rebase --abort >> "$LOG" 2>&1 || true
  echo "[$(date '+%F %T')] ALERT: auto_preopen git rebase 충돌 — 수동 확인 필요" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock 개장전(08:00) git rebase 충돌 — 배포 보류·워킹트리 복구. 서버 확인." >> "$LOG" 2>&1 || true
  exit 1
fi
if git push origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✓ 개장 전 리포트 배포 완료(Vercel 자동배포 트리거)" >> "$LOG"
else
  echo "[$(date '+%F %T')] ✗ git push 실패 — 커밋은 로컬에 남음" >> "$LOG"
  echo "[$(date '+%F %T')] ALERT: auto_preopen git push 실패" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock 개장전(08:00) git push 실패 — 사이트 미갱신. 서버 확인." >> "$LOG" 2>&1 || true
  exit 1
fi
