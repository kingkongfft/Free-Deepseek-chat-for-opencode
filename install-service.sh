#!/usr/bin/env bash
#
# install-service.sh — Install the deepseek-api systemd user service.
#
# Usage:
#   ./install-service.sh                 # install and start
#   ./install-service.sh --uninstall     # stop and remove
#

set -euo pipefail

ServiceName="deepseek-api.service"
RepoDir="$(cd "$(dirname "$0")" && pwd)"
ServiceFile="$RepoDir/$ServiceName"

uninstall() {
    echo "Stopping service..."
    systemctl --user stop "$ServiceName" 2>/dev/null || true
    echo "Disabling service..."
    systemctl --user disable "$ServiceName" 2>/dev/null || true
    echo "Removing service link..."
    systemctl --user unlink "$ServiceName" 2>/dev/null || true
    echo "Done — service uninstalled."
    exit 0
}

if [ "${1:-}" = "--uninstall" ]; then
    uninstall
fi

# Ensure we're in the repo directory
if [ "$RepoDir" != "$(pwd)" ]; then
    echo "Run this script from the repo directory: $RepoDir"
    exit 1
fi

# Link the service file so systemd can find it
echo "Linking service file..."
systemctl --user link "$ServiceFile" 2>/dev/null || true

# Reload daemon so the new service is picked up
echo "Reloading systemd daemon..."
systemctl --user daemon-reload

# Enable and start
echo "Enabling service (starts at login)..."
systemctl --user enable "$ServiceName"

echo "Starting service now..."
systemctl --user start "$ServiceName"

# Show status
sleep 2
echo ""
systemctl --user status "$ServiceName" --no-pager

echo ""
echo "Service installed. Check logs with:"
echo "  journalctl --user -u $ServiceName -f"
echo "Health check:"
echo "  curl http://127.0.0.1:8000/healthz"
