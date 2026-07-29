@echo off
REM ===================================================================
REM  CamView Examination Compliance Portal - Windows launcher
REM  Just double-click this file. First run builds the environment
REM  from the bundled wheels (offline, ~1 min). Then the browser opens.
REM
REM  The bundled wheels are built for Python 3.12 and 3.13 ONLY. This
REM  launcher selects one of those on purpose. If neither is installed
REM  it stops with clear instructions instead of failing halfway.
REM ===================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0backend"

echo(
echo   CamView Compliance Portal
echo   -------------------------

REM --- find a Python whose version the bundled wheels cover (3.12, then 3.13) ---
REM Flat, sequential probes - no nested blocks - so each line is easy to verify.
REM Each probe only sets PYBIN if it is still empty, so the first match wins and
REM the preference order (py 3.12 > py 3.13 > python) is preserved.
set "PYBIN="

REM 1) Windows 'py' launcher, explicit 3.12
if not defined PYBIN py -3.12 -c "import sys" >nul 2>nul && set "PYBIN=py -3.12"
REM 2) Windows 'py' launcher, explicit 3.13
if not defined PYBIN py -3.13 -c "import sys" >nul 2>nul && set "PYBIN=py -3.13"
REM 3) a bare 'python' on PATH, but ONLY if it is itself 3.12 or 3.13
if not defined PYBIN python -c "import sys;sys.exit(0 if sys.version_info[:2] in ((3,12),(3,13)) else 1)" >nul 2>nul && set "PYBIN=python"

if not defined PYBIN (
  echo(
  echo   Cannot start: a supported Python ^(3.12 or 3.13^) was not found.
  echo(
  echo   This portal ships its packages as pre-built wheels for Python
  echo   3.12 and 3.13 only. Building against any other version would
  echo   fail offline, so setup is stopped here on purpose.
  echo(
  echo   Installed Python versions detected:
  where py    >nul 2>nul && py    -0p 2>nul
  where python>nul 2>nul && python --version 2>nul
  echo(
  echo   Fix: install Python 3.12 ^(recommended^) from
  echo       https://www.python.org/downloads/release/python-3129/
  echo   IMPORTANT: on the installer's first screen, tick
  echo       "Add python.exe to PATH"
  echo   Then double-click run.bat again.
  echo(
  pause
  exit /b 1
)
echo   Using Python:
%PYBIN% --version

REM --- one-time environment build (offline, from bundled wheels) --------------
if not exist ".venv\Scripts\uvicorn.exe" (
  echo   First run - building the local environment from bundled wheels...
  REM clear any partial venv from a previous failed attempt
  if exist ".venv" rmdir /s /q ".venv"
  %PYBIN% -m venv .venv
  if errorlevel 1 (
    echo   ERROR: could not create the virtual environment.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip >nul 2>nul
  REM STRICT offline install - the wheels match this Python, so this must work.
  REM If it fails we stop loudly instead of silently building from source.
  ".venv\Scripts\python.exe" -m pip install --no-index --find-links wheels -r requirements.txt
  if errorlevel 1 (
    echo(
    echo   Setup failed while installing the bundled packages.
    echo   The incomplete environment has been removed; please re-run
    echo   run.bat. If it fails again, report the pip output above.
    echo(
    rmdir /s /q ".venv"
    pause
    exit /b 1
  )
  echo   Environment ready.
)

REM --- verify the app imports before claiming it is starting ------------------
".venv\Scripts\python.exe" -c "import app.main" >nul 2>nul
if errorlevel 1 (
  echo(
  echo   ERROR: the application failed to import. Setup may be incomplete.
  echo   Delete the  backend\.venv  folder and run run.bat again.
  echo(
  pause
  exit /b 1
)

REM --- free port 8077 if a previous instance is still running -----------------
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8077 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>nul

echo(
echo   Portal starting  -^>  http://127.0.0.1:8077
echo   (leave this window open; close it to stop the portal)
echo(

REM open the browser the moment the server is actually answering (not a blind wait)
start "" /min cmd /c "@echo off & for /l %%i in (1,1,90) do (curl.exe -s -o nul http://127.0.0.1:8077/healthz && (start http://127.0.0.1:8077 & exit) || ping -n 2 127.0.0.1 >nul)"

".venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8077 --log-level warning
echo(
echo   Portal stopped.
pause
