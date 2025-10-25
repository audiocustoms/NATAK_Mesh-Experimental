#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# --- Logging: /var/log if root, otherwise $HOME
if [ "$(id -u)" -eq 0 ]; then
  LOG="/var/log/startup_sequence.log"
else
  LOG="$HOME/startup_sequence.log"
fi
umask 022
mkdir -p "$(dirname "$LOG")"
touch "$LOG"
# as of here, logging
exec >>"$LOG" 2>&1

ts(){ date +'%F %T'; }

echo "[$(ts)] Startup: begin"

# buffer for udev/Module
sleep 3

# 1) stop wpa_supplicant safe (ignore, if not active)
echo "[$(ts)] Stop interfering services (wpa_supplicant/NM/iwd)"
systemctl stop wpa_supplicant@wlan1.service wpa_supplicant.service NetworkManager iwd 2>/dev/null || true
pkill -f "wpa_supplicant.*-i wlan1" 2>/dev/null || true
rm -f /var/run/wpa_supplicant/wlan1 2>/dev/null || true

# 2) Mesh & Batman (open 802.11s)
echo "[$(ts)] start batmesh.sh (open 802.11s + batman-adv)"
/home/natak/mesh/batmesh.sh || echo "[$(ts)] WARN: batmesh.sh exit code $?"

# 3) wait till bat0 is up (max. 10s), just info (reduced to speed up boot)
echo "[$(ts)] wait for bat0=UP (max 10s)"
for i in $(seq 10); do
  if ip link show bat0 2>/dev/null | grep -q "state UP"; then
    echo "[$(ts)] OK: bat0 is UP"
    break
  fi
  sleep 1
done

# 4) status dump
echo "[$(ts)] Status: iw/batctl"
iw dev wlan1 info 2>/dev/null | egrep -i 'type|channel' || true
iw dev wlan1 station dump 2>/dev/null | sed -n '1,20p' || true
batctl n 2>/dev/null || true
batctl o 2>/dev/null || true

# 5) start RNS (as user natak)
echo "[$(ts)] start rnsd (as user natak)"
nohup runuser -l natak -c 'rnsd' >> /var/log/rnsd.log 2>&1 &

# 6) Start enhanced OGM monitor in background
#cd /home/natak/mesh/ogm_monitor && python3 enhanced_ogm_monitor.py &
#OGM_PID=$!

echo "[$(ts)] Startup: done"
exit 0
