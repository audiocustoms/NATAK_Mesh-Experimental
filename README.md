# IGNORE INSTALLATION SETUP FOR NOW!
This is a working repo and subject to change and fail.
It the installer does not work properly...


# Fresh Node Setup (NatakMesh)

This script prepares a new system (e.g. Raspberry Pi / Debian-based) for use as a **NatakMesh node**.
It installs required packages, sets up networking and mesh tools, and copies configuration files into place.
Optional features allow resetting machine IDs (for cloned images) and triggering a reboot.

---

## Features

- Installs system packages: `hostapd`, `batctl`, `aircrack-ng`, `iperf3`, `ufw`, `NetworkManager`, `python3`, `pipx` (or `pip3`).
- Loads and persists the **batman-adv** kernel module.
- Installs Python tools: **Reticulum (rns)**, **Nomadnet**, **Flask**.
- Copies user and system configuration files from `~/move_me/…` into the correct locations.
- Optionally resets **machine-id** and regenerates **SSH host keys** for cloned images.
- Optional automatic reboot at the end.
- Safe, idempotent-ish design with logging, dry-run mode, and confirmation prompts.

---

## Requirements

- Debian/Ubuntu/Raspberry Pi OS (APT-based).
- Run as a normal user with `sudo` privileges.
- Source files available in `~/move_me` (structured like `/home/natak/…` and `/etc/…`).

---

## Usage

```bash
chmod +x fresh_node.sh
./fresh_node.sh [OPTIONS]
```

### Options

| Option        | Description                                                                 |
|---------------|-----------------------------------------------------------------------------|
| `--reset-id`  | Reset `/etc/machine-id` and SSH host keys (for cloned SD card images).      |
| `--no-pipx`   | Use `pip3` system-wide instead of `pipx` (not recommended).                 |
| `--do-reboot` | Reboot automatically at the end.                                            |
| `--dry-run`   | Show commands without executing them.                                       |
| `-h, --help`  | Show usage help.                                                            |

---

## Examples

- **Normal setup** (recommended):

  ```bash
  ./fresh_node.sh
  ```

- **Reset IDs on a cloned image**:

  ```bash
  ./fresh_node.sh --reset-id
  ```

- **Preview only (no changes)**:

  ```bash
  ./fresh_node.sh --dry-run
  ```

- **Full setup with reboot**:

  ```bash
  ./fresh_node.sh --do-reboot
  ```

---

## After Running

Please review and adjust configuration files as needed:

- `/etc/hostapd/hostapd.conf` → set **SSID, channel, country code**
- `/etc/systemd/network/br0.network` → set **bridge & IP configuration**
- Ensure **hostapd** and **wpa_supplicant** are not conflicting (AP mode vs client mode)

---

## Notes

- Default behavior installs Python tools with **pipx** (isolated, safer).
  Use `--no-pipx` only if pipx is unavailable or undesired.
- Do **not** use `chmod -R 777 ~` (removed for safety).
- The script is idempotent: running it again should not break the system.
