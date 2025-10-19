from flask import Flask, render_template, jsonify, request
import socket, subprocess, json, os, time, sys, platform, shutil, re
import flask
from pathlib import Path
from datetime import datetime

NEIGH_ACTIVE = {"REACHABLE", "DELAY", "PROBE"}  # optional: add "STALE" with a time window

def get_reticulum_version():
    # 1) Versuch: offizielles RNS-Paket
    try:
        import RNS
        return getattr(RNS, "__version__", "unbekannt")
    except Exception:
        pass
    # 2) Versuch: alternativer Modulname "reticulum"
    try:
        import reticulum as _ret
        return getattr(_ret, "__version__", "unbekannt")
    except Exception:
        pass
    # 3) Versuch: CLI-Tools (falls installiert)
    for cmd in (["rnsd", "--version"], ["rnsh", "--version"], ["reticulum", "--version"]):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
            # nimm die erste Zeile/Version, falls mehr kommt
            return out.splitlines()[0]
        except Exception:
            pass
    return "unbekannt"

APP_VERSION = "1.0"
ALLOWED_SERVICES = {"dnsmasq", "reticulum", "networking"}
from typing import Final

app = Flask(__name__)

# WiFi Channel to Frequency Mapping
WIFI_CHANNELS = {
    # 2.4 GHz
    1: 2412, 2: 2417, 3: 2422, 4: 2427, 5: 2432, 6: 2437,
    7: 2442, 8: 2447, 9: 2452, 10: 2457, 11: 2462, 12: 2467, 13: 2472, 14: 2484
}
WPA_WLAN1_CONF = Path("/etc/wpa_supplicant/wpa_supplicant-wlan1-encrypt.conf")
BATMESH_SH     = Path("/home/natak/mesh/batmesh.sh")

# Configuration
NODE_TIMEOUT = 30  # Seconds - nodes not seen within this time will be greyed out

