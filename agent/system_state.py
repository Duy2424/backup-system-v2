"""
Ghi nhan / khoi phuc cau hinh he thong Windows:
  card mang (IPv4/IPv6), firewall (3 profile + rule), Defender,
  persistent route, hosts, SMB share, portproxy.

Toi uu so voi v1 goc:
  - Ghi nhan bang MOT tien trinh PowerShell duy nhat (v1 goi ~8 tien trinh, moi cai
    ton 0,3-1 s khoi dong) va CHI lay thanh phan duoc chon.
  - Xuat JSON UTF-8 -> ten card/share tieng Viet khong bi loi ma.
  - Dung cmdlet (khong phu thuoc ngon ngu Windows) thay vi doc chu cua netsh/route;
    netsh chi con la phuong an du phong.
  - Port filter cua firewall rule lay 1 lan roi noi theo InstanceID (cmdlet tra ket
    qua khong theo thu tu dau vao).
Khoi phuc giu nguyen cac lenh netsh cua v1 (da kiem chung tren Server 2012), them
kiem tra dau vao de chong chen lenh.
"""
import json
import logging
import platform

from agent import network_advanced
from agent.winexec import IS_WINDOWS, run_cmd, run_ps, safe_arg

log = logging.getLogger("agent.system")
HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"

NETWORK_COMPONENTS = ["ipv4", "ipv6", "firewall", "hosts", "shares", "route", "portproxy", "defender"]


# ===================================================================== ghi nhan

