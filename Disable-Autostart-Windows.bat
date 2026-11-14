@echo off
rem Quantriel — turn off Windows autostart (removes the startup item and stops the background server).
chcp 65001 >nul
powershell -NoProfile -Command "Remove-Item -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath('Startup')) 'QuantStockGod.lnk'); Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*server.py*' -and $_.CommandLine -like '*%~dp0*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }"
echo Autostart disabled and the background server stopped. Double-click Start-Quantriel.bat to start it manually.
pause
