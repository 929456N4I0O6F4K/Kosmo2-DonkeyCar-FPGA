@echo off
cd /d "%~dp0"
python tools/board_link.py status --factory-password
pause
