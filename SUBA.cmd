@echo off
setlocal
cd /d "%~dp0"

if /I "%~1"=="ISTO" (
  shift
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0SUBA.ps1" ISTO %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0SUBA.ps1" %*
)

exit /b %errorlevel%
