"""
Ap cau hinh mang tu ban sao luu len MAY KHAC (ke hoach DACN tuan 4, Nguoi A).

May moi thuong co card mang ten khac ("Ethernet0" -> "Ethernet 2") va MAC khac. Quy trinh:
  1. export : ghi nhan cau hinh may cu ra JSON (chi doc)            -> may_cu.json
  2. plan   : ghep card theo --map (chi dinh tay) > MAC > ten, liet ke KHAC BIET va DUNG cac lenh
              netsh/route se chay (che do xem truoc cua winexec - khong cham vao may)
  3. apply  : chi chay khi them --yes (can quyen Administrator)

  python -m agent.netplan export --out may_cu.json
  python -m agent.netplan plan  --state may_cu.json --map "Ethernet0=Ethernet 2"
  python -m agent.netplan apply --state may_cu.json --map "Ethernet0=Ethernet 2" --yes
"""
import argparse
import json
import sys
from dataclasses import dataclass, field

from agent import network_advanced, system_state, winexec

NET_COMPONENTS = ["ipv4", "ipv6", "firewall", "hosts", "shares", "route", "portproxy", "defender"]


def _mac(m):
    return (m or "").replace("-", "").replace(":", "").upper()


def match_adapters(backup, current, mapping=None):
    """[(card_cu, card_moi | None, cach_ghep)] - uu tien: chi dinh tay > MAC > ten."""
    mapping = mapping or {}
    by_name = {a["name"]: a for a in current}
    by_mac = {_mac(a.get("mac")): a for a in current if _mac(a.get("mac"))}
    used, out = set(), []
    for b in backup:
        c, how = None, None
        if b["name"] in mapping:
            c, how = by_name.get(mapping[b["name"]]), "chỉ định"
        elif _mac(b.get("mac")) in by_mac:
            c, how = by_mac[_mac(b.get("mac"))], "MAC"
        elif b["name"] in by_name:
            c, how = by_name[b["name"]], "tên"
        if c is not None and c["name"] in used:
            c, how = None, "trùng"
        if c is not None:
            used.add(c["name"])
        out.append((b, c, how))
    return out


@dataclass
class Step:
    kind: str
    title: str
    changes: list = field(default_factory=list)
    commands: list = field(default_factory=list)
    run: object = None          # callable thuc thi that (chi goi khi apply)


def _diff_family(fam, b, c):
    out = []
    bv, cv = b.get(fam) or {}, (c.get(fam) or {}) if c else {}
    for k, label in (("dhcp", "DHCP"), ("ip", "địa chỉ"), ("subnet_mask", "subnet mask"), ("prefix", "prefix"),
                     ("gateway", "gateway"), ("dns", "DNS")):
        if k in bv and bv.get(k) != cv.get(k):
            out.append(f"{fam.upper()} {label}: {cv.get(k)} -> {bv.get(k)}")
    return out


def _preview(fn, *args):
    with winexec.capture() as cmds:
        fn(*args)
    return [c for _, c in cmds]


