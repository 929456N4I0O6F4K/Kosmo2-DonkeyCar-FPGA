@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 -B tools\manual_calibrate.py
pause
