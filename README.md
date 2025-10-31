<p align="center">
  <img src="move_me/home/natak/mesh_monitor/static/OrbisMesh_Logo_green.svg" alt="OrbisMesh Logo" width="500" />
</p>

<p align="center"><em>Self-healing mesh networks — visible, understandable, resilient.</em></p>



---

## What Is a Self-Healing Mesh Network?

A **mesh network** is a web of devices where each node acts as a **sender, receiver, and router**.  
Unlike traditional networks with a central router, every node finds its own path through the network.

**Self-healing** means the network automatically reroutes traffic when a node or link fails — no manual fixes needed.

---

## Why It Matters

A self-healing mesh can operate **without Internet or cellular infrastructure**, which makes it ideal for off-grid and emergency scenarios.

### For Preppers
- Communication continues when public networks fail  
- Nodes auto-connect via Wi-Fi or radio links  
- Great for local coordination and situational awareness

### For LARPers & Reenactors
- Build in-game communication (chat, maps, sensors)  
- Fully independent of mobile networks  
- Every participant extends the mesh

### For Civil Defense & Emergency Services
- **Ad-hoc** communication when infrastructure is down  
- Link vehicles, checkpoints, drones, or command posts  
- Local, encrypted, and redundant

### For Military & Training
- **Decentralized** field comms  
- Redundant paths increase reliability  
- Less dependence on central relays or satellites

---

## Advantages & Limitations

| Advantage | Description |
| --- | --- |
| **Self-healing** | Traffic automatically routes around failures |
| **Decentralized** | No single point of failure |
| **Private & local** | Operates offline; Internet optional |
| **Flexible** | Works over Wi-Fi, radio, or Ethernet |
| **Scalable** | More nodes generally improve resilience |

**Limitations**
- Bandwidth decreases over many hops  
- Slightly higher power usage (continuous participation)  
- Harder to reason about without good visualization  
- Range depends on antennas, terrain, and placement

---

## Introducing OrbisMesh

**OrbisMesh** is a lightweight local **web UI** that turns raw mesh telemetry into a clear, interactive dashboard.  
It shows neighbors, link quality, and network health at a glance — and offers simple tools for configuration.

### Key Features
- **Live monitoring:** neighbors, signal strength, link status  
- **Configuration:** DHCP, bridge, and access point helpers  
- **Autostart & services:** persistent monitoring stack  
- **Local-only:** runs fully offline  
- **Modern design:** clean dark UI with green accents

---

## Installation

> **Requirements**
> - Debian-based OS (Debian, Ubuntu Server, Raspberry Pi OS, etc.)
> - The system **username must be `natak`**
> - The folder **`move_me`** must exist inside the `natak` home directory:
>   ```
>   /home/natak/move_me
>   ```

### Step 1 — Prepare a Fresh Node
Run this on a fresh Debian installation (as user `natak`):

```bash
sudo bash fresh-node.sh
```

This installs the core dependencies and prepares the environment  
(e.g., `batman-adv`, `alfred`, `dnsmasq`, `hostapd`, and related tools).

### Step 2 — Activate OrbisMesh
Enable and start the services:

```bash
sudo bash service-activator.sh
```

This will:
- Install and enable the required systemd units  
- Start the mesh monitoring stack  
- Enable DHCP/bridge/ALFRED helpers  
- Launch the OrbisMesh web UI

Afterwards, open:

```
http://<your-node-ip>:5000
```


---

## Philosophy

Self-healing mesh is **digital resilience**.  
OrbisMesh makes that resilience **visible, controllable, and trustworthy** — off-grid, in the field, or in training.

---

## Contributing

Contributions and ideas are welcome!  
Open an issue, start a discussion, or submit a pull request.

---


<p align="center">
  <sub>Made with 💚 by the OrbisMesh community — empowering resilient communication.</sub>
</p>
