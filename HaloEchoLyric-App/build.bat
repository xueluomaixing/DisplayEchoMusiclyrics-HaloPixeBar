@echo off
setlocal
title HaloEchoLyric - Build
cd /d "%~dp0"

set "VPY=%~dp0.venv\Scripts\python.exe"
if not exist "%VPY%" (
  echo [ERROR] venv not found. Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

echo ============================================================
echo   Building HaloEchoLyric.exe  (onefile, no console)
echo ============================================================
echo.

"%VPY%" -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name HaloEchoLyric ^
  --icon "src\icon.ico" ^
  --distpath "dist" --workpath "build" ^
  --add-data "src\ui;ui" ^
  --add-data "src\plugin;plugin" ^
  --collect-all webview ^
  --collect-all clr_loader ^
  --hidden-import clr ^
  --hidden-import pythonnet ^
  --hidden-import pystray ^
  --hidden-import PIL._tkinter_finder ^
  "src\app.py"

if errorlevel 1 (
  echo.
  echo [ERROR] build failed.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   Done: dist\HaloEchoLyric.exe
echo ============================================================
dir /b "dist\HaloEchoLyric.exe"
pause
exit /b 0
