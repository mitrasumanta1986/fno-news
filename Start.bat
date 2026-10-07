@echo off
title F&O News Dashboard - Launcher
cd /d "%~dp0"

set "PY=%~dp0python\python.exe"
set PYTHONNOUSERSITE=1
set PYTHONUTF8=1

if not exist "%PY%" (
    echo Bundled Python not found in %~dp0python
    echo Re-extract the full zip file and try again.
    pause
    exit /b 1
)

if not exist ".env" if exist ".env.example" copy ".env.example" ".env" >nul
if not exist "data" mkdir data
if not exist "logs" mkdir logs

rem --- Worker (data collector): start only if it is not already running ---
powershell -NoProfile -Command "if (Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*worker.py*' }) { exit 1 } else { exit 0 }"
if %errorlevel%==0 (
    echo Starting worker...
    start "News Worker - leave open" cmd /k ""%PY%" worker.py"
) else (
    echo Worker is already running.
)

rem --- Dashboard: start only if port 8501 is free ---
netstat -ano | findstr /r /c:":8501 .*LISTENING" >nul
if errorlevel 1 (
    echo Starting dashboard...
    start "News Dashboard - leave open" cmd /k ""%PY%" -m streamlit run app.py --server.headless true"
    timeout /t 8 /nobreak >nul
) else (
    echo Dashboard is already running.
)

start "" http://localhost:8501
exit /b 0
