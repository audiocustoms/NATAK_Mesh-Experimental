#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# --- Settings ---
IF="wlan1"
MESH_SSID="natak_mesh"
FREQ=2462           # channel 11 (2.4 GHz)
REG="US"
WAIT_PEER=60        # Sekunden, maximal auf sichtbaren Mesh-Peer warten
BRIDGE_NAME="br0"   # falls vorhanden, wird bat0 hinein gebr�ckt; sonst ignoriert

ts(){ date +'%F %T'; }
log(){ echo "[$(ts)] $*"; }

log "[prep] Stoppe potenzielle St�rer (harmlos, falls nicht aktiv)"
systemctl stop "wpa_supplicant@${IF}.service" wpa_supplicant.service NetworkManager iwd 2>/dev/null || true
pkill -f "wpa_supplicant.*-i ${IF}" 2>/dev/null || true
rm -f "/var/run/wpa_supplicant/${IF}" 2>/dev/null || true

log "[mesh] Setze RegDomain=${REG}, Typ=MESH, bringe ${IF} hoch"
iw reg set "${REG}" || true
ip link set "${IF}" down 2>/dev/null || true
iw dev "${IF}" set type mesh
ip link set "${IF}" up

log "[mesh] Trete offenem 802.11s bei: ssid='${MESH_SSID}', freq=${FREQ}"
# Leaver (idempotent), Join (offen), Forwarding f�r batman-adv aus
iw dev "${IF}" mesh leave 2>/dev/null || true
iw dev "${IF}" mesh join "${MESH_SSID}" freq "${FREQ}"
iw dev "${IF}" set mesh_param mesh_fwding=0 || true

# MTU etwas gr��er f�r batman-adv + 802.11s Overhead
ip link set "${IF}" mtu 1560 || true

log "[batman] Modul laden, bat0 anlegen/hochfahren, ${IF} anbinden"
modprobe batman-adv 2>/dev/null || true
ip link add bat0 type batadv 2>/dev/null || true
ip link set bat0 up
batctl if add "${IF}" 2>/dev/null || true
batctl dat 1
batctl ap_isolation 0

# Optional: bat0 in br0 h�ngen, wenn Bridge existiert
if ip link show "${BRIDGE_NAME}" >/dev/null 2>&1; then
  log "[bridge] H�nge bat0 in ${BRIDGE_NAME}"
  ip link set "${BRIDGE_NAME}" up || true
  ip link set dev bat0 master "${BRIDGE_NAME}" || true
fi

# Optional: auf Peer warten (rein informativ)
log "[wait] Warte bis zu ${WAIT_PEER}s auf einen sichtbaren Mesh-Peer�"
for i in $(seq "${WAIT_PEER}"); do
  if iw dev "${IF}" station dump | grep -q "^Station "; then
    log "[ok] Mindestens ein Mesh-Peer sichtbar"
    break
  fi
  sleep 1
done

# Status-Ausgabe (nicht kritisch)
log "[status] Interface:"
iw dev "${IF}" info | egrep -i 'type|channel|addr' || true
log "[status] Peers:"
iw dev "${IF}" station dump | sed -n '1,30p' || true
log "[status] batman-adv Nachbarn/Originators:"
batctl n || true
batctl o || true

log "[done] batmesh.sh erfolgreich abgeschlossen"
exit 0