@echo off
REM easystock 자동 개장 전 파이프라인 (Windows 작업 스케줄러용)
REM 전일 마감 앵커 + 간밤 리서치 → 개장 전 재검토 뷰 → public/index.html → git push → Vercel.
setlocal
cd /d E:\Projects\stock_strategy
set PYTHONUTF8=1

python scripts\run_preopen.py --auto >> out\auto_preopen.log 2>&1

git add public/index.html
git diff --cached --quiet
if %errorlevel%==0 (
  echo [%DATE% %TIME%] 변경 없음 - 배포 생략 >> out\auto_preopen.log
) else (
  git commit -m "auto(개장전): %DATE%" >> out\auto_preopen.log 2>&1
  git push origin main >> out\auto_preopen.log 2>&1
  echo [%DATE% %TIME%] 개장 전 리포트 배포 완료 >> out\auto_preopen.log
)
endlocal
