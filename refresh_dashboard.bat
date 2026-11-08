@echo off
rem Bấm đúp để làm mới dashboard sau khi thả file báo cáo mới vào 00_Raw.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
python refresh_dashboard.py %*
echo.
pause