def get_local_mac():
    """Get local MAC from wlan1 interface"""
    try:
        result = subprocess.run(['cat', '/sys/class/net/wlan1/address'], 
                              capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except:
        return "unknown"

def _first_line(txt: str) -> str:
    return (txt or "").strip().splitlines()[0] if txt else ""

def _parse_version(s: str) -> str:
    # Versuch 1: "alfred 2024.2" => greife die Zahl mit evtl. Suffix
    m = re.search(r"\balfred\b[^0-9]*([0-9][0-9A-Za-z\.\-\+_]*)", s, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Versuch 2: allgemein: erste plausible Versionsnummer
    m = re.search(r"\b[0-9]+(?:\.[0-9A-Za-z\-\+_]+)+\b", s)
    return m.group(0) if m else ""

def _try_cmd(cmd) -> str:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=2)
        ver = _parse_version(out) or _parse_version(_first_line(out))
        return ver or _first_line(out)
    except Exception:
        return ""

def get_alfred_version() -> str:
    # Kandidaten-Pfade (PATH + typische Orte)
    candidates = [shutil.which("alfred"), "/usr/sbin/alfred", "/usr/bin/alfred", "/sbin/alfred", "/bin/alfred"]
    candidates = [p for p in candidates if p]

    # Typische Versions-Flags ausprobieren
    flags = [["-v"], ["-V"], ["--version"], ["-h"]]

    for exe in candidates:
        for fl in flags:
            ver = _try_cmd([exe, *fl])
            if ver:
                return ver

    # Falls Binary nicht erreichbar: versuche Paketmanager
    for cmd in (
        ["dpkg-query", "-W", "-f=${Version}\n", "alfred"],                        # Debian/Ubuntu
        ["apk", "info", "-v", "alfred"],                                          # Alpine
        ["opkg", "info", "alfred"],                                               # OpenWrt
        ["pacman", "-Qi", "alfred"],                                              # Arch
        ["rpm", "-q", "alfred", "--qf", "%{VERSION}\n"],                          # RHEL/Fedora
    ):
        ver = _try_cmd(cmd)
        if ver:
            v = _parse_version(ver) or _first_line(ver)
            if v:
                return v

    return "unbekannt"

def get_batman_version():
    try:
        out = subprocess.check_output(["batctl", "-v"], stderr=subprocess.STDOUT).decode()
        # Beispielausgabe: "batctl 2023.4 [batman-adv: 2023.4]"
        for part in out.split():
            if part.startswith("batman-adv:"):
                return part.split(":")[1].strip("[] ")
        return out.strip()
    except Exception:
        return "unbekannt"

def read_node_status():
    try:
        with open('/home/natak/mesh/ogm_monitor/node_status.json', 'r') as f:
            data = json.load(f)
            return data.get('nodes', {})
    except Exception as e:
        print(f"Error reading node_status.json: {e}")
        return {}

def get_current_channel():
    """Read current channel from batmesh.sh"""
    try:
        with open('/home/natak/mesh/batmesh.sh', 'r') as f:
            for line in f:
                if line.startswith('MESH_CHANNEL='):
                    return int(line.split('=')[1].strip())
    except:
        return 11  # default

def update_batmesh_channel(new_channel):
    """Update channel in batmesh.sh using sed"""
    cmd = f'sed -i "s/^MESH_CHANNEL=.*/MESH_CHANNEL={new_channel}/" /home/natak/mesh/batmesh.sh'
    return subprocess.run(cmd, shell=True, capture_output=True)

def update_wpa_supplicant_frequency(new_frequency):
    """Update frequency in wpa_supplicant config using sed"""
    cmd = f'sed -i "s/frequency=.*/frequency={new_frequency}/" /etc/wpa_supplicant/wpa_supplicant-wlan1-encrypt.conf'
    return subprocess.run(cmd, shell=True, capture_output=True)

def reboot_system():
    """Reboot the system to apply changes"""
    return subprocess.run(['sudo', 'reboot'], capture_output=True)

def get_current_ip():
    """Read current IP from br0.network"""
    try:
        with open('/etc/systemd/network/br0.network', 'r') as f:
            for line in f:
                if line.startswith('Address='):
                    # Extract IP without subnet mask
                    return line.split('=')[1].strip().split('/')[0]
    except:
        return "10.20.1.2"  # default

def update_br0_ip(new_ip):
    """Update IP in br0.network using sed"""
    cmd = f'sed -i "s/^Address=.*/Address={new_ip}\/24/" /etc/systemd/network/br0.network'
    return subprocess.run(cmd, shell=True, capture_output=True)

def read_peer_discovery():
    """
    Falls du Peer-Infos irgendwo speicherst, hier auslesen.
    Bis dahin liefern wir ein leeres Dict, damit /api/node-status existiert.
    """
    try:
        # Beispiel: aus Datei lesen – bei Bedarf anpassen
        # with open('/home/natak/mesh/ogm_monitor/peers.json','r') as f:
        #     return json.load(f)
        return {}
    except Exception:
        return {}

def read_packet_logs():
    """
    Liefert Packet-Logs für /packet-logs + /api/packet-logs.
    Passe Pfad/Quelle an deine Umgebung an. Fallback = leere Liste.
    """
    try:
        # Beispiel: JSON-Datei mit Logeinträgen [{time, type, message}, …]
        # with open('/home/natak/mesh/reticulum/packet_logs.json','r') as f:
        #     return json.load(f)
        return []
    except Exception:
        return []

def get_timezone():
    try:
        with open('/etc/timezone','r') as f: return f.read().strip()
    except: return "UTC"

def set_timezone(tz):
    return subprocess.run(['sudo','timedatectl','set-timezone',tz], capture_output=True, text=True)

def change_hostname(newname):
    return subprocess.run(['sudo','hostnamectl','set-hostname', newname], capture_output=True, text=True)

def restart_service(service):
    if service not in ALLOWED_SERVICES:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr='Service not allowed')
    return subprocess.run(['sudo','systemctl','restart',service], capture_output=True, text=True)

