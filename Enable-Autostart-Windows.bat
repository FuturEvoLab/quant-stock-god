@echo off
rem Quantriel — start automatically at Windows login, in the background with no window (log: data\server.log).
rem To undo, double-click Disable-Autostart-Windows.bat.
chcp 65001 >nul
cd /d "%~dp0"
set "PYW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW for /f "delims=" %%i in ('py -3 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do set "PYW=%%i"
if not defined PYW (
  echo Python 3 (pythonw.exe) was not found. Install Python 3 and tick "Add Python to PATH".
  pause
  exit /b 1
)
powershell -NoProfile -Command "$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'QuantStockGod.lnk'; $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk); $s.TargetPath = '%PYW%'; $s.Arguments = '\"%~dp0server.py\"'; $s.WorkingDirectory = '%~dp0'; $s.WindowStyle = 7; $s.Save(); Write-Host ('Autostart enabled: ' + $lnk)"
echo Starting it now...
start "" "%PYW%" "%~dp0server.py"
timeout /t 3 >nul
start "" "http://127.0.0.1:8767"
pause
