@echo off
setlocal
chcp 65001 >nul
title Kosmo2 WP-1625 timed low-speed test
cd /d "%~dp0"
python -X utf8 -B tools\esc_calibrate.py --frequency 60 --neutral-us 1550
pause
