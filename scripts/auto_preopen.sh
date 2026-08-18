#!/usr/bin/env bash
# easystock 자동 개장 전 파이프라인 (리눅스 서버 cron 용)
set -u
cd "$(dirname "$0")/.." || exit 1
export PYTHONUTF8=1
[ -f "$HOME/.ssh/easystock_deploy" ] && export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/easystock_deploy -o StrictHostKeyChecking=accept-new"

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

mkdir -p out
"$PY" scripts/run_preopen.py --auto >> out/auto_preopen.log 2>&1

git add public/index.html
if ! git diff --cached --quiet; then
  git commit -m "auto(개장전): $(date +%F)" >> out/auto_preopen.log 2>&1
  git push origin main >> out/auto_preopen.log 2>&1
  echo "[$(date '+%F %T')] 개장 전 리포트 배포 완료" >> out/auto_preopen.log
else
  echo "[$(date '+%F %T')] 변경 없음 - 배포 생략" >> out/auto_preopen.log
fi
