@echo off
setlocal
cd /d "%~dp0"
set "USB_PYTHON=..\..\kintex\.venv-donkey-tof\Scripts\python.exe"
if not exist "%USB_PYTHON%" set "USB_PYTHON=python"
if "%~1"=="" (
  "%USB_PYTHON%" tools\usb_power.py deploy
) else (
  "%USB_PYTHON%" tools\usb_power.py deploy --port "%~1"
)
set "USB_EXIT=%ERRORLEVEL%"
if not "%USB_EXIT%"=="0" echo USB power deployment failed. See the evidence directory printed above.
pause
exit /b %USB_EXIT%
