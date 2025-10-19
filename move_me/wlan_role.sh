# Create an array of WiFi names
names=$(/usr/sbin/iw dev | grep "^[[:space:]]*Interface" | cut -d" " -f2)
name=($names)

# Need at least 1 WiFi interface for the mesh
if [ ${#name[@]} -eq 0 ]; then
	echo "No WiFi interfaces detected, aborting"
	exit 1
fi

cfg=interface.conf
declare -a drv
declare -a mac

echo "# Board WiFi configuration" > $cfg

if [ ${#name[@]} -eq 1 ]; then
	# Only 1 WiFi: use for mesh
	echo "A single WiFi interface ${name[0]} has been detected. It will be used for the mesh."
	read -p "Enter \"n\" if you disagree to abort installation now: " ans
	case "$ans" in
		[nN]*)
			exit 1
			;;
	esac

	# Identify driver and MAC address
	drv[0]=$(basename $(readlink -f "/sys/class/net/${name[0]}/device/driver/module"))
	read mac[0] < /sys/class/net/${name[0]}/address

	idx_mesh=0
	idx_client=-1
else
	# More than 1 WiFi interfaces: ask the user
	echo "The following WiFi interfaces detected:"
	for (( i=0; i<${#name[@]}; i++ )); do
		drv[$i]=$(basename $(readlink -f "/sys/class/net/${name[$i]}/device/driver/module"))
		read mac[$i] < /sys/class/net/${name[$i]}/address
		echo "$i: ${name[$i]} MAC ${mac[$i]} driver ${drv[$i]}"
	done
	echo "Enter index between 0 and $((${#name[@]} - 1)) to be used for mesh"
	read idx_mesh
	if [ "$idx_mesh" -lt 0 -o "$idx_mesh" -ge ${#name[@]} ]; then
		echo "Invalid index \"$idx_mesh\", aborting"
		exit 1
	fi
	echo "Enter index between 0 and $((${#name[@]} - 1)) to be used for client AP"
	read idx_client
	if [ "$idx_client" -lt 0 -o "$idx_client" -ge "${#name[@]}" -o \
	     "$idx_client" -eq "$idx_mesh" ]; then
		echo "Invalid index \"$idx_client\", aborting"
		exit 1
	fi

	echo "CLIENT_IF=${name[${idx_client}]}" >> $cfg
	echo "CLIENT_DRV=${drv[${idx_client}]}" >> $cfg
	echo "CLIENT_MAC=${mac[${idx_client}]}" >> $cfg
fi

echo "MESH_IF=${name[${idx_mesh}]}" >> $cfg
echo "MESH_DRV=${drv[${idx_mesh}]}" >> $cfg
echo "MESH_MAC=${mac[${idx_mesh}]}" >> $cfg
