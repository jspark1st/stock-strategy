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
  "$PY" scripts/notify.py "🔴 easystock 마감(15:00) 파이프라인 실패(exit $RC) — 배포 안 됨. out/auto_close.log 확인." >> "$LOG" 2>&1 || true
  exit $RC
fi

# 크로스트랙 배포 직렬화 — 주식·BTC 러너가 같은 public/index.html·git 인덱스를 동시에
# 커밋/rebase/push 하지 않게 공유 락(대기 120s). 정상 스케줄은 안 겹치나 한 러너가 지연되면
# 겹칠 수 있고, 그 경우 git 충돌·엉킨 커밋을 유발한다. 대기 초과면 이번 배포만 보류(다음 회차 반영).
exec 8>"out/.deploy.lock"
if ! flock -w 120 8; then
  echo "[$(date '+%F %T')] 배포 락 대기 초과(다른 트랙 배포 중) — 이번 배포 보류" >> "$LOG"
  exit 0
fi

git add public/index.html
if git diff --cached --quiet; then
  echo "[$(date '+%F %T')] 변경 없음(휴장일 등) — 배포 생략" >> "$LOG"
  exit 0
fi

git commit -m "auto(마감): $(date +%F)" >> "$LOG" 2>&1
# 원격이 앞서 있으면 push 가 거부된다 → rebase 로 맞춘 뒤 재시도.
# ⚠ rebase 가 public/index.html 충돌로 멈추면 (a) 반쪽 rebase 상태로 repo 가 잠기고
#   (b) --autostash 로 치워둔 **미커밋 소스(라이브 코드)**가 pop 되지 않아, 다음 회차가
#   조용히 옛 커밋 코드로 돈다. 실패 시 rebase 를 중단해 원상복구(autostash 자동 복원)하고 배포 보류.
if ! git pull --rebase --autostash origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✗ git pull --rebase 충돌 — rebase 중단·워킹트리 복구, 배포 보류" >> "$LOG"
  git rebase --abort >> "$LOG" 2>&1 || true
  echo "[$(date '+%F %T')] ALERT: auto_close git rebase 충돌 — 수동 확인 필요" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock 마감(15:00) git rebase 충돌 — 배포 보류·워킹트리 복구. 서버 확인." >> "$LOG" 2>&1 || true
  exit 1
fi
if git push origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✓ 마감 리포트 배포 완료(Vercel 자동배포 트리거)" >> "$LOG"
else
  echo "[$(date '+%F %T')] ✗ git push 실패 — 커밋은 로컬에 남음" >> "$LOG"
  echo "[$(date '+%F %T')] ALERT: auto_close git push 실패" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock 마감(15:00) git push 실패 — 사이트 미갱신. 서버 확인." >> "$LOG" 2>&1 || true
  exit 1
fi
