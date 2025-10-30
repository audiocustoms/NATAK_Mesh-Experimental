#!/usr/bin/env bash
set -euo pipefail

# Manage WLAN2 for testing without affecting boot.
# Usage:
#   manage_wlan2.sh start     # unmask & start the unit if interface present
#   manage_wlan2.sh stop      # stop & mask the unit again
#   manage_wlan2.sh status    # show unit status and interface presence

UNIT="wpa_supplicant@wlan2.service"
IFPATH="/sys/class/net/wlan2"

cmd="$1"

exists() { [ -d "$IFPATH" ]; }

case "$cmd" in
  start)
    if exists; then
      echo "wlan2 exists -> unmask & start $UNIT"
      sudo systemctl unmask "$UNIT" || true
      sudo systemctl start "$UNIT"
      sudo systemctl status "$UNIT" --no-pager
    else
      echo "wlan2 interface not present. To create virtual interface for testing, use: sudo ip link add link wlan1 name wlan2 type macvlan" 1>&2
      exit 2
    fi
    ;;
  stop)
    echo "Stopping and masking $UNIT"
    sudo systemctl stop "$UNIT" || true
    sudo systemctl mask "$UNIT"
    sudo systemctl status "$UNIT" --no-pager || true
    ;;
  status)
    echo "Interface present: $(exists && echo yes || echo no)"
    sudo systemctl status "$UNIT" --no-pager || true
    ;;
  *)
    echo "Usage: $0 {start|stop|status}" 1>&2
    exit 1
    ;;
esac
