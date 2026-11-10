#!/usr/bin/env bash
# Start PocketLinux services automatically when the phone boots.
#
# Install (Termux:Boot app from F-Droid required):
#   mkdir -p ~/.termux/boot
#   cp scripts/termux-boot.sh ~/.termux/boot/plx-boot.sh
#   chmod +x ~/.termux/boot/plx-boot.sh
#
# Boot scripts run without a TTY and with a minimal environment, so this file
# deliberately keeps things dumb: wait for storage, then start the supervisor.
set -u

PLX_HOME="${PLX_HOME:-$HOME/.plx}"
export PLX_HOME
mkdir -p "$PLX_HOME/logs"

exec >>"$PLX_HOME/logs/boot.log" 2>&1
echo "=== $(date -Iseconds) boot hook ==="

# Shared storage can take a few seconds to appear after boot.
for _ in $(seq 1 30); do
  [ -d "$HOME/storage/shared" ] && break
  sleep 2
done

PLX_BIN=""
for candidate in "$HOME/.local/bin/plx" "$HOME/.local/share/pocketlinux/bin/plx"; do
  [ -x "$candidate" ] && PLX_BIN="$candidate" && break
done
if [ -z "$PLX_BIN" ]; then
  echo "plx launcher not found — skipping"
  exit 0
fi

termux-wake-lock 2>/dev/null || true
"$PLX_BIN" service up
sleep 2
"$PLX_BIN" service status
echo "=== boot hook done ==="
