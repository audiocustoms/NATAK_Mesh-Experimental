#!/usr/bin/env bash
# ==============================================================================
# FRESH NODE SETUP (OrbisMesh) – safer, structured, idempotent-ish
# ------------------------------------------------------------------------------

set -Eeuo pipefail


# -------- Confirmation ---------------------------------------------------------

clear

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}┌───────────────────────────────────────────────────┐${NC}"
echo -e "${GREEN}│                                                   │${NC}"
echo -e "${GREEN}│   ___       _     _       __  __           _      │${NC}"
echo -e "${GREEN}│  / _ \ _ __| |__ (_)___  |  \/  | ___  ___| |__   │${NC}"
echo -e "${GREEN}│ | | | | '__| '_ \| / __| | |\/| |/ _ \/ __| '_ \  │${NC}"
echo -e "${GREEN}│ | |_| | |  | |_) | \__ \ | |  | |  __/\__ \ | | | │${NC}"
echo -e "${GREEN}│  \___/|_|  |_.__/|_|___/ |_|  |_|\___||___/_| |_| │${NC}"
echo -e "${GREEN}│                                                   │${NC}"
echo -e "${GREEN}└───────────────────────────────────────────────────┘${NC}"
echo ""
echo ""
echo ""
echo "This script will install 'Orbis Mesh' on your system."
echo ""
read -r -p "Do you want to continue? [y/n] " ans
case "$ans" in
  [Yy]*) echo "Proceeding with setup...";;
  *) echo "Aborted."; exit 1;;
esac

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
command -v systemctl >/dev/null 2>&1 || true

LOG_TS; echo "Starting setup …"
LOG_TS; echo "Options: reset-id=${RUN_RESET_ID}, pipx=${USE_PIPX}, reboot=${DO_REBOOT}, dry-run=${DRY_RUN}"

n_wlan=$(iw dev | grep "^[[:space:]]*Interface" | wc -l)
if [ "$n_wlan" -lt 2 ]; then
  drv=""
  if [ "$n_wlan" -eq 1 -a -e /sys/class/net/wlan0/device ]; then
    drv=$(basename $(readlink -f "/sys/class/net/wlan0/device/driver/module"))
    read mac < /sys/class/net/wlan0/address
    echo "SUBSYSTEM==\"net\", ACTION==\"add\", ATTR{address}==\"${mac}\", NAME=\"wlan1\"" | sudo tee /etc/udev/rules.d/50-wlan1.rules > /dev/null
    run "sudo rmmod $drv"
  fi
  run "sudo modprobe dummy"
  run "sudo ip link add wlan0 type dummy"
  if [ -n "$drv" ]; then
    run "sudo modprobe $drv"
  fi
fi

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
sudo DEBIAN_FRONTEND=readline apt-get install -y hostapd batctl wget curl
sudo DEBIAN_FRONTEND=readline apt-get install -y python3 python3-pip pipx
sudo DEBIAN_FRONTEND=readline apt-get install -y aircrack-ng iperf3 network-manager alfred dnsmasq python3-flask

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
else
  run "pip3 install --upgrade --break-system-packages rns"
  # fallback: extend PATH for ~/.local/bin
  run "grep -q 'HOME/.local/bin' ~/.bashrc || echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
fi

# Note: consider disabling wpa_supplicant if hostapd should run exclusively in AP mode.
# This is system-specific — intentionally NOT automated.

# -------- File copies ----------------------------------------------------------
LOG_TS; echo "Copying configuration files from ${MOVE_SRC} …"
[ -d "${MOVE_SRC}" ] || die "Source not found: ${MOVE_SRC}"

# User directories
dst="${HOME}/"
for d in mesh mesh_monitor .reticulum scripts; do
  src="${MOVE_SRC}/home/natak/${d}"
  if [ -d "$src" ]; then
    run "cp -a -v \"$src\" \"$dst\""
  else
    LOG_TS; echo "Skipping: ${src} not found."
  fi
done

# -------- Permissions ----------------------------------------------------------
LOG_TS; echo "Setting permissions on user directories …"
for d in mesh mesh_monitor .reticulum; do
  dst="${HOME}/${d}"
  if [ -d "$dst" ]; then
    run "find \"$dst\" -type d -exec chmod 0777 {} \\;"
  fi
done

# System directories
run "sudo install -d /etc/dnsmasq.d /etc/hostapd /etc/modprobe.d /etc/NetworkManager /etc/sudoers.d /etc/sysctl.d /etc/udev /etc/systemd/network /etc/systemd/system"

# Concrete copies (only if present)
for name in etc/dnsmasq.d etc/hostapd etc/modprobe.d etc/NetworkManager etc/sudoers.d etc/sysctl.d etc/udev etc/systemd/network etc/systemd/system; do
  if test -d "${MOVE_SRC}/${name}"; then
    run "sudo cp -a ${MOVE_SRC}/${name}/* /${name}/"
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

run "clear"

sudo="sudo "

replace() {
  local old="$1"
  local name="$2"
  local file="$3"
  local new clean

  echo -n "$name: [${old}]: "
  read -r new
  if [ -n "$new" ]; then
    # use | as sed delimiter so slashes in the replacement don't need escaping
    # escape literal '|' in the new value to avoid breaking the delimiter
    clean="${new//|/\\|}"
    ${sudo}sed -i "s|${old}|${clean}|" "$file"
  fi
}

root=""
line="$(grep '^ssid=' ${root}/etc/hostapd/hostapd.conf)"
ssid=${line#ssid=}
replace "$ssid" "Local SSID" "${root}/etc/hostapd/hostapd.conf"

line="$(grep '^wpa_passphrase=' ${root}/etc/hostapd/hostapd.conf)"
wpa_pass=${line#wpa_passphrase=}
replace "$wpa_pass" "Local SSID WPA password" "${root}/etc/hostapd/hostapd.conf"

line="$(grep '^Address=' ${root}/etc/systemd/network/br0.network)"
line=${line#Address=}
ip_addr=${line%/24}
replace "$ip_addr" "IP Address" "${root}/etc/systemd/network/br0.network"

line="$(grep '^DNS=' ${root}/etc/systemd/network/br0.network)"
dns=${line#DNS=}
replace "$dns" "DNS (must match IP)" "${root}/etc/systemd/network/br0.network"

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
  LOG_TS; echo "Setup finished – no reboot triggered but required!"
fi