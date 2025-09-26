****************************
*
*	NATAK Installer
*
****************************


	- 	Pi user must be named "natak"!
	- 	Copy the "move_me" folder to the "home/natak" directory.
	- 	Run the installer "bash ./move_me/fresh_node.sh".
		This will install all requirements and software, also moves all needed files to the
		correct location.
	-	After automatic reboot, edit
			/ect/hostapd/hostapd.conf
			/etc/systemd/network/br0.network
		to your requirements.

		## DOES NOT WORK YET, IGNORE SCRIPT!
	-	Run the service activator script "bash ./move_me/service_activator.sh".

		## For now do:
	-	Run "sudo cp -R -f -v ~/move_me/etc/NetworkManager/conf.d/unmanaged.conf /etc/NetworkManager/conf.d"
	-	Run "sudo systemctl enable systemd-networkd"
	-	Run "sudo systemctl enable mesh-monitor.service"
	-	Run "sudo systemctl enable mesh-startup.service"
	-	Run "sudo reboot"

