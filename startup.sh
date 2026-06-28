#!/usr/bin/env bash
#
# startup.sh — Wrapper for auto-start on Linux.
# Sources .env, activates venv, and starts app.py in the background.
# Logs to logs/startup.log in the repo directory.
#
# Usage:
#   ./startup.sh               # interactive
#   ./startup.sh &             # background
#   nohup ./startup.sh &       # survive terminal close
#
# Install as a systemd user service for boot auto-start:
#   systemctl --user link "$(pwd)/deepseek-api.service"
#   systemctl --user enable  deepseek-api.service
#   systemctl --user start   deepseek-api.service
#

set -euo pipefail

RepoDir="$(cd "$(dirname "$0")" && pwd)"
PythonExe="$RepoDir/venv/bin/python"
AppPy="$RepoDir/app.py"
LogDir="$RepoDir/logs"
LogFile="$LogDir/startup.log"

mkdir -p "$LogDir"

# Load .env if present
EnvFile="$RepoDir/.env"
if [ -f "$EnvFile" ]; then
    set -a
    source "$EnvFile"
    set +a
fi

: "${HOST:=127.0.0.1}"
: "${PORT:=8000}"

# Kill any existing process on our port
if pid=$(lsof -ti "tcp:$PORT" 2>/dev/null); then
    echo "[$(date)] Killing existing process on port $PORT (PID $pid)" >> "$LogFile"
    kill "$pid" 2>/dev/null || true
    sleep 1
fi

# Start app.py, redirect output to log files
echo "[$(date)] Starting DeepSeek API on $HOST:$PORT" >> "$LogFile"

nohup "$PythonExe" "$AppPy" \
    >> "$LogDir/app.log" \
    2>> "$LogDir/app-error.log" \
    &

pid=$!
echo "[$(date)] Started PID $pid" >> "$LogFile"
echo "DeepSeek API started (PID $pid) — see logs/ for output."
