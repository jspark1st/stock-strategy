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
  echo "[$(date '+%F %T')] ALERT: auto_final 재계산 실패(exit $RC)" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock 마감확정(16:30) 파이프라인 실패(exit $RC) — 배포 안 됨. out/auto_final.log 확인." >> "$LOG" 2>&1 || true
  exit $RC
fi

# t1601 suffix 실증 확정(비파괴 진단): 마감 후엔 t1601 이 확정 수급이라 네이버와 대조 가능.
# .ls_investor_map.json 만 갱신할 뿐 점수/배포엔 영향 없음 → 실패해도 이번 회차를 막지 않는다.
"$PY" scripts/probe_investor_map.py >> "$LOG" 2>&1 || \
  echo "[$(date '+%F %T')] (참고) t1601 매핑 프로브 실패 — 무시하고 진행" >> "$LOG"

# 자가학습 축적 헬스체크(며칠 감시) — 실거래 지평 괴리·채점 정체·고아행 등을 텔레그램 보고.
# 읽기 전용·비파괴. 실패해도 이번 회차/배포를 막지 않는다.
"$PY" scripts/health_check.py >> "$LOG" 2>&1 || \
  echo "[$(date '+%F %T')] (참고) 헬스체크 실패 — 무시하고 진행" >> "$LOG"

# 5b) 사용자 관점 UI 자가비평 — 규칙(결정론)만 매일. 깨진 링크·게이트 모순·도달불가·전문용어 잔재를
# 점검해 report_review(market='UI')에 누적, 고심각이면 경보. LLM 제안은 주 1회 별도(auto_ui_review.sh).
# 강요된 비평 금지: 규칙은 '있으면 진짜 있는 것'만 잡는다. 읽기+DB기록만·비파괴.
"$PY" scripts/run_ui_review.py --write --no-llm >> "$LOG" 2>&1 || \
  echo "[$(date '+%F %T')] (참고) UI 규칙 비평 실패 — 무시하고 진행" >> "$LOG"

# 6) 자가학습 DB 백업 — 채점이 막 반영된 직후 스냅샷(유일본 보호). 실패해도 배포는 진행.
"$PY" scripts/backup_db.py >> "$LOG" 2>&1 || \
  echo "[$(date '+%F %T')] ALERT: DB 백업 실패(auto_final)" >> out/alerts.log

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

git commit -m "auto(마감확정): $(date +%F)" >> "$LOG" 2>&1
# rebase 충돌 시 반쪽 상태·autostash 미복원 방지(auto_close.sh 주석 참조) → 중단·복구·배포 보류.
if ! git pull --rebase --autostash origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✗ git pull --rebase 충돌 — rebase 중단·워킹트리 복구, 배포 보류" >> "$LOG"
  git rebase --abort >> "$LOG" 2>&1 || true
  echo "[$(date '+%F %T')] ALERT: auto_final git rebase 충돌 — 수동 확인 필요" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock 마감확정(16:30) git rebase 충돌 — 배포 보류·워킹트리 복구. 서버 확인." >> "$LOG" 2>&1 || true
  exit 1
fi
if git push origin main >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] ✓ 마감 확정본 배포 완료(Vercel 재배포)" >> "$LOG"
else
  echo "[$(date '+%F %T')] ✗ git push 실패 — 커밋은 로컬에 남음" >> "$LOG"
  echo "[$(date '+%F %T')] ALERT: auto_final git push 실패" >> out/alerts.log
  "$PY" scripts/notify.py "🔴 easystock 마감확정(16:30) git push 실패 — 사이트 미갱신. 서버 확인." >> "$LOG" 2>&1 || true
  exit 1
fi
