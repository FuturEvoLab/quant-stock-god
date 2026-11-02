@echo off
rem Quant Stock God — double-click to start on Windows.
rem If it is already running, just open the browser; otherwise run it in this window. Closing the window stops it.
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not defined PORT set "PORT=8767"
set "URL=http://127.0.0.1:%PORT%"

powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%/api/status'; if ($r.Content -match 'yahoo') { exit 0 } else { exit 1 } } catch { exit 1 }"
if %errorlevel%==0 (
  echo Quant Stock God is already running: %URL%
  start "" "%URL%"
  exit /b 0
)

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo Python 3 was not found. Install Python 3 from https://www.python.org/downloads/ (tick "Add Python to PATH"), then double-click this file again.
  pause
  exit /b 1
)

echo Starting Quant Stock God: %URL% (close this window to stop it)
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%URL%'"
%PY% server.py
pause
