#!/usr/bin/env bash
# ==============================================================================
# FRESH NODE SETUP (OrbisMesh) – safer, structured, idempotent-ish
# ------------------------------------------------------------------------------

set -Eeuo pipefail


# -------- Confirmation ---------------------------------------------------------
echo
echo "=============================================================="
echo "This script will install 'OrbisMesh' on your system."
echo "=============================================================="
read -r -p "Do you want to continue? [y/n] " ans
case "$ans" in
  [Yy]*) echo "Proceeding with setup...";;
  *) echo "Aborted."; exit 1;;
esac

# --- WiFi naming guard: Reserve wlan0 for onboard or dummy, USB starts at wlan1 ---

# Use sudo only when needed
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; else SUDO=""; fi

# Helper: list wifi ifaces
_list_wifi_ifaces() {
  for p in /sys/class/net/*; do
    n="$(basename "$p")"
    # consider only real wifi (wireless/phy80211)
    if [ -d "$p/wireless" ] || [ -e "$p/phy80211" ]; then
      echo "$n"
    fi
  done
}

# Helper: return 0 if iface is on USB bus
_is_usb_iface() {
  local ifc="$1"
  local devpath
  devpath="$(readlink -f "/sys/class/net/$ifc/device" 2>/dev/null || true)"
  # empty devpath for dummy or special cases -> treat as non-USB
  [[ -n "$devpath" && "$devpath" == *"/usb"* ]]
}

# Helper: try to guess driver module providing an iface
_iface_module() {
  local ifc="$1"
  local mod
  mod="$(basename "$(readlink -f "/sys/class/net/$ifc/device/driver/module" 2>/dev/null)" 2>/dev/null || true)"
  [ -n "$mod" ] && echo "$mod"
}

# Ensure dummy wlan0 exists and is up
_ensure_dummy_wlan0() {
  $SUDO modprobe dummy || true
  # if wlan0 exists and is not dummy, remove/rename later
  if ! ip link show wlan0 >/dev/null 2>&1; then
    $SUDO ip link add wlan0 type dummy 2>/dev/null || true
  fi
  $SUDO ip link set wlan0 up 2>/dev/null || true
}

# Remove (unload) all detected wifi adapters by module, to re-enumerate cleanly
_remove_all_wifi_adapters() {
  local ifc mod
  local -A SEEN=()
  # bring all wifi ifaces down first
  for ifc in $(_list_wifi_ifaces); do
    $SUDO ip link set "$ifc" down 2>/dev/null || true
  done
  # collect unique modules
  for ifc in $(_list_wifi_ifaces); do
    mod="$(_iface_module "$ifc")"
    # skip empty or dummy
    if [ -n "$mod" ] && [ "$mod" != "dummy" ]; then
      SEEN["$mod"]=1
    fi
  done
  # unload modules (this will detach devices)
  for mod in "${!SEEN[@]}"; do
    $SUDO modprobe -r "$mod" 2>/dev/null || true
  done
}

# Re-load previously unloaded modules (best-effort: udev will re-create ifaces)
_reload_modules() {
  local mod
  # Try to read loaded modules list from lsmod is not reliable here,
  # instead just probe common wifi stacks back; also re-probe saved set if available.
  # You can extend this if you know your exact USB chips.
  for mod in mt76 mt76x02_usb mt76x2u mt7601u rtl8xxxu ath9k_htc brcmfmac; do
    $SUDO modprobe "$mod" 2>/dev/null || true
  done
  # Also trigger udev add in case devices are present
  $SUDO udevadm trigger --subsystem-match=net --action=add 2>/dev/null || true
}

# Ensure onboard (non-USB) wifi ends up as wlan0; if absent, keep dummy
_ensure_onboard_is_wlan0() {
  local onboard_if="" other
  for other in $(_list_wifi_ifaces); do
    if _is_usb_iface "$other"; then
      continue
    fi
    onboard_if="$other"
    break
  done

  if [ -z "$onboard_if" ]; then
    # No onboard found -> keep/ensure dummy on wlan0
    _ensure_dummy_wlan0
    return 0
  fi

  # If wlan0 already exists and is the onboard iface, we're good
  if [ "$onboard_if" = "wlan0" ]; then
    return 0
  fi

  # If wlan0 exists and is dummy, remove it to free the name
  if ip -d link show wlan0 2>/dev/null | grep -q "<BROADCAST" ; then
    # cannot reliably detect dummy via 'ip -d' on all distros; try a safe delete
    $SUDO ip link set wlan0 down 2>/dev/null || true
    $SUDO ip link delete wlan0 2>/dev/null || true
  fi

  # If wlan0 exists and is a USB wifi, move it away first
  if ip link show wlan0 >/dev/null 2>&1; then
    $SUDO ip link set wlan0 down 2>/dev/null || true
    # Find a free name for temporary storage
    local tmpname="wlan9tmp"
    $SUDO ip link set wlan0 name "$tmpname" 2>/dev/null || true
  fi

  # Finally rename onboard to wlan0
  $SUDO ip link set "$onboard_if" down 2>/dev/null || true
  $SUDO ip link set "$onboard_if" name wlan0
  $SUDO ip link set wlan0 up 2>/dev/null || true
}

# --- Prompt with 10s timeout (default: Yes) ---
echo
echo "=============================================================="
echo "Does your system provide onboard WiFi?"
echo "Press Enter for 'Yes' (default in 10 seconds) or type 'No'."
echo "=============================================================="
printf "Answer [Y/n]: "
if read -r -t 10 REPLY; then
  : # got input
else
  REPLY="Y"
  echo "Y"
fi

case "$REPLY" in
  [Nn]*)
    echo "[WiFi guard] No onboard WiFi selected."
    echo "[WiFi guard] Removing all detected WiFi adapters..."
    _remove_all_wifi_adapters
    echo "[WiFi guard] Ensuring dummy on wlan0..."
    _ensure_dummy_wlan0
    echo "[WiFi guard] Re-initializing USB WiFi adapters (they will enumerate from wlan1)..."
    _reload_modules
    ;;
  *)
    echo "[WiFi guard] Yes (onboard WiFi present). Verifying wlan0 assignment..."
    _ensure_onboard_is_wlan0
    ;;
esac

# End of WiFi naming guard

# -------- Logging (warnings & errors) -----------------------------------------
LOG_FILE="/tmp/fresh_node.log"
: > "$LOG_FILE"   # clear file on start
# redirect stderr to both console and log
exec 2> >(tee -a "$LOG_FILE" >&2)
# -------- Settings -------------------------------------------------------------
MOVE_SRC="${HOME}/move_me"           # source of files to be copied
RUN_RESET_ID=false                   # via --reset-id
DO_REBOOT=false                      # via --do-reboot
USE_PIPX=true                        # prefer pipx for Python tools
LOG_TS() { printf '[%s] ' "$(date '+%F %T')"; }

# -------- Helpers --------------------------------------------------------------
die() { LOG_TS; echo "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Command not found: $1"; }
sudocheck() { [ "$(id -u)" -eq 0 ] || need sudo; }
confirm() {
  local prompt="$1"
  read -r -p "$prompt [y/N] " ans
  [[ "${ans:-N}" =~ ^[Yy]$ ]]
}

usage() {
  cat <<EOF
Usage: $(basename "$0") [--reset-id] [--no-pipx] [--do-reboot] [--dry-run]

  --reset-id    Reset machine-id/SSH keys (for cloned images).
  --no-pipx     Use pip3 system-wide (less clean).
  --do-reboot   Perform a reboot at the end.
  --dry-run     Only show what would be done.
EOF
}

DRY_RUN=false
run() { LOG_TS; echo "+ $*"; $DRY_RUN || eval "$@"; }

# -------- Argparse -------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset-id)   RUN_RESET_ID=true; shift ;;
    --no-pipx)    USE_PIPX=false; shift ;;
    --do-reboot)  DO_REBOOT=true; shift ;;
    --dry-run)    DRY_RUN=true; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

# -------- Preflight ------------------------------------------------------------
sudocheck
need bash
need tee
need awk
need sed
need grep
need systemctl || true

LOG_TS; echo "Starting setup …"
LOG_TS; echo "Options: reset-id=${RUN_RESET_ID}, pipx=${USE_PIPX}, reboot=${DO_REBOOT}, dry-run=${DRY_RUN}"

# -------- Optional: Reset for cloned images -----------------------------------
if $RUN_RESET_ID; then
  LOG_TS; echo "Running machine reset for cloned images …"
  run "rm -rf /home/natak/linux || true"
  # Reset machine-id & SSH keys carefully
  run "sudo systemctl stop systemd-networkd || true"
  run "sudo rm -f /etc/machine-id"
  run "echo -n > /etc/machine-id"
  run "sudo systemd-machine-id-setup"
  run "sudo rm -f /etc/ssh/ssh_host_*"
  run "sudo dpkg-reconfigure -f noninteractive openssh-server"
  run "sudo systemctl restart systemd-networkd || true"
fi

# -------- Packages -------------------------------------------------------------
LOG_TS; echo "Installing system packages …"
export DEBIAN_FRONTEND=noninteractive
run "sudo apt-get update -y"
sudo DEBIAN_FRONTEND=readline apt-get install -y --no-install-recommends hostapd batctl
sudo DEBIAN_FRONTEND=readline apt-get install -y --no-install-recommends python3 python3-pip pipx
sudo DEBIAN_FRONTEND=readline apt-get install -y --no-install-recommends aircrack-ng iperf3 network-manager alfred dnsmasq

# Load batman-adv kernel module & keep it persistent
run "sudo modprobe -v batman_adv"
run "echo 'batman_adv' | sudo tee /etc/modules-load.d/batman_adv.conf >/dev/null"



# -------- Python Tools (Reticulum, Nomadnet, Flask) ----------------------------
LOG_TS; echo "Installing Python tools … (preferring pipx)"

# -------- Cleanup old binaries (rns & nomadnet) --------------------------------
# Remove old files/symlinks in ~/.local/bin that block pipx from linking correctly
for b in rncp rnid rnir rnodeconf rnpath rnprobe rnsd rnstatus rnx; do
  tgt="${HOME}/.local/bin/${b}"
  if [ -e "$tgt" ]; then
    if [ -L "$tgt" ]; then
      if ! readlink -f "$tgt" | grep -q "${HOME}/.local/pipx/venvs/rns/bin/${b}"; then
        run "rm -f \"$tgt\""
      fi
    else
      run "rm -f \"$tgt\""
    fi
  fi
done

# Nomadnet binary cleanup
tgt="${HOME}/.local/bin/nomadnet"
if [ -e "$tgt" ]; then
  if [ -L "$tgt" ]; then
    if ! readlink -f "$tgt" | grep -q "${HOME}/.local/pipx/venvs/nomadnet/bin/nomadnet"; then
      run "rm -f \"$tgt\""
    fi
  else
    run "rm -f \"$tgt\""
  fi
fi

if $USE_PIPX; then
  run "pipx ensurepath"

  # Clean up conflicting user-bin entries for rns and nomadnet so pipx can link its shims
  CLEAN_BIN_DIR="${HOME}/.local/bin"
  # rns binaries
  for b in rncp rnid rnir rnodeconf rnpath rnprobe rnsd rnstatus rnx; do
    tgt="${CLEAN_BIN_DIR}/${b}"
    if [ -e "$tgt" ]; then
      if [ -L "$tgt" ]; then
        if ! readlink -f "$tgt" | grep -q "${HOME}/.local/pipx/venvs/rns/bin/${b}"; then
          run "rm -f \"$tgt\""
        fi
      else
        run "rm -f \"$tgt\""
      fi
    fi
  done
  # nomadnet binary
  tgt="${CLEAN_BIN_DIR}/nomadnet"
  if [ -e "$tgt" ]; then
    if [ -L "$tgt" ]; then
      if ! readlink -f "$tgt" | grep -q "${HOME}/.local/pipx/venvs/nomadnet/bin/nomadnet"; then
        run "rm -f \"$tgt\""
      fi
    else
      run "rm -f \"$tgt\""
    fi
  fi

  # Reinstall via pipx to ensure proper shims
  run "pipx uninstall rns || true"
  run "pipx install rns"
  run "pipx install flask || pipx upgrade flask"
else
  run "pip3 install --upgrade --break-system-packages rns flask"
  # fallback: extend PATH for ~/.local/bin
  run "grep -q 'HOME/.local/bin' ~/.bashrc || echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
fi

# -------- File copies ----------------------------------------------------------
LOG_TS; echo "Copying configuration files from ${MOVE_SRC} …"
[ -d "${MOVE_SRC}" ] || die "Source not found: ${MOVE_SRC}"

# User directories
dst="${HOME}/"
for d in mesh mesh_monitor .reticulum; do
  src="${MOVE_SRC}/home/natak/${d}"
  if [ -d "$src" ]; then
    run "cp -a -v \"$src\" \"$dst\""
  else
    LOG_TS; echo "Skipping: ${src} not found."
  fi
done

# Note: consider disabling wpa_supplicant if hostapd should run exclusively in AP mode.
# This is system-specific — intentionally NOT automated.

# -------- Permissions ----------------------------------------------------------
LOG_TS; echo "Setting permissions on user directories …"
for d in mesh mesh_monitor .reticulum .nomadnet; do
  dst="${HOME}/${d}"
  if [ -d "$dst" ]; then
    run "find \"$dst\" -type d -exec chmod 0777 {} \\;"
  fi
done

# System directories
run "sudo install -d /etc/hostapd /etc/modprobe.d /etc/systemd/network /etc/systemd/system /etc/wpa_supplicant /etc/sudoers.d /etc/dnsmasq.d /etc/sysctl.d"

# Concrete copies (only if present)
for name in etc/hostapd etc/modprobe.d etc/systemd/network etc/systemd/system etc/wpa_supplicant /etc/sudoers.d /etc/dnsmasq.d /etc/sysctl.d; do
  if test -d "${MOVE_SRC}/${name}"; then
    run "sudo cp -v ${MOVE_SRC}/${name}/* /${name}/"
  else
    LOG_TS; echo "Skipping: ${MOVE_SRC}/${name} not found."
  fi
done

# -------- Services/Daemons -----------------------------------------------------
LOG_TS; echo "Enabling/configuring services …"
run "sudo systemctl enable NetworkManager.service"
run "sudo systemctl enable dnsmasq"
run "sudo systemctl enable alfred.service"
run "sudo systemctl enable alfred-hostname.timer"
run "sudo systemctl enable ogm-monitor.service"
run "sudo systemctl unmask hostapd || true"

# -------- Update values --------------------------------------------------------

sudo="sudo "

function replace
{
	old=$1
	name=$2
	file=$3

	echo -n "$name: [${old}]: "
	read new
	if [ "$new" != "" ] ; then
		clean=${new//\//\\\/}
		${sudo}sed -e "s/${old}/${clean}/" -i $file
	fi
}

root=""

# Farbdefinitionen
GREEN="\e[32m"
RESET="\e[0m"

# SSID
line="$(grep '^ssid=' ${root}/etc/hostapd/hostapd.conf)"
ssid=${line#ssid=}
echo -e "${GREEN}Change local OrbisMesh SSID${RESET}"
replace "$ssid" "${GREEN}Change local OrbisMesh SSID${RESET}" "${root}/etc/hostapd/hostapd.conf"

# Passwort
line="$(grep '^wpa_passphrase=' ${root}/etc/hostapd/hostapd.conf)"
wpa_pass=${line#wpa_passphrase=}
echo -e "${GREEN}Change local SSID Password${RESET}"
replace "$wpa_pass" "${GREEN}Change local SSID Password${RESET}" "${root}/etc/hostapd/hostapd.conf"

# IP-Adresse
line="$(grep '^Address=' ${root}/etc/systemd/network/br0.network)"
line=${line#Address=}
ip_addr=${line%/24}
echo -e "${GREEN}Change Node IP address${RESET}"
replace "$ip_addr" "${GREEN}Change Node IP address${RESET}" "${root}/etc/systemd/network/br0.network"

#line="$(grep '^DNS=' ${root}/etc/systemd/network/br0.network)"
#dns=${line#DNS=}
#replace "$dns" "Change DNS" "${root}/etc/systemd/network/br0.network"

# -------- Show Log Summary -----------------------------------------------------
echo
echo "======================================================================"
echo " LOG SUMMARY (Warnings & Errors)"
echo "======================================================================"
if [ -s "$LOG_FILE" ]; then
  cat "$LOG_FILE"
else
  echo "No warnings or errors were recorded."
fi
echo "======================================================================"
echo
# -------- Finish/Reboot --------------------------------------------------------
if $DO_REBOOT; then
  if $DRY_RUN || confirm "Reboot now?"; then
    LOG_TS; echo "Rebooting in 5s …"
    $DRY_RUN || sleep 5
    run "sudo reboot"
  else
    LOG_TS; echo "Reboot skipped."
  fi
else
  LOG_TS; echo "Setup finished – no reboot triggered but requred!"
fi