def build_plan(backup_state, current_state, mapping=None, only=None):
    comps = set(only or NET_COMPONENTS)
    steps, warnings = [], []
    if comps & {"ipv4", "ipv6"}:
        cur = current_state.get("adapters", [])
        for b, c, how in match_adapters(backup_state.get("adapters", []), cur, mapping):
            if c is None:
                warnings.append(f"Card '{b['name']}' (MAC {b.get('mac')}) không ghép được với card nào trên máy này"
                                + (" (trùng card đã ghép)" if how == "trùng" else "") + " - dùng --map")
                continue
            target = {k: v for k, v in b.items() if not (k == "ipv4" and "ipv4" not in comps)
                      and not (k == "ipv6" and "ipv6" not in comps)}
            target["name"] = c["name"]
            if "ipv4" not in comps:
                for k in ("ip", "prefix", "subnet_mask", "gateway", "dns", "dhcp"):
                    target.pop(k, None)
            changes = [x for fam in ("ipv4", "ipv6") if fam in comps for x in _diff_family(fam, target, c)]
            if not changes:
                continue
            title = f"Card '{b['name']}' -> '{c['name']}' (ghép theo {how})"
            try:
                cmds = _preview(system_state.restore_network_adapter, target)
            except ValueError as e:              # gia tri doc hai/hong trong ban sao luu (safe_arg chan)
                warnings.append(f"Bỏ qua {title}: {e}")
                continue
            steps.append(Step("adapter", title, changes, cmds,
                              (lambda t=target: system_state.restore_network_adapter(t))))
    if "firewall" in comps and backup_state.get("firewall"):
        diffs = [f"{p}: bật={current_state.get('firewall', {}).get(p, {}).get('enabled')} -> {s.get('enabled')}"
                 for p, s in backup_state["firewall"].items()
                 if s != current_state.get("firewall", {}).get(p)]
        if diffs:
            fw = backup_state["firewall"]
            steps.append(Step("firewall", "Tường lửa (3 profile)", diffs,
                              _preview(system_state.restore_firewall_state, fw),
                              (lambda: system_state.restore_firewall_state(fw))))
    na_b, na_c = backup_state.get("network_advanced", {}), current_state.get("network_advanced", {})
    if "route" in comps and na_b.get("routing_table"):
        have = {(r["destination"], r["mask"], r["gateway"]) for r in na_c.get("routing_table", [])}
        add = [r for r in na_b["routing_table"] if (r["destination"], r["mask"], r["gateway"]) not in have]
        if add:
            steps.append(Step("route", f"Thêm {len(add)} persistent route",
                              [f"{r['destination']}/{r['mask']} via {r['gateway']}" for r in add],
                              _preview(network_advanced.restore_routing_table, add),
                              (lambda a=add: network_advanced.restore_routing_table(a))))
    if "hosts" in comps and na_b.get("hosts_file") and na_b["hosts_file"] != na_c.get("hosts_file"):
        steps.append(Step("hosts", "Ghi lại file hosts (bản cũ giữ ở hosts.bak)",
                          [f"{len(na_b['hosts_file'].splitlines())} dòng"], [network_advanced.HOSTS_PATH],
                          (lambda h=na_b["hosts_file"]: network_advanced.restore_hosts_file(h))))
    for key, comp, label, fn in (("network_shares", "shares", "SMB share", network_advanced.restore_network_shares),
                                 ("port_proxy", "portproxy", "portproxy", network_advanced.restore_port_proxy),
                                 ("firewall_rules", "firewall", "rule tường lửa", network_advanced.restore_firewall_rules)):
        items = na_b.get(key) or []
        if comp in comps and items:
            have = {json.dumps(x, sort_keys=True) for x in na_c.get(key, [])}
            add = [x for x in items if json.dumps(x, sort_keys=True) not in have]
            if add:
                steps.append(Step(comp, f"{label}: {len(add)} mục", [x.get("name") or str(x) for x in add[:10]],
                                  _preview(fn, add), (lambda f=fn, a=add: f(a))))
    if "defender" in comps and backup_state.get("defender", {}).get("available"):
        d = backup_state["defender"]
        if d.get("realtime_enabled") != current_state.get("defender", {}).get("realtime_enabled"):
            steps.append(Step("defender", "Windows Defender", [f"realtime -> {d.get('realtime_enabled')}"],
                              ["Set-MpPreference ..."], (lambda: system_state.restore_defender_state(d))))
    return steps, warnings


def render(steps, warnings):
    lines = []
    for i, s in enumerate(steps, 1):
        lines.append(f"[{i}] {s.title}")
        lines += [f"      {c}" for c in s.changes]
        lines += [f"      > {c}" for c in s.commands]
    lines += [f"CẢNH BÁO: {w}" for w in warnings]
    if not steps:
        lines.append("Không có gì khác biệt cần áp.")
    return "\n".join(lines)


def apply(steps, log=print):
    for i, s in enumerate(steps, 1):
        log(f"Áp [{i}] {s.title}")
        try:
            s.run()
        except Exception as e:     # noqa: BLE001 - mot buoc loi khong chan buoc khac
            log(f"  LỖI: {e}")


def main(argv=None):
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="python -m agent.netplan")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="ghi nhận cấu hình máy này ra JSON (chỉ đọc)")
    e.add_argument("--out", required=True)
    for name in ("plan", "apply"):
        p = sub.add_parser(name, help="xem trước" if name == "plan" else "áp thật (cần --yes, quyền Administrator)")
        p.add_argument("--state", required=True, help="JSON từ 'export' hoặc _meta/system_state.json của bản sao lưu")
        p.add_argument("--map", action="append", default=[], help='"Tên card cũ=Tên card mới", lặp lại được')
        p.add_argument("--only", help="chỉ các thành phần, vd ipv4,route")
        if name == "apply":
            p.add_argument("--yes", action="store_true", help="xác nhận áp thật")
    a = ap.parse_args(argv)
    if a.cmd == "export":
        st = system_state.capture_system_state()
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        print(f"Đã ghi {a.out}: {len(st.get('adapters', []))} card mạng")
        return 0
    with open(a.state, encoding="utf-8-sig") as f:
        backup = json.load(f)
    mapping = dict(m.split("=", 1) for m in a.map)
    only = a.only.split(",") if a.only else None
    steps, warnings = build_plan(backup, system_state.capture_system_state(only), mapping, only)
    print(render(steps, warnings))
    if a.cmd == "apply":
        if not a.yes:
            print("\nChưa áp. Kiểm tra kế hoạch trên rồi chạy lại với --yes.")
            return 1
        apply(steps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
