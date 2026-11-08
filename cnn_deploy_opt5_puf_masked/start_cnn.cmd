@echo off
setlocal
title Kosmo DonkeyCar CNN - opt4
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_cnn.ps1" %*
set "launch_exit=%ERRORLEVEL%"
if not "%launch_exit%"=="0" echo Startup failed. Check the messages above and integration\training\runs.
echo.
pause
exit /b %launch_exit%
