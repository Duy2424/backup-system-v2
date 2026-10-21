"""Dien tap K6/K7/K8 (bench/dien_tap.py) chay duoc va ra dung ket luan tren du lieu nho."""
import re

import pytest

from bench import dien_tap


def _run(tmp_path, *argv):
    return dien_tap.main([*argv, "--workdir", str(tmp_path / "w"), "--csv", str(tmp_path / "dt.csv")])


def test_k8_sua_1_bit_o_3_cho_deu_bi_bat(tmp_path):
    rows = _run(tmp_path, "k8", "--size", "3MB", "--pack-mb", "1")
    assert [r["mo_ta"] for r in rows] == ["sửa 1 bit: pack - vùng dữ liệu", "sửa 1 bit: pack - bảng index",
                                          "sửa 1 bit: snapshot"]
    for r in rows:
        assert "check_nhanh=BAT" in r["ghi_chu"] and "check_day_du=BAT" in r["ghi_chu"]
        assert "khoi_phuc=TU CHOI" in r["ghi_chu"]
        assert "sau_khi_tra_byte=sach" in r["ghi_chu"]
    assert "khoi_phuc_1_file=TU CHOI" in rows[0]["ghi_chu"]       # GCM cua tung mau bat duoc khi doc Range
    assert (tmp_path / "dt.csv").exists() and not any((tmp_path / "w").iterdir())


def test_k6_dut_mang_chay_lai_khong_gui_trung(tmp_path):
    rows = _run(tmp_path, "k6", "--size", "6MB", "--pack-mb", "1", "--retries", "0", "--backoff", "0")
    doi_chung, lan1, lan2, kiem = rows
    assert lan1["mo_ta"] == "lần 1: đứt mạng" and "snapshot_tren_kho=0" in lan1["ghi_chu"]
    assert 0 < lan1["byte_gui"] < doi_chung["byte_gui"]
    assert "mau_gui_2_lan=0" in lan2["ghi_chu"]
    assert lan1["byte_gui"] + lan2["byte_gui"] <= doi_chung["byte_gui"] * 1.02
    assert "digest=khop" in kiem["ghi_chu"]


def test_k7_toc_do_gui_khong_vuot_gioi_han(tmp_path):
    rows = _run(tmp_path, "k7", "--size", "4MB", "--pack-mb", "1", "--limit", "1MB/s")
    assert [r["lan_chay"] for r in rows] == [1, 2]
    lech = float(re.search(r"lech=([+-][0-9.]+)%", rows[1]["ghi_chu"]).group(1))
    assert lech <= 5.0                        # trung binh ca lan chay khong vuot muc dat
    assert "khong_gioi_han" in rows[0]["ghi_chu"]


def test_k5_xoa_ghi_de_deu_bi_tu_choi_du_lieu_nguyen_ven(tmp_path):
    rows = _run(tmp_path, "k5", "--size", "2MB", "--pack-mb", "1")
    *attacks, final = rows
    assert len(attacks) == 11
    for r in attacks:
        assert "ket_qua=TU CHOI" in r["ghi_chu"] or "ket_qua=BO QUA (exists)" in r["ghi_chu"], r
    assert "chap_nhan=0 nguyen_ven=co snapshot_con=co digest=khop" in final["ghi_chu"]


def test_k5_kho_that_khong_dung_toi_config_va_key():
    real = dien_tap._attacks("a" * 64, "b" * 64, "c" * 64, real=True)
    assert all("/config" not in p and "/keys" not in p for _, p, _, _ in real)


def test_k8_khong_cho_chay_tren_kho_that(tmp_path):
    with pytest.raises(SystemExit):
        _run(tmp_path, "k8", "--repo", "https://100.64.0.1:8443")
