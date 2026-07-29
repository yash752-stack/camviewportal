#!/bin/bash
# CamView Examination Compliance Portal — start the local server.
# Usage:  bash ~/Desktop/Compliance_Portal/run.sh
# Then open:  http://127.0.0.1:8077  (opens automatically)
#
# Self-contained: ships with the database, all evidence, AND the Python
# packages it needs (as wheels). The first run builds a small local
# environment from those bundled wheels — no internet required.
#
# IMPORTANT: the bundled wheels are built for Python 3.12 and 3.13 only.
# This launcher deliberately selects one of those versions. If neither is
# installed it stops with clear instructions instead of trying (and
# failing) to build against an unsupported Python.
set -e
cd "$(dirname "$0")/backend"

SUPPORTED="3.12 or 3.13"

# --- locate a Python whose version the bundled wheels actually cover ----------
# Preference order matches the bundle: 3.12 first, then 3.13. We probe explicit
# version-named interpreters AND check generic 'python3' in case it *is* 3.12/3.13.
PYBIN=""
PYVER=""
is_supported() {  # $1 = interpreter; echoes "MAJOR.MINOR" if 3.12/3.13, else nothing
  "$1" -c 'import sys; v=sys.version_info; print("%d.%d"%v[:2]) if v[:2] in ((3,12),(3,13)) else sys.exit(1)' 2>/dev/null
}
for cand in \
    python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 \
    python3.13 /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13 \
    python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    v="$(is_supported "$cand")" || true
    if [ -n "$v" ]; then PYBIN="$cand"; PYVER="$v"; break; fi
  fi
done

if [ -z "$PYBIN" ]; then
  # Report what *is* installed, so the user understands why we stopped.
  found=""
  for c in python3 python python3.10 python3.11 python3.14; do
    if command -v "$c" >/dev/null 2>&1; then
      found="$found  - $c -> $("$c" --version 2>&1)\n"
    fi
  done
  echo "──────────────────────────────────────────────────────────────"
  echo "  Cannot start: a supported Python ($SUPPORTED) was not found."
  echo ""
  echo "  This portal ships its packages as pre-built wheels for Python"
  echo "  $SUPPORTED only. Building against any other version would fail"
  echo "  offline, so setup is stopped here on purpose."
  echo ""
  if [ -n "$found" ]; then
    echo "  Python versions detected on this machine:"
    printf "$found"
    echo ""
  fi
  echo "  Fix: install Python 3.12 (recommended), then re-run this script:"
  echo "      brew install python@3.12"
  echo "  (No Homebrew? Get it at https://brew.sh )"
  echo "──────────────────────────────────────────────────────────────"
  exit 1
fi
echo "Using Python $PYVER  ($PYBIN)"

# --- one-time environment build (offline, from bundled wheels) ----------------
if [ ! -x ".venv/bin/uvicorn" ]; then
  echo "First run — building the local environment from bundled wheels…"
  # If a partial/failed .venv exists from a previous attempt, clear it.
  [ -d ".venv" ] && rm -rf .venv
  if ! "$PYBIN" -m venv .venv; then
    echo "ERROR: could not create the virtual environment with $PYBIN." >&2
    exit 1
  fi
  ./.venv/bin/python -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  # STRICT offline install. The wheels match this Python, so this must succeed;
  # if it doesn't, we stop loudly rather than silently source-building.
  if ! ./.venv/bin/python -m pip install --no-index --find-links wheels -r requirements.txt; then
    echo "──────────────────────────────────────────────────────────────" >&2
    echo "  Setup failed while installing the bundled packages." >&2
    echo "  The environment was left incomplete and has been removed." >&2
    echo "  Please re-run this script; if it fails again, report the" >&2
    echo "  pip output above." >&2
    echo "──────────────────────────────────────────────────────────────" >&2
    rm -rf .venv
    exit 1
  fi
  echo "Environment ready."
fi

# --- verify the app can import before we claim it's starting -------------------
if ! ./.venv/bin/python -c "import app.main" >/dev/null 2>&1; then
  echo "ERROR: the application failed to import. Setup may be incomplete —" >&2
  echo "       delete the 'backend/.venv' folder and re-run this script." >&2
  exit 1
fi

# --- a note about PDF report export (optional) --------------------------------
# Dashboards, maps and on-screen evidence work with no extra software.
# Generating downloadable PDF reports additionally needs Google Chrome/Edge.
if [ ! -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] \
   && [ ! -x "/Applications/Chromium.app/Contents/MacOS/Chromium" ] \
   && [ ! -x "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" ]; then
  echo "Note: Google Chrome not found — the portal runs fine, but PDF report"
  echo "      download needs Chrome installed (https://www.google.com/chrome/)."
fi

# free the port if a previous instance is still running
pkill -f "uvicorn app.main" 2>/dev/null || true
sleep 1

echo "CamView portal starting → http://127.0.0.1:8077"
# auto-open the browser once the server actually answers
( for i in $(seq 1 40); do
    if curl -s -o /dev/null http://127.0.0.1:8077/healthz; then
      if command -v open >/dev/null 2>&1; then open http://127.0.0.1:8077          # macOS
      elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://127.0.0.1:8077 # Linux
      fi
      break
    fi
    sleep 0.5
  done ) &

exec ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8077 --log-level warning
