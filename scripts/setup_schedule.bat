@echo off
REM easystock 매일 자동화 등록 (Windows 작업 스케줄러). 한 번만 실행하면 됨.
REM 평일 마감 15:45 / 개장 전 08:10 (로컬 시간 = KST). 관리자 권한 불필요(현재 사용자로 실행).
REM 해제: schtasks /Delete /TN easystock-close /F  &  /TN easystock-preopen /F

schtasks /Create /TN "easystock-close" /TR "E:\Projects\stock_strategy\scripts\auto_close.bat" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 15:45 /F
schtasks /Create /TN "easystock-preopen" /TR "E:\Projects\stock_strategy\scripts\auto_preopen.bat" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 08:10 /F

echo.
echo === 등록된 작업 ===
schtasks /Query /TN "easystock-close" /FO LIST | findstr /C:"TaskName" /C:"다음 실행" /C:"Next Run"
schtasks /Query /TN "easystock-preopen" /FO LIST | findstr /C:"TaskName" /C:"다음 실행" /C:"Next Run"
echo.
echo 완료. 그 시간에 PC가 켜져 있으면 자동 실행됩니다.
echo (auto_update=false 로 두면 예약 실행이 스스로 건너뜁니다 - API 비용 절약)
pause
