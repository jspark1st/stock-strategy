@echo off
REM easystock 자동 마감 파이프라인 (Windows 작업 스케줄러용)
REM 로컬 .env 키로 데이터 수집·리포트 생성 → public/index.html → git push → Vercel 자동배포.
REM auto_update=false 면 run_close 가 스스로 건너뜀(API 비용 절약).
setlocal
cd /d E:\Projects\stock_strategy
set PYTHONUTF8=1

python scripts\run_close.py --auto >> out\auto_close.log 2>&1

git add public/index.html
git diff --cached --quiet
if %errorlevel%==0 (
  echo [%DATE% %TIME%] 변경 없음 - 배포 생략 >> out\auto_close.log
) else (
  git commit -m "auto(마감): %DATE%" >> out\auto_close.log 2>&1
  git push origin main >> out\auto_close.log 2>&1
  echo [%DATE% %TIME%] 마감 리포트 배포 완료 >> out\auto_close.log
)
endlocal
