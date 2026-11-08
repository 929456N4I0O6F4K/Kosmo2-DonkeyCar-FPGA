@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_board.ps1" %*
set "deploy_exit=%errorlevel%"
if not "%deploy_exit%"=="0" echo Deployment failed. Read the error and log path above.
pause
exit /b %deploy_exit%
