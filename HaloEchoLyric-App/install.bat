@echo off
setlocal EnableExtensions
title HaloEchoLyric - Install
cd /d "%~dp0"

set "SRC=%~dp0dist\HaloEchoLyric.exe"
set "DESTDIR=%LOCALAPPDATA%\Programs\HaloEchoLyric"
set "DEST=%DESTDIR%\HaloEchoLyric.exe"

echo ============================================================
echo   HaloEchoLyric - Install to this computer
echo ============================================================
echo.

if not exist "%SRC%" (
  echo [ERROR] dist\HaloEchoLyric.exe not found.
  echo         Run build.bat first, or place this script next to the exe.
  echo.
  pause
  exit /b 1
)

echo [1/3] Copying program to:
echo       %DESTDIR%
if not exist "%DESTDIR%" mkdir "%DESTDIR%"
copy /y "%SRC%" "%DEST%" >nul
if errorlevel 1 (
  echo [ERROR] copy failed.
  pause
  exit /b 1
)

echo [2/3] Creating shortcuts ...
set "LNK_DESK=%USERPROFILE%\Desktop\HaloEchoLyric.lnk"
set "LNK_MENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\HaloEchoLyric.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; foreach($p in @('%LNK_DESK%','%LNK_MENU%')){ $s=$w.CreateShortcut($p); $s.TargetPath='%DEST%'; $s.WorkingDirectory='%DESTDIR%'; $s.IconLocation='%DEST%,0'; $s.Description='HaloEchoLyric'; $s.Save() }" >nul 2>&1

echo [3/3] Starting HaloEchoLyric ...
start "" "%DEST%"

echo.
echo ============================================================
echo   Installed.
echo.
echo   Next: in EchoMusic open "Plugin management" and enable
echo         "Halo PixelBar Lyric Bridge".
echo         (Or click the plugin install button inside the app.)
echo.
echo   To remove everything, run uninstall.bat
echo ============================================================
echo.
pause
exit /b 0
