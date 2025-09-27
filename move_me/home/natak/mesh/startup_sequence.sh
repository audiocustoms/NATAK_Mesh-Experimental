#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# --- Logging: /var/log wenn root, sonst $HOME
if [ "$(id -u)" -eq 0 ]; then
  LOG="/var/log/startup_sequence.log"
else
  LOG="$HOME/startup_sequence.log"
fi
umask 022
mkdir -p "$(dirname "$LOG")"
touch "$LOG"
# Ab hier alles ins Log
exec >>"$LOG" 2>&1

ts(){ date +'%F %T'; }

echo "[$(ts)] Startup: begin"

# Kleiner Puffer für udev/Module
sleep 3

# 1) Störer sicher beenden (harmlos, falls nicht aktiv)
echo "[$(ts)] Stop interfering services (wpa_supplicant/NM/iwd)"
systemctl stop wpa_supplicant@wlan1.service wpa_supplicant.service NetworkManager iwd 2>/dev/null || true
pkill -f "wpa_supplicant.*-i wlan1" 2>/dev/null || true
rm -f /var/run/wpa_supplicant/wlan1 2>/dev/null || true

# 2) Mesh & Batman (offenes 802.11s)
echo "[$(ts)] Starte batmesh.sh (open 802.11s + batman-adv)"
/home/natak/mesh/batmesh.sh || echo "[$(ts)] WARN: batmesh.sh exit code $?"

# 3) Warten bis bat0 oben ist (max. 30s), rein informativ
echo "[$(ts)] Warte auf bat0=UP (max 30s)"
for i in $(seq 30); do
  if ip link show bat0 2>/dev/null | grep -q "state UP"; then
    echo "[$(ts)] OK: bat0 ist UP"
    break
  fi
  sleep 1
done

# 4) Kurzer Statusdump (nicht kritisch)
echo "[$(ts)] Status: iw/batctl"
iw dev wlan1 info 2>/dev/null | egrep -i 'type|channel' || true
iw dev wlan1 station dump 2>/dev/null | sed -n '1,20p' || true
batctl n 2>/dev/null || true
batctl o 2>/dev/null || true

# 5) RNS starten (als User natak)
echo "[$(ts)] Starte rnsd (als Benutzer natak)"
nohup runuser -l natak -c 'rnsd' >> /var/log/rnsd.log 2>&1 &

# 6) OGM-Monitor nur starten, wenn Datei existiert und bat0 up ist
if ip link show bat0 2>/dev/null | grep -q "state UP"; then
  if [ -f /home/natak/mesh/ogm_monitor/enhanced_ogm_monitor.py ]; then
    echo "[$(ts)] Starte OGM Monitor"
    ( cd /home/natak/mesh/ogm_monitor && python3 enhanced_ogm_monitor.py ) >> "$LOG" 2>&1 &
  else
    echo "[$(ts)] OGM Monitor nicht gefunden – überspringe"
  fi
else
  echo "[$(ts)] WARN: bat0 nicht UP – OGM Monitor wird nicht gestartet"
fi

echo "[$(ts)] Startup: done"
exit 0
