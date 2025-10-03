from flask import Flask, render_template, jsonify, request
import socket, subprocess, json, os, time, sys, platform, shutil, re
import flask 

APP_VERSION = "1.0"
ALLOWED_SERVICES = {"dnsmasq", "reticulum", "networking"}

app = Flask(__name__)

# WiFi Channel to Frequency Mapping
WIFI_CHANNELS = {
    # 2.4 GHz
    1: 2412, 2: 2417, 3: 2422, 4: 2427, 5: 2432, 6: 2437,
    7: 2442, 8: 2447, 9: 2452, 10: 2457, 11: 2462, 12: 2467, 13: 2472, 14: 2484
}

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

def read_node_status():
    try:
        with open('/home/natak/mesh/ogm_monitor/node_status.json', 'r') as f:
            data = json.load(f)
            return data.get('nodes', {})
    except Exception as e:
        print(f"Error reading node_status.json: {e}")
        return {}

def get_current_channel():
    try:
        out = subprocess.run(['iw','dev','wlan1','info'],
                             capture_output=True, text=True).stdout
        m = re.search(r'channel\s+(\d+)', out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 11

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
    """Very simple parser for /etc/dnsmasq.d/orbismesh.conf if present."""
    cfg = {'enabled': True, 'range_start':'10.20.1.100','range_end':'10.20.1.200','lease':'12h'}
    path = '/etc/dnsmasq.d/orbismesh.conf'
    if not os.path.exists(path):
        return cfg
    try:
        with open(path,'r') as f:
            txt=f.read()
        m=re.search(r'dhcp-range=\s*([\d\.]+),\s*([\d\.]+),\s*([^,\s]+)', txt)
        if m:
            cfg['range_start'], cfg['range_end'], cfg['lease'] = m.group(1), m.group(2), m.group(3)
        if 'disable-dhcp' in txt: cfg['enabled']=False
    except: pass
    return cfg

def write_dhcp_config(enabled, start, end, lease):
    path = '/etc/dnsmasq.d/orbismesh.conf'
    lines = [
        '# Managed by mesh_monitor',
        f"dhcp-range={start},{end},{lease}"
    ]
    if not enabled:
        lines.append('disable-dhcp')
    try:
        with open(path,'w') as f:
            f.write('\n'.join(lines)+'\n')
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
        'load': load, 'memory': mem, 'disk': disk, 'ipv4': ips
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
                           local_mac=get_local_mac())

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

@app.route('/api/dhcp-config', methods=['GET','POST'])
def api_dhcp_config():
    if request.method == 'GET':
        cfg = read_dhcp_config()
        cfg.update({'hostname': socket.gethostname(), 'local_mac': get_local_mac()})
        return jsonify(cfg)
    d = request.get_json(force=True) or {}
    ok,msg = write_dhcp_config(bool(d.get('enabled',True)),
                               d.get('range_start','10.20.1.100'),
                               d.get('range_end','10.20.1.200'),
                               d.get('lease','12h'))
    return jsonify(success=ok, message=msg if ok else None, error=None if ok else msg)

@app.route('/api/dhcp-leases')
def api_dhcp_leases():
    return jsonify({'leases': read_dhcp_leases()})

@app.route('/api/node-info')
def api_node_info():
    return jsonify(gather_node_info())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)

