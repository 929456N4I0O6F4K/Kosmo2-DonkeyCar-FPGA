@echo off
setlocal
chcp 65001 >nul
title Kosmo2 steering and ESC joint test
cd /d "%~dp0"
python -X utf8 -B tools\joint_test.py
pause