def read_dhcp_config():
    """
    Parser für /etc/dnsmasq/mesh-br0.conf.
    Erwartet z.B.:
      interface=br0
      dhcp-range=192.168.200.100,192.168.200.199,255.255.255.0,12h
      disable-dhcp  (optional)
    """
    cfg = {
        'enabled': True,
        'range_start': '192.168.200.100',
        'range_end':   '192.168.200.199',
        'netmask':     '255.255.255.0',
        'lease':       '12h'
    }
    path = '/etc/dnsmasq/mesh-br0.conf'
    if not os.path.exists(path):
        return cfg
    try:
        with open(path, 'r') as f:
            txt = f.read()
        # 4-teilige dhcp-range (start,end,netmask,lease)
        m = re.search(
            r'^\s*dhcp-range\s*=\s*([\d\.]+)\s*,\s*([\d\.]+)\s*,\s*([\d\.]+)\s*,\s*([^,\s#]+)',
            txt, flags=re.M
        )
        if m:
            cfg['range_start'], cfg['range_end'], cfg['netmask'], cfg['lease'] = m.groups()
        if re.search(r'^\s*disable-dhcp\b', txt, flags=re.M):
            cfg['enabled'] = False
    except Exception:
        pass
    return cfg


def write_dhcp_config(enabled, start, end, lease, netmask='255.255.255.0'):
    path = '/etc/dnsmasq/mesh-br0.conf'
    existing = []
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                existing = f.read().splitlines()
    except Exception:
        existing = []

    kept = []
    for ln in existing:
        if re.match(r'^\s*dhcp-range\s*=', ln): 
            continue
        if re.match(r'^\s*disable-dhcp\b', ln): 
            continue
        kept.append(ln)

    kept.append(f"dhcp-range={start},{end},{netmask},{lease}")
    if not enabled:
        kept.append("disable-dhcp")

    try:
        with open(path, 'w') as f:
            f.write('\n'.join(kept).rstrip() + '\n')
        return True, "DHCP Konfiguration geschrieben"
    except Exception as e:
        return False, f"Fehler: {e}"


def read_dhcp_leases():
    leases=[]
    try:
        with open('/var/lib/misc/dnsmasq.leases','r') as f:
            for line in f:
                parts=line.strip().split()
                # ts, mac, ip, hostname, clientid?
                if len(parts)>=4:
                    leases.append({
                        'expires': parts[0],
                        'mac': parts[1],
                        'ip': parts[2],
                        'hostname': parts[3] if parts[3] != '*' else ''
                    })
    except: pass
    return leases

def gather_node_info():
    # OS/Kernal
    kernel = platform.release()
    try:
        os_pretty = subprocess.run(['bash','-lc','. /etc/os-release && echo $PRETTY_NAME'],
                                   capture_output=True, text=True)
        os_name = os_pretty.stdout.strip() or platform.platform()
    except:
        os_name = platform.platform()
    # uptime
    try:
        up = subprocess.run(['uptime','-p'], capture_output=True, text=True).stdout.strip()
    except:
        up = ''
    # load
    try:
        la = os.getloadavg()
        load = f"{la[0]:.2f}, {la[1]:.2f}, {la[2]:.2f}"
    except:
        load = ''
    # memory
    try:
        meminfo = {}
        with open('/proc/meminfo') as f:
            for line in f:
                k,v = line.split(':',1)
                meminfo[k]=v.strip()
        mem = f"{meminfo.get('MemAvailable','?')} free / {meminfo.get('MemTotal','?')} total"
    except:
        mem = ''
    # disk
    try:
        du = shutil.disk_usage('/')
        disk = f"{du.free//(1024**3)}G free / {du.total//(1024**3)}G total"
    except:
        disk = ''
    # ipv4
    try:
        out = subprocess.run(['ip','-o','-4','addr','show'], capture_output=True, text=True).stdout
        ips = [ln.split()[3].split('/')[0] for ln in out.strip().splitlines()]
    except:
        ips = []
    return {
        'hostname': socket.gethostname(),
        'local_mac': get_local_mac(),
        'os': os_name, 'kernel': kernel, 'uptime': up,
        'load': load, 'memory': mem, 'disk': disk, 'ipv4': ips,
        'app_version': APP_VERSION,
        'flask_version': flask.__version__,
        'python_version': sys.version.split()[0],
        'reticulum_version': get_reticulum_version(),
        'batman_version': get_batman_version(),
        'alfred_version': get_alfred_version(),
    }

