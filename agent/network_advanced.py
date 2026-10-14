"""
Cau hinh mang nang cao: persistent route, hosts, firewall rule, SMB share, portproxy.

Ghi nhan nam trong system_state.capture_system_state() (1 tien trinh PowerShell).
Module nay giu: bo phan tich chu cua netsh/route (du phong), cac ham KHOI PHUC
(lenh giu nguyen tu v1, them safe_arg chong chen lenh) va so sanh.
"""
import logging
import os
import re

from agent.winexec import IS_WINDOWS, run_cmd, safe_arg

log = logging.getLogger("agent.netadv")
HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


# ===================================================================== phan tich du phong

def parse_route_print(text):
    """Muc 'Persistent Routes' cua `route print -4` (ban Windows tieng Anh)."""
    routes, inside = [], False
    for line in text.splitlines():
        s = line.strip()
        if "Persistent Routes" in s:
            inside = True
            continue
        if inside:
            if s.startswith("=") and routes:
                break
            parts = s.split()
            if len(parts) >= 4 and _IPV4.match(parts[0]) and _IPV4.match(parts[1]):
                routes.append({"destination": parts[0], "mask": parts[1], "gateway": parts[2],
                               "metric": parts[3], "persistent": True})
    return routes


def parse_portproxy(text):
    """Dong du lieu cua `netsh interface portproxy show all`: 4 cot dia chi/cong."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if (len(parts) == 4 and parts[1].isdigit() and parts[3].isdigit()
                and (parts[0] == "*" or re.match(r"^[\d.:a-fA-F]+$", parts[0]))):
            out.append({"listen_address": parts[0], "listen_port": parts[1],
                        "connect_address": parts[2], "connect_port": parts[3]})
    return out


def firewall_profiles_netsh():
    """Du phong khi cmdlet firewall khong chay: doc `netsh advfirewall show allprofiles`."""
    res = {p: {"enabled": False, "inbound": "Block", "outbound": "Allow"} for p in ("Domain", "Private", "Public")}
    out, _ = run_cmd("netsh advfirewall show allprofiles")
    cur = None
    for line in out.splitlines():
        s = line.strip()
        for p in res:
            if s.startswith(f"{p} Profile"):
                cur = p
        if cur and s.lower().startswith("state"):
            res[cur]["enabled"] = s.split()[-1].upper() == "ON"
        elif cur and "firewall policy" in s.lower():
            pol = s.split()[-1].lower()
            res[cur]["inbound"] = "Allow" if "allowinbound" in pol else "Block"
            res[cur]["outbound"] = "Block" if "blockoutbound" in pol else "Allow"
    return res


def capture_network_advanced():
    """Tuong thich code cu: goi qua system_state (1 tien trinh PowerShell)."""
    from agent import system_state
    return system_state.capture_system_state(["route", "hosts", "firewall", "shares", "portproxy"]).get(
        "network_advanced", {})


# ===================================================================== khoi phuc

def restore_routing_table(routes):
    for r in routes:
        try:
            dest, mask, gw, metric = (safe_arg(r.get(k)) for k in ("destination", "mask", "gateway", "metric"))
        except ValueError as e:
            log.warning("Bo qua route: %s", e)
            continue
        if dest and mask and gw:
            run_cmd(f"route add {dest} mask {mask} {gw} metric {metric or 1} -p")
            log.info("Route %s/%s -> %s", dest, mask, gw)


def restore_hosts_file(content):
    if not content:
        log.info("Hosts trong ban backup rong, bo qua")
        return False
    if os.path.exists(HOSTS_PATH):
        try:
            with open(HOSTS_PATH, encoding="utf-8", errors="ignore") as f:
                old = f.read()
            with open(HOSTS_PATH + ".bak", "w", encoding="utf-8") as f:
                f.write(old)
        except OSError:
            pass
    with open(HOSTS_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("Hosts: ghi %d byte", len(content))
    return True


def restore_firewall_rules(rules):
    """Them lai rule (xoa rule cung ten truoc). Khong dong toi rule khac."""
    added = 0
    for r in rules:
        try:
            name = safe_arg(r.get("name", ""))
            if not name or name.startswith("@"):
                continue
            direction = "out" if "out" in str(r.get("direction", "")).lower() else "in"
            action = "block" if "block" in str(r.get("action", "")).lower() else "allow"
            protocol, localport = safe_arg(r.get("protocol", "")), safe_arg(r.get("localport", ""))
            run_cmd(f'netsh advfirewall firewall delete rule name="{name}"')
            cmd = f'netsh advfirewall firewall add rule name="{name}" dir={direction} action={action}'
            if protocol and protocol not in ("Any", "None"):
                cmd += f" protocol={protocol}"
                if localport and localport not in ("Any", "None"):
                    cmd += f" localport={localport}"
            out, rc = run_cmd(cmd)
            added += rc == 0
        except ValueError as e:
            log.warning("Bo qua rule: %s", e)
    log.info("Firewall rule: %d/%d", added, len(rules))


def restore_network_shares(shares):
    restored = 0
    for s in shares:
        try:
            name, path = safe_arg(s.get("name", "")), safe_arg(s.get("path", ""))
            if not name or not path:
                continue
            if not os.path.exists(path):
                log.warning("Bo qua share '%s': %s khong ton tai", name, path)
                continue
            run_cmd(f"net share {name} /delete /y")
            cmd = f'net share {name}="{path}"'
            desc = safe_arg(s.get("description", ""))
            if desc:
                cmd += f' /remark:"{desc}"'
            _, rc = run_cmd(cmd)
            restored += rc == 0
        except ValueError as e:
            log.warning("Bo qua share: %s", e)
    log.info("SMB share: %d/%d", restored, len(shares))


def restore_port_proxy(proxies):
    for p in proxies:
        try:
            la, lp, ca, cp = (safe_arg(p.get(k)) for k in ("listen_address", "listen_port",
                                                            "connect_address", "connect_port"))
        except ValueError as e:
            log.warning("Bo qua portproxy: %s", e)
            continue
        if lp and ca and cp:
            run_cmd(f"netsh interface portproxy add v4tov4 listenaddress={la or '0.0.0.0'} listenport={lp} "
                    f"connectaddress={ca} connectport={cp}")
            log.info("Portproxy %s:%s -> %s:%s", la, lp, ca, cp)


def restore_network_advanced(na):
    """Chi khoi phuc khoa CO trong ban backup."""
    if not na:
        return
    if not IS_WINDOWS:
        log.info("(bo qua - khong phai Windows) restore network_advanced: %s", list(na))
        return
    steps = [("routing_table", restore_routing_table), ("hosts_file", restore_hosts_file),
             ("firewall_rules", restore_firewall_rules), ("network_shares", restore_network_shares),
             ("port_proxy", restore_port_proxy)]
    for key, fn in steps:
        if key in na:
            try:
                fn(na[key])
            except Exception as e:      # noqa: BLE001
                log.error("Khoi phuc %s loi: %s", key, e)


def compare_network_advanced(b, c):
    diffs = []
    for key, label in (("routing_table", "Persistent route"), ("firewall_rules", "Firewall rule"),
                       ("port_proxy", "Portproxy")):
        if key in b and len(b[key]) != len(c.get(key, [])):
            diffs.append(f"{label}: {len(c.get(key, []))} -> {len(b[key])}")
    if "hosts_file" in b and b["hosts_file"] != c.get("hosts_file", ""):
        diffs.append("File hosts đã thay đổi")
    if "network_shares" in b:
        missing = {s.get("name") for s in b["network_shares"]} - {s.get("name") for s in c.get("network_shares", [])}
        if missing:
            diffs.append(f"Thiếu SMB share: {', '.join(sorted(missing))}")
    return diffs
