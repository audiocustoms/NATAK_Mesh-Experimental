#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# --- Settings ---
IF="wlan1"
MESH_SSID="natak_mesh"
FREQ=2462           # wifi channel (standard channel is 11)
REG="US"	    # wifi region
WAIT_PEER=5        # seconds, wait for mesh-peer (reduced during boot to avoid long blocking)
BRIDGE_NAME="br0"   # bridge name

ts(){ date +'%F %T'; }
log(){ echo "[$(ts)] $*"; }

log "[prep] stop wpa_supplicant (ignore if allready masked or deactivated)"
systemctl stop "wpa_supplicant@${IF}.service" wpa_supplicant.service NetworkManager iwd 2>/dev/null || true
pkill -f "wpa_supplicant.*-i ${IF}" 2>/dev/null || true
rm -f "/var/run/wpa_supplicant/${IF}" 2>/dev/null || true

log "[mesh] set RegDomain=${REG}, Typ=MESH, bringe ${IF} up"
iw reg set "${REG}" || true
ip link set "${IF}" down 2>/dev/null || true
iw dev "${IF}" set type mesh
ip link set "${IF}" up

log "[mesh] join open 802.11s: ssid='${MESH_SSID}', freq=${FREQ}"
# Leaver (idempotent), Join (open), Forwarding for batman-adv
iw dev "${IF}" mesh leave 2>/dev/null || true
iw dev "${IF}" mesh join "${MESH_SSID}" freq "${FREQ}"
iw dev "${IF}" set mesh_param mesh_fwding=0 || true

# MTU little bit bigger for batman-adv + 802.11s Overhead
ip link set "${IF}" mtu 1560 || true

log "[batman] load module, bat0 setup/up, ${IF} connect"
modprobe batman-adv 2>/dev/null || true
ip link add bat0 type batadv 2>/dev/null || true
ip link set bat0 up
batctl if add "${IF}" 2>/dev/null || true
batctl dat 1
batctl ap_isolation 0

# Optional: bat0 to br0 join, if bridge is existing
if ip link show "${BRIDGE_NAME}" >/dev/null 2>&1; then
  log "[bridge] join bat0 in ${BRIDGE_NAME}"
  ip link set "${BRIDGE_NAME}" up || true
  ip link set dev bat0 master "${BRIDGE_NAME}" || true
fi

# Optional: wait for peer (just info)
log "[wait] wait for ${WAIT_PEER}s mesh-peer"
for i in $(seq "${WAIT_PEER}"); do
  if iw dev "${IF}" station dump | grep -q "^Station "; then
    log "[ok] minimum one mesh-peer available"
    break
  fi
  sleep 1
done

# Status (not critical)
log "[status] Interface:"
iw dev "${IF}" info | egrep -i 'type|channel|addr' || true
log "[status] Peers:"
iw dev "${IF}" station dump | sed -n '1,30p' || true
log "[status] batman-adv Nachbarn/Originators:"
batctl n || true
batctl o || true

log "[done] batmesh.sh erfolgreich abgeschlossen"
exit 0
