#!/usr/bin/env bash
# ==============================================================================
# POST FRESH NODE SETUP (NatakMesh)
# Muss nach einem Reboot ausgeführt werden.
# ==============================================================================

set -Eeuo pipefail

LOG_TS() { printf '[%s] ' "$(date '+%F %T')"; }

# -------- Confirmation ---------------------------------------------------------
read -r -p "This script will enable and activate all required services for Orbis Mesh and reboot your system. Do you want to continue? [Y/N] " ans
case "$ans" in
  [Yy]*) echo "Proceeding with post-setup...";;
  *) echo "Aborted."; exit 1;;
esac

# -------- Logging (warnings & errors) -----------------------------------------
LOG_FILE="/tmp/post_fresh_node.log"
: > "$LOG_FILE"   # Logfile leeren beim Start
exec 2> >(tee -a "$LOG_FILE" >&2)   # stderr -> Konsole + Log

LOG_TS; echo "Starting post-setup tasks …"

# 1. Copy unmanaged.conf
if [ -f "${HOME}/move_me/etc/NetworkManager/conf.d/unmanaged.conf" ]; then
  LOG_TS; echo "Copying unmanaged.conf to /etc/NetworkManager/conf.d"
  sudo cp -R -f -v "${HOME}/move_me/etc/NetworkManager/conf.d/unmanaged.conf" /etc/NetworkManager/conf.d
else
  LOG_TS; echo "WARNING: unmanaged.conf not found in ${HOME}/move_me/etc/NetworkManager/conf.d"
fi



# 2. Reload systemd units
LOG_TS; echo "Reloading systemd units …"
sudo systemctl daemon-reload

# 3. Enable required services
LOG_TS; echo "Enabling systemd-networkd …"
sudo systemctl enable systemd-networkd

LOG_TS; echo "Enabling mesh-monitor.service …"
sudo systemctl enable mesh-monitor.service

LOG_TS; echo "Enabling mesh-startup.service …"
sudo systemctl enable mesh-startup.service

LOG_TS; echo "Enabling NetworkManager.service …"
sudo systemctl enable NetworkManager.service

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

# 4. Reboot (with confirmation)
read -r -p "Reboot now? [Y/N] " reboot_ans
case "$reboot_ans" in
  [Yy]*)
    LOG_TS; echo "Rebooting in 5 seconds …"
    sleep 5
    sudo reboot
    ;;
  *)
    LOG_TS; echo "Reboot skipped."
    ;;
esac
