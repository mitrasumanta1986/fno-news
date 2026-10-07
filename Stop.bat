@echo off
title F&O News Dashboard - Stop
echo Stopping worker and dashboard started from %~dp0 ...
powershell -NoProfile -Command "$py = Join-Path '%~dp0' 'python\python.exe'; Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.ExecutablePath -eq $py } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('Stopped ' + $_.ProcessId) }"
timeout /t 3 /nobreak >nul
