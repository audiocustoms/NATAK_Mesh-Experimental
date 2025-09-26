#!/bin/bash

# Variables
MESH_NAME="natak_mesh"
MESH_CHANNEL=11

# Set interfaces to not be managed by NetworkManager
nmcli device set eth0 managed no
nmcli device set wlan1 managed no
nmcli device set br0 managed no

#load batman-adv
modprobe batman-adv

# Configure mesh interface
ifconfig wlan1 down
iw reg set "US"
iw dev wlan1 set type managed
iw dev wlan1 set 4addr on
iw dev wlan1 set type mesh
iw dev wlan1 set meshid $MESH_NAME
iw dev wlan1 set channel $MESH_CHANNEL
ifconfig wlan1 up

#increase wlan1 MTU to account for BATMAN-ADV overhead
sudo ip link set dev wlan1 mtu 1560

# Set fragmentation threshold for better reliability at range, test this
# shrinking packet size reduces tx time of each individual packet, less time for something
# to get corrupted. but cuts throughput due to all the additional headers
#iwconfig wlan1 frag 1024

#wpa_supplicant for encryption only
wpa_supplicant -B -i wlan1 -c /etc/wpa_supplicant/wpa_supplicant-wlan1-encrypt.conf

sleep 15

#disable stock HWMP routing to allow BATMAN-ADV to handle it
iw dev wlan1 set mesh_param mesh_fwding 0

# Further disable HWMP by setting PREQ interval to maximum and path timeout to minimum
iw dev wlan1 set mesh_param mesh_hwmp_preq_min_interval 65535
iw dev wlan1 set mesh_param mesh_hwmp_active_path_timeout 1

#BATMAN-ADV setup
sudo batctl ra BATMAN_V
sudo ip link add bat0 type batadv
sudo ip link set dev wlan1 master bat0
sudo ip link set dev bat0 up
sudo ip link set dev br0 up
sudo ip link set dev bat0 master br0

#Stop NetworkManager from controlling bat0 interface
nmcli device set bat0 managed no

# Set OGM interval to 1000ms for better adaptation to mobility
batctl it 1000

## Mesh optimizations below depend on services that dont seem to start for 60+ seconds, need to watch dmesg for IGMP querier or something to that effect and adjust this timing.
# Set hop penalty to favor stronger direct links in poor RF conditions
#batctl nc 1
# Enable distributed ARP table to reduce broadcast traffic
#batctl dat 1


systemctl restart systemd-networkd
