#!/usr/bin/env bash
# easystock 자동 마감 파이프라인 (리눅스 서버 cron 용)
# 서버(한국 IP·KST)에서 데이터 수집·리포트 생성 → public/index.html → git push → Vercel 자동배포.
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
# 서버 배포용 SSH 키(있으면 사용) — GitHub push 인증
[ -f "$HOME/.ssh/easystock_deploy" ] && export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/easystock_deploy -o StrictHostKeyChecking=accept-new"

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

mkdir -p out
"$PY" scripts/run_close.py --auto >> out/auto_close.log 2>&1

git add public/index.html
if ! git diff --cached --quiet; then
  git commit -m "auto(마감): $(date +%F)" >> out/auto_close.log 2>&1
  git push origin main >> out/auto_close.log 2>&1
  echo "[$(date '+%F %T')] 마감 리포트 배포 완료" >> out/auto_close.log
else
  echo "[$(date '+%F %T')] 변경 없음 - 배포 생략" >> out/auto_close.log
fi
