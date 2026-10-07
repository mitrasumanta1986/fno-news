@echo off
title Create Desktop Shortcuts
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desk = [Environment]::GetFolderPath('Desktop');" ^
  "$dir = (Get-Location).Path;" ^
  "$s = $ws.CreateShortcut((Join-Path $desk 'F&O News Dashboard.lnk'));" ^
  "$s.TargetPath = Join-Path $dir 'Start.bat'; $s.WorkingDirectory = $dir;" ^
  "$s.IconLocation = (Join-Path $dir 'python\python.exe') + ',0';" ^
  "$s.Description = 'Start F&O News worker + dashboard'; $s.Save();" ^
  "$t = $ws.CreateShortcut((Join-Path $desk 'Stop F&O News.lnk'));" ^
  "$t.TargetPath = Join-Path $dir 'Stop.bat'; $t.WorkingDirectory = $dir;" ^
  "$t.IconLocation = \"$env:SystemRoot\System32\shell32.dll,27\";" ^
  "$t.Description = 'Stop F&O News worker + dashboard'; $t.Save();" ^
  "Write-Host 'Desktop shortcuts created: F&O News Dashboard  /  Stop F&O News'"
pause