_PS_CAPTURE = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
$want = @(__WANT__)
$r = [ordered]@{}
if ($want -contains 'adapters') {
  # Lay hang loat roi noi theo ifIndex (Get-NetIPConfiguration -Detailed cham gap ~15 lan)
  $ads = @{}; foreach ($n in @(Get-NetAdapter)) { $ads[[int]$n.ifIndex] = $n }
  $ifs = @{}; foreach ($i in @(Get-NetIPInterface)) { $ifs["$($i.ifIndex)-$([int]$i.AddressFamily)"] = $i }
  $dns = @{}; foreach ($d in @(Get-DnsClientServerAddress)) { $dns["$($d.InterfaceIndex)-$([int]$d.AddressFamily)"] = @($d.ServerAddresses) }
  $gws = @{}; foreach ($g in @(Get-NetRoute -DestinationPrefix '0.0.0.0/0','::/0')) {
    $k = "$($g.ifIndex)-$([int]$g.AddressFamily)"; if (-not $gws.ContainsKey($k)) { $gws[$k] = $g.NextHop } }
  $ips = @(Get-NetIPAddress | Where-Object { $ads.ContainsKey([int]$_.InterfaceIndex) })
  $list = New-Object System.Collections.ArrayList
  foreach ($idx in @($ips | ForEach-Object { [int]$_.InterfaceIndex } | Sort-Object -Unique)) {
    $na = $ads[$idx]
    $v4 = $ips | Where-Object { $_.InterfaceIndex -eq $idx -and [int]$_.AddressFamily -eq 2 } | Select-Object -First 1
    $v6 = $ips | Where-Object { $_.InterfaceIndex -eq $idx -and [int]$_.AddressFamily -eq 23 -and
                                $_.IPAddress -notlike 'fe80*' -and [string]$_.SuffixOrigin -ne 'Random' } | Select-Object -First 1
    [void]$list.Add([ordered]@{
      name = $na.Name; mac = $na.MacAddress; status = [string]$na.Status; index = $idx
      v4_ip = $v4.IPAddress; v4_prefix = $v4.PrefixLength; v4_gateway = @($gws["$idx-2"])
      v4_dns = $dns["$idx-2"]; v4_dhcp = [string]$ifs["$idx-2"].Dhcp
      v6_ip = $v6.IPAddress; v6_prefix = $v6.PrefixLength; v6_gateway = @($gws["$idx-23"])
      v6_dns = $dns["$idx-23"]; v6_dhcp = [string]$ifs["$idx-23"].Dhcp
    })
  }
  $r.adapters = $list
}
if ($want -contains 'firewall') {
  try {
    # COM FwPolicy2: khong can nap module NetSecurity (~4 s) va doc duoc ca khi khong la admin
    $fw = New-Object -ComObject HNetCfg.FwPolicy2 -ErrorAction Stop
    $r.firewall_profiles = @(foreach ($p in @(@('Domain', 1), @('Private', 2), @('Public', 4))) {
      [ordered]@{ name = $p[0]; enabled = [string]$fw.FirewallEnabled($p[1])
        inbound = $(if ($fw.DefaultInboundAction($p[1]) -eq 1) { 'Allow' } else { 'Block' })
        outbound = $(if ($fw.DefaultOutboundAction($p[1]) -eq 0) { 'Block' } else { 'Allow' }) } })
    $proto = @{ 1 = 'ICMPv4'; 6 = 'TCP'; 17 = 'UDP'; 58 = 'ICMPv6'; 256 = 'Any' }
    $r.firewall_rules = @($fw.Rules | Where-Object { $_.Enabled -and $_.Name -notlike '@*' } | Select-Object -First 100 |
      ForEach-Object {
        $pr = @(); if ($_.Profiles -band 1) { $pr += 'Domain' }; if ($_.Profiles -band 2) { $pr += 'Private' }; if ($_.Profiles -band 4) { $pr += 'Public' }
        [ordered]@{ Name = $_.Name; Direction = $(if ($_.Direction -eq 2) { 'Outbound' } else { 'Inbound' })
          Action = $(if ($_.Action -eq 1) { 'Allow' } else { 'Block' })
          Protocol = $(if ($proto.ContainsKey([int]$_.Protocol)) { $proto[[int]$_.Protocol] } else { [string]$_.Protocol })
          LocalPort = $(if ($_.LocalPorts -and $_.LocalPorts -ne '*') { $_.LocalPorts } else { 'Any' })
          RemotePort = $(if ($_.RemotePorts -and $_.RemotePorts -ne '*') { $_.RemotePorts } else { 'Any' })
          Profile = $(if ($pr.Count -eq 3 -or $pr.Count -eq 0) { 'Any' } else { $pr -join ', ' }) } })
  } catch {
    $r.firewall_profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore | ForEach-Object {
      [ordered]@{ name = [string]$_.Name; enabled = [string]$_.Enabled
                  inbound = [string]$_.DefaultInboundAction; outbound = [string]$_.DefaultOutboundAction } })
    $rules = @(Get-NetFirewallRule -Enabled True | Where-Object { $_.DisplayName -notlike '@*' } | Select-Object -First 100)
    $pf = @{}
    try { Get-NetFirewallPortFilter -All -ErrorAction Stop | ForEach-Object { $pf[$_.InstanceID] = $_ } }
    catch { foreach ($f in @($rules | Get-NetFirewallPortFilter)) { $pf[$f.InstanceID] = $f } }
    $r.firewall_rules = @($rules | ForEach-Object { $f = $pf[$_.Name]
      [ordered]@{ Name = $_.DisplayName; Direction = [string]$_.Direction; Action = [string]$_.Action
                  Protocol = [string]$f.Protocol; LocalPort = [string]$f.LocalPort
                  RemotePort = [string]$f.RemotePort; Profile = [string]$_.Profile } })
  }
}
if ($want -contains 'defender') {
  try { $p = Get-MpPreference -ErrorAction Stop
        $r.defender = [ordered]@{ realtime_enabled = -not $p.DisableRealtimeMonitoring
          behavior_enabled = -not $p.DisableBehaviorMonitoring; ioav_enabled = -not $p.DisableIOAVProtection
          available = $true } }
  catch { $r.defender = @{ available = $false } }
}
if ($want -contains 'route') {
  $r.routes = @(Get-NetRoute -AddressFamily IPv4 -PolicyStore PersistentStore | ForEach-Object {
    [ordered]@{ prefix = $_.DestinationPrefix; next_hop = $_.NextHop; metric = $_.RouteMetric } })
  $r.route_print = (route print -4 | Out-String)
}
if ($want -contains 'shares') {
  $r.shares = @(Get-SmbShare | Where-Object { $_.Name -notlike '*$' } | ForEach-Object {
    [ordered]@{ Name = $_.Name; Path = $_.Path; Description = $_.Description } })
}
if ($want -contains 'portproxy') { $r.portproxy_text = (netsh interface portproxy show all | Out-String) }
$r | ConvertTo-Json -Depth 6 -Compress
"""


def _as_list(x):
    if isinstance(x, list):
        return [v for v in x if v]
    return [x] if x else []


def prefix_to_mask(prefix):
    try:
        p = int(prefix)
        m = (0xFFFFFFFF << (32 - p)) & 0xFFFFFFFF
        return ".".join(str((m >> s) & 0xFF) for s in (24, 16, 8, 0))
    except (TypeError, ValueError):
        return "255.255.255.0"


def detect_network_mode(ip):
    """Heuristic theo dai IP cua lab VMware (giu tu v1)."""
    if not ip or ip.count(".") != 3:
        return "Unknown"
    if ip.startswith(("192.168.10.", "192.168.146.", "192.168.137.")):
        return "Host-only"
    if ip.startswith("192.168.") and ip.split(".")[2] in ("80", "100", "110", "44"):
        return "NAT"
    if ip.startswith("100."):
        return "Tailscale"
    return "Unknown"


def _adapters(raw, want_v4, want_v6):
    out = []
    for a in raw or []:
        if not a.get("v4_ip") and not a.get("v6_ip"):
            continue
        v4 = {"ip": a.get("v4_ip"), "prefix": a.get("v4_prefix"),
              "subnet_mask": prefix_to_mask(a["v4_prefix"]) if a.get("v4_prefix") is not None else None,
              "gateway": (_as_list(a.get("v4_gateway")) or [None])[0], "dns": _as_list(a.get("v4_dns")),
              "dhcp": "enabled" in str(a.get("v4_dhcp", "")).lower()}
        v6 = {"ip": a.get("v6_ip"), "prefix": a.get("v6_prefix"), "subnet_mask": None,
              "gateway": (_as_list(a.get("v6_gateway")) or [None])[0], "dns": _as_list(a.get("v6_dns")),
              "dhcp": "enabled" in str(a.get("v6_dhcp", "")).lower()}
        item = {"name": a.get("name"), "mac": a.get("mac"), "status": a.get("status"),
                "index": a.get("index"), "mode": detect_network_mode(v4["ip"])}
        if want_v4:
            item["ipv4"] = v4
            # tuong thich code restore/compare cu doc IPv4 o cap goc
            item.update({k: v4[k] for k in ("ip", "prefix", "subnet_mask", "gateway", "dns", "dhcp")})
        if want_v6:
            item["ipv6"] = v6
        out.append(item)
    return out


def _firewall_profiles(raw):
    res = {}
    for p in raw or []:
        name = p.get("name")
        if name not in ("Domain", "Private", "Public"):
            continue
        en = str(p.get("enabled", "")).lower()
        inbound = p.get("inbound") if p.get("inbound") in ("Block", "Allow") else "Block"
        outbound = p.get("outbound") if p.get("outbound") in ("Block", "Allow") else "Allow"
        res[name] = {"enabled": en in ("true", "1", "notconfigured"), "inbound": inbound, "outbound": outbound}
    return res or network_advanced.firewall_profiles_netsh()


def _routes(raw_routes, route_print):
    routes, seen = [], set()
    for r in raw_routes or []:
        dest, _, plen = str(r.get("prefix", "")).partition("/")
        item = {"destination": dest, "mask": prefix_to_mask(plen or 32), "gateway": r.get("next_hop"),
                "metric": r.get("metric", 1), "persistent": True}
        key = (item["destination"], item["mask"], item["gateway"])
        if dest and key not in seen:
            seen.add(key)
            routes.append(item)
    for item in network_advanced.parse_route_print(route_print or ""):
        key = (item["destination"], item["mask"], item["gateway"])
        if key not in seen:
            seen.add(key)
            routes.append(item)
    return routes


def _read_hosts():
    if not IS_WINDOWS:
        return ""
    try:
        with open(HOSTS_PATH, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError as e:
        log.warning("Khong doc duoc hosts: %s", e)
        return ""


def capture_system_state(components=None):
    """
    Ghi nhan cau hinh cho cac thanh phan duoc chon (None = tat ca).
    Ket qua co cung cau truc voi ban v1 goc da loc theo thanh phan
    (khoa nao khong co nghia la thanh phan do khong duoc backup).
    """
    comps = [c for c in (components or NETWORK_COMPONENTS)]
    state = {"platform": platform.platform(), "hostname": platform.node(), "components": list(comps)}
    want = set()
    if "ipv4" in comps or "ipv6" in comps:
        want.add("adapters")
    for c in ("firewall", "defender", "route", "shares", "portproxy"):
        if c in comps:
            want.add(c)

    data = {}
    if want and IS_WINDOWS:
        out, _ = run_ps(_PS_CAPTURE.replace("__WANT__", ",".join(f"'{w}'" for w in sorted(want))))
        try:
            data = json.loads(out) if out.strip() else {}
        except json.JSONDecodeError:
            log.warning("Khong doc duoc JSON tu PowerShell: %s", out[:200])

    if "adapters" in want:
        state["adapters"] = _adapters(data.get("adapters"), "ipv4" in comps, "ipv6" in comps)
    if "firewall" in comps:
        state["firewall"] = _firewall_profiles(data.get("firewall_profiles"))
    if "defender" in comps:
        state["defender"] = data.get("defender") or {"available": False}

    na = {}
    if "route" in comps:
        na["routing_table"] = _routes(data.get("routes"), data.get("route_print"))
    if "hosts" in comps:
        na["hosts_file"] = _read_hosts()
    if "firewall" in comps:
        na["firewall_rules"] = [{"name": r.get("Name", ""), "direction": r.get("Direction", ""),
                                 "action": r.get("Action", ""), "protocol": r.get("Protocol", ""),
                                 "localport": r.get("LocalPort", ""), "remoteport": r.get("RemotePort", ""),
                                 "profile": r.get("Profile", ""), "enabled": True}
                                for r in data.get("firewall_rules") or []]
    if "shares" in comps:
        na["network_shares"] = [{"name": s.get("Name", ""), "path": s.get("Path", ""),
                                 "description": s.get("Description") or ""} for s in data.get("shares") or []]
    if "portproxy" in comps:
        na["port_proxy"] = network_advanced.parse_portproxy(data.get("portproxy_text") or "")
    if na:
        state["network_advanced"] = na
    return state


# ===================================================================== khoi phuc (lenh giu tu v1)

def restore_network_adapter(a):
    if not IS_WINDOWS:
        log.info("(bo qua - khong phai Windows) restore adapter %s", a.get("name"))
        return True
    name = safe_arg(a.get("name"))
    if not name:
        return False
    ipv4 = a.get("ipv4")
    if ipv4 is None and a.get("ip") is not None:          # dinh dang cu
        ipv4 = {k: a.get(k) for k in ("ip", "prefix", "gateway", "dns", "dhcp", "subnet_mask")}
    if ipv4 and (ipv4.get("ip") or ipv4.get("dhcp")):
        _restore_ipv4(name, ipv4)
    ipv6 = a.get("ipv6")
    if ipv6 and (ipv6.get("ip") or ipv6.get("dhcp")):
        _restore_ipv6(name, ipv6)
    return True


def _restore_ipv4(name, v4):
    if v4.get("dhcp"):
        run_cmd(f'netsh interface ipv4 set address name="{name}" source=dhcp')
        run_cmd(f'netsh interface ipv4 set dnsservers name="{name}" source=dhcp')
        log.info("%s IPv4 -> DHCP", name)
        return
    ip = safe_arg(v4.get("ip"))
    if not ip:
        return
    mask = safe_arg(v4.get("subnet_mask") or prefix_to_mask(v4.get("prefix") or 24))
    cmd = f'netsh interface ipv4 set address name="{name}" static {ip} {mask}'
    if v4.get("gateway"):
        cmd += f" {safe_arg(v4['gateway'])} 1"
    run_cmd(cmd)
    log.info("%s IPv4 -> %s/%s gw=%s", name, ip, mask, v4.get("gateway"))
    dns = [safe_arg(d) for d in v4.get("dns") or []]
    if dns:
        run_cmd(f'netsh interface ipv4 set dnsservers name="{name}" static {dns[0]} primary')
        for i, d in enumerate(dns[1:], 2):
            run_cmd(f'netsh interface ipv4 add dnsservers name="{name}" {d} index={i}')


def _restore_ipv6(name, v6):
    if v6.get("dhcp"):
        run_cmd(f'netsh interface ipv6 set interface "{name}" routerdiscovery=enabled')
        run_cmd(f'netsh interface ipv6 set dnsservers name="{name}" source=dhcp')
        log.info("%s IPv6 -> DHCP/autoconfig", name)
        return
    ip = safe_arg(v6.get("ip"))
    if not ip or ip.lower().startswith("fe80"):
        return
    prefix = safe_arg(v6.get("prefix") or 64)
    run_cmd(f'netsh interface ipv6 set address interface="{name}" address={ip}/{prefix}')
    if v6.get("gateway"):
        run_cmd(f'netsh interface ipv6 add route ::/0 "{name}" {safe_arg(v6["gateway"])}')
    dns = [safe_arg(d) for d in v6.get("dns") or []]
    if dns:
        run_cmd(f'netsh interface ipv6 set dnsservers name="{name}" static {dns[0]} primary')
        for i, d in enumerate(dns[1:], 2):
            run_cmd(f'netsh interface ipv6 add dnsservers name="{name}" {d} index={i}')
    log.info("%s IPv6 -> %s/%s", name, ip, prefix)


def restore_firewall_state(fw):
    if not IS_WINDOWS:
        return True
    for prof, s in fw.items():
        p = {"Domain": "domain", "Private": "private", "Public": "public"}.get(prof)
        if not p:
            continue
        run_cmd(f"netsh advfirewall set {p}profile state {'on' if s.get('enabled') else 'off'}")
        inbound = "block" if str(s.get("inbound", "Block")).lower() == "block" else "allow"
        outbound = "block" if str(s.get("outbound", "Allow")).lower() == "block" else "allow"
        run_cmd(f"netsh advfirewall set {p}profile firewallpolicy {inbound}inbound,{outbound}outbound")
        log.info("Firewall %s -> %s", prof, "on" if s.get("enabled") else "off")
    return True


def restore_defender_state(d):
    if not IS_WINDOWS or not d.get("available"):
        return True
    flag = {True: "$false", False: "$true"}
    script = (f"Set-MpPreference -DisableRealtimeMonitoring {flag[bool(d.get('realtime_enabled'))]} -ErrorAction SilentlyContinue;"
              f"Set-MpPreference -DisableBehaviorMonitoring {flag[bool(d.get('behavior_enabled'))]} -ErrorAction SilentlyContinue;"
              f"Set-MpPreference -DisableIOAVProtection {flag[bool(d.get('ioav_enabled'))]} -ErrorAction SilentlyContinue")
    run_ps(script)
    log.info("Defender -> realtime=%s", d.get("realtime_enabled"))
    return True


def restore_system_state(state):
    """Chi khoi phuc thanh phan CO trong ban backup."""
    steps = []
    if "adapters" in state:
        steps += [(f"card {a.get('name')}", restore_network_adapter, a) for a in state["adapters"]]
    if "firewall" in state:
        steps.append(("firewall", restore_firewall_state, state["firewall"]))
    if "defender" in state:
        steps.append(("defender", restore_defender_state, state["defender"]))
    for label, fn, arg in steps:
        try:
            fn(arg)
        except Exception as e:          # noqa: BLE001 - mot muc loi khong chan cac muc khac
            log.error("Khoi phuc %s loi: %s", label, e)
    if state.get("network_advanced"):
        network_advanced.restore_network_advanced(state["network_advanced"])


def compare_system_state(backup_state, current_state):
    """Danh sach khac biet (chuoi) giua luc backup va hien tai."""
    diffs = []
    cur = {a["name"]: a for a in current_state.get("adapters", [])}
    for b in backup_state.get("adapters", []):
        name = b["name"]
        c = cur.get(name)
        if not c:
            diffs.append(f"Card '{name}' không còn tồn tại")
            continue
        for fam in ("ipv4", "ipv6"):
            bv, cv = b.get(fam), c.get(fam) or {}
            if bv is None:
                continue
            for k, label in (("ip", "địa chỉ"), ("subnet_mask", "subnet mask"), ("gateway", "gateway"), ("dhcp", "DHCP")):
                if fam == "ipv6" and k == "subnet_mask":
                    continue
                if bv.get(k) != cv.get(k):
                    diffs.append(f"Card '{name}' {fam.upper()} {label}: {cv.get(k)} -> {bv.get(k)}")
    for prof, bfw in backup_state.get("firewall", {}).items():
        cfw = current_state.get("firewall", {}).get(prof, {})
        if bfw.get("enabled") != cfw.get("enabled"):
            diffs.append(f"Firewall {prof}: {cfw.get('enabled')} -> {bfw.get('enabled')}")
    if "defender" in backup_state:
        bd, cd = backup_state["defender"], current_state.get("defender", {})
        if bd.get("realtime_enabled") != cd.get("realtime_enabled"):
            diffs.append(f"Defender realtime: {cd.get('realtime_enabled')} -> {bd.get('realtime_enabled')}")
    if backup_state.get("network_advanced") and current_state.get("network_advanced"):
        diffs += network_advanced.compare_network_advanced(backup_state["network_advanced"],
                                                           current_state["network_advanced"])
    return diffs


if __name__ == "__main__":
    import sys
    import time
    t = time.perf_counter()
    st = capture_system_state(sys.argv[1:] or None)
    print(json.dumps(st, indent=2, ensure_ascii=False, default=str))
    print(f"# {time.perf_counter() - t:.2f} s", file=sys.stderr)
