@echo off
REM ===================================================================
REM  CamView portal - start and open.
REM
REM  Double-click this file, or run it from a terminal. It starts the
REM  server, waits for it to answer, then opens the browser at the
REM  product ring. Close the black window to stop the server.
REM
REM  DATA: defaults to the demo set (tools\_bench) which holds the two
REM  sample examinations. For real data, comment out the line below and
REM  the app falls back to backend\data.
REM ===================================================================

cd /d "%~dp0"

set "CAMVIEW_DATA_DIR=%~dp0tools\_bench"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   No virtual environment found. Creating one...
  py -3.12 -m venv .venv 2>nul || python -m venv .venv
  .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  .venv\Scripts\python.exe -m pip install --quiet -r backend\requirements.txt
)

echo.
echo   Starting CamView on http://127.0.0.1:8077
echo   Sign in:  admin / innovatiview
echo   Leave this window open. Close it to stop the server.
echo.

REM open the browser once the port answers, without blocking the server
start "" /b powershell -NoProfile -Command ^
  "1..40 | ForEach-Object { try { Invoke-WebRequest -Uri http://127.0.0.1:8077/healthz -UseBasicParsing -TimeoutSec 1 | Out-Null; Start-Process 'http://127.0.0.1:8077/logout'; break } catch { Start-Sleep -Milliseconds 400 } }"

.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8077 --app-dir backend
