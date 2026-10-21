"""Tuan 4 (A): ap cau hinh mang len may khac - ghep card, xem truoc, KHONG chay lenh that trong test."""
import subprocess

import pytest

from agent import netplan, winexec


@pytest.fixture(autouse=True)
def khong_chay_lenh_that(monkeypatch):
    def boom(*a, **k):
        raise AssertionError(f"Lenh that bi goi trong test: {a}")
    monkeypatch.setattr(subprocess, "run", boom)


def card(name, mac, ip, gw="192.168.10.1", dns=("8.8.8.8",), dhcp=False):
    v4 = {"ip": ip, "prefix": 24, "subnet_mask": "255.255.255.0", "gateway": gw, "dns": list(dns), "dhcp": dhcp}
    return {"name": name, "mac": mac, "status": "Up", "ipv4": v4, **v4}


MAY_CU = {
    "adapters": [card("Ethernet0", "00-0C-29-AA-BB-01", "192.168.10.1", gw=None),
                 card("LAN Kho", "00-0C-29-AA-BB-02", "10.0.0.5", gw="10.0.0.1")],
    "firewall": {"Domain": {"enabled": True, "inbound": "Block", "outbound": "Allow"},
                 "Private": {"enabled": True, "inbound": "Block", "outbound": "Allow"},
                 "Public": {"enabled": True, "inbound": "Block", "outbound": "Allow"}},
    "network_advanced": {"routing_table": [{"destination": "172.16.0.0", "mask": "255.255.0.0",
                                            "gateway": "10.0.0.254", "metric": "5"}],
                         "network_shares": [{"name": "KeToan", "path": "D:\\KeToan", "description": ""}]},
}
MAY_MOI = {
    "adapters": [card("Ethernet 2", "00-0C-29-AA-BB-02", "10.0.0.99", gw="10.0.0.1", dhcp=True),   # cung MAC voi "LAN Kho"
                 card("Ethernet 3", "00-50-56-11-22-33", "192.168.200.7")],
    "firewall": {"Domain": {"enabled": False, "inbound": "Block", "outbound": "Allow"},
                 "Private": {"enabled": True, "inbound": "Block", "outbound": "Allow"},
                 "Public": {"enabled": True, "inbound": "Block", "outbound": "Allow"}},
    "network_advanced": {"routing_table": [], "network_shares": []},
}


def test_ghep_theo_mac_roi_ten_roi_chi_dinh():
    m = netplan.match_adapters(MAY_CU["adapters"], MAY_MOI["adapters"])
    assert [(b["name"], c and c["name"], how) for b, c, how in m] == [
        ("Ethernet0", None, None), ("LAN Kho", "Ethernet 2", "MAC")]
    m2 = netplan.match_adapters(MAY_CU["adapters"], MAY_MOI["adapters"], {"Ethernet0": "Ethernet 3"})
    assert m2[0][1]["name"] == "Ethernet 3" and m2[0][2] == "chỉ định"


def test_ke_hoach_dung_ten_card_moi_va_khong_cham_vao_may():
    steps, warns = netplan.build_plan(MAY_CU, MAY_MOI, {"Ethernet0": "Ethernet 3"})
    kinds = [s.kind for s in steps]
    assert kinds[:2] == ["adapter", "adapter"] and "firewall" in kinds and "route" in kinds and "shares" in kinds
    eth3 = steps[0]
    assert any("192.168.200.7 -> 192.168.10.1" in c for c in eth3.changes)
    if winexec.IS_WINDOWS:
        assert any('name="Ethernet 3" static 192.168.10.1 255.255.255.0' in c for c in eth3.commands)
        assert not any("Ethernet0" in c for c in eth3.commands)               # dung ten card MOI
        lan = steps[1]
        assert any("DHCP: True -> False" in c for c in lan.changes)
        assert any("route add 172.16.0.0 mask 255.255.0.0 10.0.0.254" in c for s in steps for c in s.commands)
    assert warns == []
    text = netplan.render(steps, warns)
    assert "ghép theo chỉ định" in text and "ghép theo MAC" in text


def test_card_khong_ghep_duoc_bao_canh_bao_va_loc_thanh_phan():
    steps, warns = netplan.build_plan(MAY_CU, MAY_MOI, only=["ipv4"])
    assert {s.kind for s in steps} == {"adapter"} and len(steps) == 1
    assert warns and "Ethernet0" in warns[0] and "--map" in warns[0]


def test_gia_tri_doc_hai_bi_chan():
    xau = {"adapters": [card('X" & del C:\\*', "00-0C-29-AA-BB-02", "10.0.0.5")]}
    steps, _ = netplan.build_plan(xau, {"adapters": [card("Ethernet 2", "00-0C-29-AA-BB-02", "10.0.0.6")]})
    # ten card dung ten MOI (an toan); gia tri doc hai o IP thi bi safe_arg chan khi xem truoc
    bad = {"adapters": [card("LAN", "00-0C-29-AA-BB-02", "10.0.0.5 & shutdown /s")]}
    steps2, warns2 = netplan.build_plan(bad, {"adapters": [card("Ethernet 2", "00-0C-29-AA-BB-02", "10.0.0.6")]})
    if netplan.winexec.IS_WINDOWS:
        assert steps2 == []
        assert "Bỏ qua" in warns2[0]
    assert steps
