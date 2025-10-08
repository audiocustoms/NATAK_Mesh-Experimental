#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhanced OGM Monitor (diagnostic & robust)
------------------------------------------
- Reads B.A.T.M.A.N. advanced originators via `batctl o`
- Reads Wi‑Fi peer metrics via `iw dev <iface> station dump`
- Merges by Originator MAC or Next-Hop MAC
- Writes JSON to /home/natak/mesh/ogm_monitor/node_status.json

This version adds *extra tolerant regexes* and *detailed logging* so you can
see exactly what was parsed for each Station block.

Run as root (recommended):
    sudo python3 enhanced_ogm_monitor.py

Or grant capability to iw to avoid sudo prompts:
    sudo setcap cap_net_admin+ep /usr/sbin/iw
"""

import json
import os
import re
import subprocess
import time
import glob
import fcntl, sys
import tempfile
from typing import Dict, Any, List, Optional


class EnhancedOGMMonitor:
    # --- Configuration ---
    STATUS_FILE = "/home/natak/mesh/ogm_monitor/node_status.json"
    WIFI_IFACES: List[str] = ["wlan1", "mesh0", "wlan0"]
    POLL_INTERVAL_SEC = 1
    LOG_PREFIX = "[ogm]"

    def __init__(self) -> None:
        self._lockf = open("/tmp/ogm_monitor.lock", "w")
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[ogm] another instance is running; exiting")
            sys.exit(0)
        self.local_mac = self._get_local_mac()
        print(f"{self.LOG_PREFIX} start | local_mac={self.local_mac} ifaces={self.WIFI_IFACES}")

    # ---------------------- helpers ----------------------
    @staticmethod
    def _run(cmd: List[str]) -> str:
        return subprocess.check_output(cmd, universal_newlines=True, stderr=subprocess.STDOUT)

    @staticmethod
    def _parse_bitrate_to_mbps(text: str) -> Optional[float]:
        m = re.search(r'(\d+(?:\.\d+)?)\s*MBit/s', text, re.IGNORECASE) or \
            re.search(r'(\d+(?:\.\d+)?)\s*Mb/s', text, re.IGNORECASE)
        return float(m.group(1)) if m else None

    def _get_local_mac(self) -> Optional[str]:
    # bevorzugt bat0, dann mesh/wlan
        for iface in ["bat0", "mesh0", "wlan1", "wlan0"]:
            p = f"/sys/class/net/{iface}/address"
            try:
                if os.path.exists(p):
                    mac = open(p).read().strip().lower()
                    if mac:
                        return mac
            except Exception:
                pass
        # Fallback
        try:
            out = self._run(["ip", "-o", "link", "show", "up"])
            m = re.search(r"link/(?:ether|ieee802\.11)\s+([0-9a-fA-F:]{17})", out)
            if m:
                return m.group(1).lower()
        except Exception:
            pass
        return None

    def _iw_cmd(self, iface: str) -> List[str]:
        if os.geteuid() == 0:
            return ["iw", "dev", iface, "station", "dump"]
        else:
            return ["sudo", "-n", "iw", "dev", iface, "station", "dump"]

    def _batctl_cmd(self) -> List[str]:
        if os.geteuid() == 0:
            return ["batctl", "o"]
        else:
            return ["sudo", "-n", "batctl", "o"]

    # ---------------------- collectors ----------------------
    def get_wifi_stations(self) -> Dict[str, Dict[str, Any]]:
        """
        Parse `iw dev <iface> station dump` into:
            { mac: {signal_dbm, rx_packets, rx_drop_misc, tx_packets, tx_retries, tx_failed,
                    tx_bitrate_mbps, rx_bitrate_mbps} }
        Tolerant regexes (no ^$ anchors) + detailed per-station logging.
        """
        stations: Dict[str, Dict[str, Any]] = {}

        for iface in self.WIFI_IFACES:
            try:
                out = self._run(self._iw_cmd(iface))
            except Exception as e:
                print(f"{self.LOG_PREFIX} iw error on {iface}: {e}")
                continue

            current_mac: Optional[str] = None
            block: Dict[str, Any] = {}
            saw_any = False

            for raw in out.splitlines():
                line = raw.strip()

                m_station = re.search(r"\bStation\s+([0-9A-Fa-f:]{17})\b", line)
                if m_station:
                    if current_mac is not None:
                        # log previous
                        print(f"{self.LOG_PREFIX} iw {iface} station {current_mac} parsed -> {block}")
                        if block:
                            stations[current_mac] = block
                    current_mac = m_station.group(1).lower()
                    block = {}
                    saw_any = True
                    continue

                if current_mac is None:
                    continue

                # Signal (prefer 'signal', fallback 'signal avg') – erlaube optionales [..]
                m = re.search(r"\bsignal:\s*(-?\d+(?:\.\d+)?)\s*(?:\[[^\]]+\])?\s*dBm\b", line, re.IGNORECASE)
                if m:
                    block["signal_dbm"] = float(m.group(1))
                m = re.search(r"\bsignal\s+avg:\s*(-?\d+(?:\.\d+)?)\s*(?:\[[^\]]+\])?\s*dBm\b", line, re.IGNORECASE)
                if m and "signal_dbm" not in block:
                    block["signal_dbm"] = float(m.group(1))


                # Counters
                m = re.search(r"\brx\s+packets:\s*(\d+)\b", line, re.IGNORECASE)
                if m: block["rx_packets"] = int(m.group(1))
                m = re.search(r"\brx\s+drop\s+misc:\s*(\d+)\b", line, re.IGNORECASE)
                if m: block["rx_drop_misc"] = int(m.group(1))
                m = re.search(r"\btx\s+packets:\s*(\d+)\b", line, re.IGNORECASE)
                if m: block["tx_packets"] = int(m.group(1))
                m = re.search(r"\btx\s+retries:\s*(\d+)\b", line, re.IGNORECASE)
                if m: block["tx_retries"] = int(m.group(1))
                m = re.search(r"\btx\s+failed:\s*(\d+)\b", line, re.IGNORECASE)
                if m: block["tx_failed"] = int(m.group(1))

                # Bitrates (use regex instead of startswith)
                m = re.search(r"\btx\s+bitrate:\s*(.+)$", line, re.IGNORECASE)
                if m:
                    v = self._parse_bitrate_to_mbps(m.group(1))
                    if v is not None:
                        block["tx_bitrate_mbps"] = v
                m = re.search(r"\brx\s+bitrate:\s*(.+)$", line, re.IGNORECASE)
                if m:
                    v = self._parse_bitrate_to_mbps(m.group(1))
                    if v is not None:
                        block["rx_bitrate_mbps"] = v

            if current_mac is not None:
                print(f"{self.LOG_PREFIX} iw {iface} station {current_mac} parsed -> {block}")
                if block:
                    stations[current_mac] = block

            if saw_any:
                print(f"{self.LOG_PREFIX} iw {iface}: parsed {len(stations)} station(s).")
                if stations:
                    break
            else:
                print(f"{self.LOG_PREFIX} iw {iface}: no stations.")

        return stations

    def get_batman_nodes(self) -> Dict[str, Dict[str, Any]]:
        nodes: Dict[str, Dict[str, Any]] = {}
        try:
            out = self._run(self._batctl_cmd())
        except Exception as e:
            print(f"{self.LOG_PREFIX} batctl error: {e}")
            return nodes

        for raw in out.splitlines():
            line = raw.rstrip()
            if " * " not in line:
                continue

            m_mac = re.search(r"([0-9A-Fa-f:]{17})", line)
            if not m_mac:
                continue
            mac = m_mac.group(1).lower()

            if self.local_mac and mac == self.local_mac.lower():
                continue

            m_seen = re.search(r"(\d+(?:\.\d+)?)s", line)
            last_seen = float(m_seen.group(1)) if m_seen else 0.0

            m_thr = re.search(r"\((\d+(?:\.\d+)?)", line)
            throughput = float(m_thr.group(1)) if m_thr else 0.0

            after = line.split(")")[-1] if ")" in line else ""
            m_nh = re.search(r"([0-9A-Fa-f:]{17})", after)
            nexthop = m_nh.group(1).lower() if m_nh else ""

            nodes[mac] = {"last_seen": last_seen, "throughput": throughput, "nexthop": nexthop}

        return nodes
    
    def read_alfred_hostnames(self):
        """
        Liefert { mac_lower: hostname } aus ALFRED Typ 64.
        Nur, wenn wirklich Daten ankommen.
        """
        mapping = {}

        # 1) Wenn verfügbar: alfred-json (JSON-Ausgabe)
        try:
            out = self._run(["alfred-json", "-r", "64"])
            import json as _json
            for item in _json.loads(out):
                mac = str(item.get("mac","")).lower()
                val = str(item.get("value","")).strip()
                if mac and val:
                    mapping[mac] = val
        except Exception:
            # 2) Fallback: Textausgabe von "alfred -r 64"
            try:
                cmd = ["alfred", "-r", "64"] if os.geteuid()==0 else ["sudo","-n","alfred","-r","64"]
                out = self._run(cmd)
                for line in out.splitlines():
                    m = re.search(r'\{\s*"([0-9a-f:]{17})",\s*"([^"]*)"', line, re.I)
                    if not m: 
                        continue
                    mac = m.group(1).lower()
                    raw = m.group(2)
                    name = bytes(raw, "utf-8").decode("unicode_escape").rstrip("\x00\x0a\r")
                    if name:
                        mapping[mac] = name
            except Exception as e:
                print(f"{self.LOG_PREFIX} alfred read error: {e}")

        print(f"{self.LOG_PREFIX} alfred hostnames: {len(mapping)} item(s)")
        return mapping


    # ---------------------- main logic ----------------------
    def build_status(self) -> Dict[str, Any]:
        nodes  = self.get_batman_nodes()
        hosts  = self.read_alfred_hostnames()  # <- ALFRED
        stats  = self.get_wifi_stations()
        me     = (self.local_mac or "").lower()

        for mac, info in nodes.items():
            if mac in hosts and mac != me:
                info["hostname"] = hosts[mac]
            elif info.get("nexthop") in hosts and info["nexthop"] != me:
                info["hostname"] = hosts[info["nexthop"]]

            peer = stats.get(mac) or stats.get(info.get("nexthop",""))
            if peer:
                for k in ("signal_dbm","rx_packets","rx_drop_misc","tx_packets",
                        "tx_retries","tx_failed","tx_bitrate_mbps","rx_bitrate_mbps"):
                    if k in peer: info[k] = peer[k]

        local = self.build_local_obj(hosts)
        return {"timestamp": int(time.time()), "local": local, "nodes": nodes}
    
        print(f"{self.LOG_PREFIX} alfred hostnames: {len(mapping)} item(s)")

    def build_local_obj(self, hosts_map):
        me = (self.local_mac or "").lower()
        local = {"mac": me, "alfred_ok": False}

        # Hostname NUR wenn ALFRED ihn liefert (Kontrollmechanismus)
        if me in hosts_map:
            local["hostname"] = hosts_map[me]
            local["alfred_ok"] = True

        # (optional) Power-Infos, falls implementiert:
        pinfo = self.read_power_info()
        local["battery_present"] = pinfo.get("battery_present", False)
        if pinfo.get("battery_pct") is not None:
            local["battery_pct"] = pinfo["battery_pct"]
        local["power_source"] = pinfo.get("power_source", "unknown")
        if pinfo.get("status"):
            local["status"] = pinfo["status"]

        return local

    
    def read_power_info(self):
        """
        Erkennt echte Batteriequellen über /sys/class/power_supply/*.
        Liefert:
        - battery_present: bool
        - battery_pct: 0..100 (nur wenn vorhanden)
        - power_source: 'battery' | 'external' | 'unknown'
        - status: optional (Charging / Discharging / Not charging)
        """
        info = {'battery_pct': None, 'power_source': 'unknown', 'status': None, 'battery_present': False}
        has_batt = False
        has_ext  = False

        for base in glob.glob('/sys/class/power_supply/*'):
            # type
            try:
                typ = open(os.path.join(base, 'type')).read().strip()
            except Exception:
                typ = ''
            t = typ.lower()

            # status (optional)
            try:
                st = open(os.path.join(base, 'status')).read().strip()
                if st:
                    info['status'] = st
            except Exception:
                pass

            if t == 'battery':
                has_batt = True
                # capacity (optional)
                try:
                    cap = int(open(os.path.join(base, 'capacity')).read().strip())
                    if 0 <= cap <= 100:
                        info['battery_pct'] = cap
                except Exception:
                    pass
            elif t in ('mains', 'usb', 'ac'):
                # "online" optional
                online = '1'
                p_online = os.path.join(base, 'online')
                if os.path.exists(p_online):
                    try:
                        online = open(p_online).read().strip()
                    except Exception:
                        online = '1'
                if online == '1':
                    has_ext = True

        info['battery_present'] = has_batt
        if has_batt:
            info['power_source'] = 'battery'
        elif has_ext:
            info['power_source'] = 'external'
        else:
            info['power_source'] = 'unknown'
        return info
    
    def read_battery_capacity(self):
        """Liest %-Wert aus /sys/class/power_supply/*/capacity, falls vorhanden."""
        base = "/sys/class/power_supply"
        try:
            for name in os.listdir(base):
                cap = os.path.join(base, name, "capacity")
                if os.path.exists(cap):
                    with open(cap) as f:
                        v = f.read().strip()
                    try:
                        v = int(v)
                        if 0 <= v <= 100:
                            return v
                    except: 
                        pass
        except Exception:
            pass
        return None

    def write_status(self, payload):
        try:
            dirpath = os.path.dirname(self.STATUS_FILE)
            os.makedirs(dirpath, exist_ok=True)

            # eindeutige Temp-Datei im selben Verzeichnis (wichtig fürs atomare replace)
            fd, tmppath = tempfile.mkstemp(prefix=".node_status.", suffix=".tmp", dir=dirpath)
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(payload, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmppath, self.STATUS_FILE)   # atomar
            finally:
                # falls ein Fehler auftrat und tmppath noch existiert: aufräumen
                try:
                    if os.path.exists(tmppath):
                        os.unlink(tmppath)
                except:
                    pass

            print(f"[ogm] wrote {self.STATUS_FILE} ({len(payload.get('nodes', {}))} nodes)")
        except Exception as e:
            print(f"[ogm] write error: {e}")

    def run(self) -> None:
        try:
            while True:
                payload = self.build_status()
                self.write_status(payload)
                time.sleep(self.POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            print(f"{self.LOG_PREFIX} exit")


if __name__ == "__main__":
    EnhancedOGMMonitor().run()
