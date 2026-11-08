@echo off
cd /d "%~dp0"
if not exist "bin\kosmo-collect.exe" (
  echo Please run training\build.ps1 first.
  pause
  exit /b 1
)
echo Open the URL printed below in your browser. Ctrl+C exits.
bin\kosmo-collect.exe -backend sim -listen 127.0.0.1:8080 -data data
pause
