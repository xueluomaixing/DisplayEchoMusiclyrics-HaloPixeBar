@echo off
setlocal
title HaloEchoLyric - Dev Run
cd /d "%~dp0"

set "VPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo [ERROR] venv not found.
  echo   python -m venv .venv
  echo   .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

echo Starting HaloEchoLyric (dev mode) ...
"%VPY%" "src\app.py" %*

if errorlevel 1 (
  echo.
  echo [ERROR] exited with an error. See messages above.
  pause
)
exit /b 0