def read_full_status():
    try:
        with open('/home/natak/mesh/ogm_monitor/node_status.json','r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading node_status.json: {e}")
        return {"timestamp": 0, "nodes": {}}
    
def _svc_state(name: str) -> str:
    """
    Liefert 'ok' wenn Service aktiv ist, sonst 'bad'.
    Versucht sowohl 'name' als auch 'name.service'.
    """
    candidates = [name, f"{name}.service"]
    for n in candidates:
        try:
            p = subprocess.run(
                ["systemctl", "is-active", n],
                capture_output=True, text=True, timeout=1.5
            )
            state = (p.stdout or '').strip()
            if state == "active":
                return "ok"
        except Exception:
            pass
    return "bad"

def get_current_ssid():
    try:
        with open(WPA_WLAN1_CONF, "r") as f:
            for ln in f:
                ln = ln.strip()
                if ln.lower().startswith("ssid="):
                    return ln.split("=",1)[1].strip().strip('"').strip("'")
    except:
        return ""

def update_wpa_ssid(new_ssid):
    # analog zu update_wpa_supplicant_frequency: sed + minimal escaping
    ssid_escaped = str(new_ssid).replace('"','\\"')
    cmd = f'sed -i \'s/^ssid=.*/ssid="{ssid_escaped}"/\' {WPA_WLAN1_CONF}'
    return subprocess.run(cmd, shell=True, capture_output=True)

def update_wpa_psk(new_psk):
    psk_escaped = str(new_psk).replace('"','\\"')
    cmd = f'sed -i \'s/^psk=.*/psk="{psk_escaped}"/\' {WPA_WLAN1_CONF}'
    return subprocess.run(cmd, shell=True, capture_output=True)

def _safe_read(p, default='-'):
    try:
        return open(p).read().strip()
    except Exception:
        return default

def _iface_state(iface):
    return _safe_read(f'/sys/class/net/{iface}/operstate')

def _bridge_members_br0():
    out = subprocess.getoutput("bridge link show | awk '/master br0/ {print $2}'")
    return [x for x in out.split() if x]

def _bat_members():
    out = subprocess.getoutput("batctl if | awk '{print $1}'")
    return [x for x in out.split() if x]

def _neigh_active_macs(dev="br0"):
    out = subprocess.getoutput(f"ip neigh show dev {dev}")
    macs = set()
    for line in out.splitlines():
        # Beispiele: 192.168.1.23 dev br0 lladdr 12:34:56:78:9a:bc REACHABLE
        m = re.search(r"lladdr\s+([0-9a-f:]{17})\s+([A-Z]+)", line, re.I)
        if m:
            mac, state = m.group(1).lower(), m.group(2).upper()
            if state in NEIGH_ACTIVE:
                macs.add(mac)
    return macs

def _wifi_assoc_macs(iface="wlan0"):
    out = subprocess.getoutput(f"iw dev {iface} station dump")
    return set(m.lower() for m in re.findall(r"Station\s+([0-9a-f:]{17})", out, re.I))



### Sites Routes

@app.route('/')
def mesh_status_page():
    """Startseite: Mesh Status (index.html)"""
    return render_template(
        'index.html',
        hostname=socket.gethostname(),
        node_status=read_node_status(),
        peer_discovery=read_peer_discovery()
    )  # index.html Vorlage: :contentReference[oaicite:8]{index=8}

@app.route('/connections')
def connections_page():
    """Connections-Seite (ehemalige Startseite)"""
    return render_template(
        'connections.html',
        hostname=socket.gethostname(),
        local_mac=get_local_mac(),
        node_status=read_node_status(),
        node_timeout=NODE_TIMEOUT
    )  # Vorlage/Logik: :contentReference[oaicite:9]{index=9}

@app.route('/mesh-config')
def mesh_config_page():
    """Mesh-Config (statt /management & management.html -> nutzt mesh-config.html)"""
    current_channel = get_current_channel()
    current_frequency = WIFI_CHANNELS.get(current_channel, 2462)
    current_ip = get_current_ip()
    return render_template(
        'mesh-config.html',
        hostname=socket.gethostname(),
        local_mac=get_local_mac(),
        current_channel=current_channel,
        current_frequency=current_frequency,
        current_ip=current_ip,
        available_channels=list(WIFI_CHANNELS.keys())
    )  # Werte wie vorher, aber mit richtiger Vorlage: :contentReference[oaicite:10]{index=10}

@app.route('/packet-logs')
def packet_logs_page():
    """Packet-Logs Seite"""
    return render_template(
        'packet_logs.html',
        hostname=socket.gethostname(),
        logs=read_packet_logs()
    )  # Vorlage: :contentReference[oaicite:11]{index=11}

@app.route('/node-config')
def node_config_page():
    return render_template('node-config.html',
                           hostname=socket.gethostname(),
                           local_mac=get_local_mac())

@app.route('/dhcp-config')
def dhcp_config_page():
    return render_template('dhcp-config.html',
                           hostname=socket.gethostname(),
                           local_mac=get_local_mac())

@app.route('/node-info')
def node_info_page():
    return render_template('node-info.html',
                           hostname=socket.gethostname(),
                           local_mac=get_local_mac(),
                           app_version=APP_VERSION,
                           flask_version=flask.__version__,
                           python_version=sys.version.split()[0])

@app.route('/about')
def about_page():
    return render_template('about.html',
                           hostname=socket.gethostname(),
                           local_mac=get_local_mac(),
                           app_version=APP_VERSION,
                           flask_version=flask.__version__,
                           python_version=sys.version.split()[0])



### API Endpoints

@app.route('/api/wifi')
def api_wifi():
    # ganze JSON inkl. 'local' lesen
    try:
        with open('/home/natak/mesh/ogm_monitor/node_status.json','r') as f:
            filedata = json.load(f)
    except Exception:
        filedata = {}

    nodes = filedata.get('nodes', {})
    local = filedata.get('local', {'mac': get_local_mac()})

    health = {
        'ogm-monitor': _svc_state('ogm-monitor'),
        'alfred': _svc_state('alfred'),
        'mesh-monitor': _svc_state('mesh-monitor'),
    }

    return jsonify({
        'hostname': socket.gethostname(),
        'local_mac': get_local_mac(),
        'node_status': nodes,
        'local': local,
        'node_timeout': NODE_TIMEOUT,
        'health': health,               # <— NEU
    })


@app.route('/api/mesh-config', methods=['GET'])
def get_mesh_config():
    """Get current mesh configuration"""
    current_channel = get_current_channel()
    current_frequency = WIFI_CHANNELS.get(current_channel, 2462)
    
    return jsonify({
        'current_channel': current_channel,
        'current_frequency': current_frequency,
        'available_channels': list(WIFI_CHANNELS.keys())
    })

@app.route('/api/node-ip', methods=['GET'])
def get_node_ip():
    """Get current node IP configuration"""
    current_ip = get_current_ip()
    
    return jsonify({
        'current_ip': current_ip
    })

@app.route('/api/reboot', methods=['POST'])
def reboot_node():
    """Reboot the node"""
    try:
        reboot_result = reboot_system()
        
        if reboot_result.returncode != 0:
            return jsonify({'error': 'Failed to reboot system'}), 500
            
        return jsonify({
            'success': True,
            'message': 'System is rebooting...'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/node-ip', methods=['POST'])
def set_node_ip():
    """Change node IP address"""
    try:
        data = request.get_json()
        new_ip = data.get('ip')
        
        # Basic IP validation
        ip_parts = new_ip.split('.')
        if len(ip_parts) != 4:
            return jsonify({'error': 'Invalid IP format'}), 400
            
        for part in ip_parts:
            try:
                num = int(part)
                if num < 0 or num > 255:
                    return jsonify({'error': 'Invalid IP format'}), 400
            except ValueError:
                return jsonify({'error': 'Invalid IP format'}), 400
        
        # Update IP in br0.network
        result = update_br0_ip(new_ip)
        
        if result.returncode != 0:
            return jsonify({'error': 'Failed to update IP address'}), 500
            
        return jsonify({
            'success': True,
            'ip': new_ip,
            'message': 'IP address updated successfully.'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/mesh-config', methods=['POST'])
def set_mesh_config():
    """Change mesh channel"""
    try:
        data = request.get_json()
        new_channel = int(data.get('channel'))
        
        # Validate channel
        if new_channel not in WIFI_CHANNELS:
            return jsonify({'error': 'Invalid channel'}), 400
            
        new_frequency = WIFI_CHANNELS[new_channel]
        
        # Update both config files
        batmesh_result = update_batmesh_channel(new_channel)
        wpa_result = update_wpa_supplicant_frequency(new_frequency)
        
        if batmesh_result.returncode != 0 or wpa_result.returncode != 0:
            return jsonify({'error': 'Failed to update configuration'}), 500
            
        return jsonify({
            'success': True,
            'channel': new_channel,
            'frequency': new_frequency,
            'message': 'Channel changed successfully. Node must be rebooted to apply changes.'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/node-status')
def api_node_status():
    """
    Für index.html (Mesh Status) – liefert Node- und Peer-Infos.
    """
    return jsonify({
        'hostname': socket.gethostname(),
        'node_status': read_node_status(),
        'peer_discovery': read_peer_discovery()
    })

@app.route('/api/packet-logs')
def api_packet_logs():
    """Packet-Logs als JSON für packet_logs.html"""
    return jsonify({
        'hostname': socket.gethostname(),
        'logs': read_packet_logs()
    })

@app.route('/api/node-config', methods=['GET','POST'])
def api_node_config():
    if request.method == 'GET':
        return jsonify({
            'hostname': socket.gethostname(),
            'local_mac': get_local_mac(),
            'timezone': get_timezone()
        })
    data = request.get_json(force=True) or {}
    if 'hostname' in data:
        proc = change_hostname(data['hostname'])
        if proc.returncode == 0:
            return jsonify(success=True, message='Hostname aktualisiert. Reboot empfohlen.')
        return jsonify(success=False, error=proc.stderr or 'Hostname konnte nicht gesetzt werden')
    if 'timezone' in data:
        proc = set_timezone(data['timezone'])
        if proc.returncode == 0:
            return jsonify(success=True, message='Zeitzone aktualisiert.')
        return jsonify(success=False, error=proc.stderr or 'Zeitzone konnte nicht gesetzt werden')
    return jsonify(success=False, error='Keine gültigen Parameter')

@app.route('/api/service', methods=['POST'])
def api_service():
    svc = (request.get_json(force=True) or {}).get('service','')
    proc = restart_service(svc)
    if proc.returncode == 0:
        return jsonify(success=True, message=f'{svc} neu gestartet')
    return jsonify(success=False, error=proc.stderr or 'Fehler')

@app.route('/api/dhcp-config', methods=['GET', 'POST'])
def api_dhcp_config():
    if request.method == 'GET':
        cfg = read_dhcp_config()
        cfg.update({'hostname': socket.gethostname(), 'local_mac': get_local_mac()})
        return jsonify(cfg)

    d = request.get_json(force=True) or {}
    ok, msg = write_dhcp_config(
        bool(d.get('enabled', True)),
        d.get('range_start', '192.168.200.100'),
        d.get('range_end',   '192.168.200.199'),
        d.get('lease',       '12h'),
        d.get('netmask',     '255.255.255.0')
    )
    return jsonify(success=ok, message=msg if ok else None, error=None if ok else msg)


@app.route('/api/dhcp-leases')
def api_dhcp_leases():
    leases = read_dhcp_leases()
    now = int(datetime.now().timestamp())

    # Gültige Leases (nicht abgelaufen)
    lease_macs = {l['mac'].lower() for l in leases
                  if str(l.get('expires','')).isdigit() and int(l['expires']) > now}

    # Aktive MACs laut System
    active_neigh = _neigh_active_macs("br0")
    active_wifi  = _wifi_assoc_macs("wlan0")

    # Schnittmenge = wirklich aktiv
    active_macs = lease_macs & (active_neigh | active_wifi)
    active_leases = []
    for l in leases:
        mac = l["mac"].lower()
        if mac in active_macs:
            if mac in active_wifi:
                l["adapter"] = "wlan"
            elif mac in active_neigh:
                l["adapter"] = "ethernet"
            else:
                l["adapter"] = "?"
            active_leases.append(l)

    return jsonify({
        "leases": leases,                # alle
        "active_leases": active_leases,  # nur aktive
        "active_clients": len(active_macs),
        "hostname": socket.gethostname(),
        "local_mac": get_local_mac(),
    })


@app.route('/api/node-info')
def api_node_info():
    return jsonify(gather_node_info())

@app.route('/api/wifi-ssid', methods=['GET'])
def api_wifi_ssid_get():
    return jsonify({'ssid': get_current_ssid()})

@app.route('/api/wifi-ssid', methods=['POST'])
def api_wifi_ssid_set():
    try:
        data = request.get_json(force=True) or {}
        ssid = (data.get('ssid') or '').strip()
        if not ssid:
            return jsonify({'error':'missing ssid'}), 400
        r = update_wpa_ssid(ssid)
        if r.returncode != 0:
            return jsonify({'error':'failed to set ssid', 'stderr': (r.stderr or b'').decode("utf-8","ignore")} ), 500
        return jsonify({'success': True, 'ssid': ssid})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wifi-psk', methods=['POST'])
def api_wifi_psk_set():
    try:
        data = request.get_json(force=True) or {}
        psk = data.get('psk')
        if not psk:
            return jsonify({'error':'missing psk'}), 400
        r = update_wpa_psk(psk)
        if r.returncode != 0:
            return jsonify({'error':'failed to set psk', 'stderr': (r.stderr or b'').decode("utf-8","ignore")} ), 500
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ======== Service-Reboot – nutzt vorhandene ALLOWED_SERVICES (inkl. "networking") ========
@app.route('/api/restart-service', methods=['POST'])
def api_restart_service():
    try:
        data = request.get_json(force=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error':'missing service name'}), 400
        if name not in ALLOWED_SERVICES:
            return jsonify({'error':'service not allowed'}), 403
        r = subprocess.run(['sudo','systemctl','restart', name], capture_output=True, text=True)
        if r.returncode != 0:
            return jsonify({'error':'failed to restart', 'stderr': r.stderr}), 500
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/network-status')
def api_network_status():
    # Routes
    gw_line = subprocess.getoutput("ip route show default").splitlines()
    gateway = gw_line[0].split()[2] if gw_line else '-'
    subnet  = subprocess.getoutput("ip -o addr show br0 | awk '{print $4}'").strip() or '-'

    # Bridges
    bridge = {
        'br0': {'state': _iface_state('br0'), 'members': _bridge_members_br0()},
        'bat0': {'state': _iface_state('bat0'), 'members': _bat_members()},
    }

    return jsonify({
        'routes': {'subnet': subnet, 'gateway': gateway},
        'bridge': bridge,
        'hostname': socket.gethostname(),
        'local_mac': _safe_read('/sys/class/net/br0/address', '?'),
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)

