@echo off
setlocal EnableExtensions
title HaloEchoLyric - Uninstall

echo ============================================================
echo   HaloEchoLyric - Remove everything
echo ============================================================
echo.

echo [1/5] Stopping the program ...
taskkill /IM HaloEchoLyric.exe /F >nul 2>&1
ping -n 2 127.0.0.1 >nul

echo [2/5] Removing EchoMusic plugin ...
if exist "%APPDATA%\echo-music\plugins\halo-pixelbar-lyric" (
  rmdir /s /q "%APPDATA%\echo-music\plugins\halo-pixelbar-lyric"
  if exist "%APPDATA%\echo-music\plugins\halo-pixelbar-lyric" (
    echo       FAILED - close EchoMusic and run this script again
  ) else (
    echo       removed
  )
) else (
  echo       not installed - skipped
)

echo [3/5] Removing shortcuts ...
del /f /q "%USERPROFILE%\Desktop\HaloEchoLyric.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\HaloEchoLyric.lnk" >nul 2>&1
del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\HaloEchoLyric.lnk" >nul 2>&1
echo       done

echo [4/5] Removing settings and logs ...
if exist "%APPDATA%\HaloEchoLyric" (
  rmdir /s /q "%APPDATA%\HaloEchoLyric"
  echo       removed
) else (
  echo       not present - skipped
)

echo [5/5] Removing installed program ...
if exist "%LOCALAPPDATA%\Programs\HaloEchoLyric" (
  rmdir /s /q "%LOCALAPPDATA%\Programs\HaloEchoLyric"
  echo       removed
) else (
  echo       not present - skipped
)

echo.
echo ============================================================
echo   Finished. Nothing of HaloEchoLyric is left.
echo   (The project folder with sources is NOT touched.)
echo ============================================================
echo.
pause
exit /b 0
