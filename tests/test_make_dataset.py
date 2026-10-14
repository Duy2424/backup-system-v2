"""Test tuan 1: bo du lieu mau phai TAT DINH va dung duoc cho ca v1 lan v2."""
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from bench import make_dataset as md

SIZE = "3MB"


@pytest.fixture(scope="module")
def ds_a(tmp_path_factory):
    root = tmp_path_factory.mktemp("ds") / "a"
    info = md.generate(root, SIZE, seed=11)
    return root, info


def test_cung_seed_cung_hash(ds_a, tmp_path):
    root_a, info_a = ds_a
    info_b = md.generate(tmp_path / "b", SIZE, seed=11)
    assert info_a["digest"] == info_b["digest"]
    assert info_a["so_file"] == info_b["so_file"]
    # ca mtime cung giong nhau (de cache theo mtime cua v2 cho ket qua lap lai)
    mt_a = {rel: p.stat().st_mtime_ns for rel, p in md.iter_files(root_a)}
    mt_b = {rel: p.stat().st_mtime_ns for rel, p in md.iter_files(tmp_path / "b")}
    assert mt_a == mt_b


def test_khac_seed_khac_hash(ds_a, tmp_path):
    _, info_a = ds_a
    info_c = md.generate(tmp_path / "c", SIZE, seed=12)
    assert info_c["digest"] != info_a["digest"]


def test_kich_thuoc_va_thanh_phan(ds_a):
    root, info = ds_a
    target = md.parse_size(SIZE)
    assert 0.95 * target <= info["tong_byte"] <= 1.15 * target
    rels = [rel for rel, _ in md.iter_files(root)]
    big = root / md.BIG_REL
    assert big.stat().st_size >= 0.39 * target
    assert any(r.endswith(".docx") for r in rels) and any(r.endswith(".xlsx") for r in rels)
    assert any(r.endswith((".jpg", ".png", ".zip", ".mp4")) for r in rels)
    assert sum(r.startswith("cau_hinh/") for r in rels) >= 10      # nhieu file nho
    assert any(any(ord(ch) > 127 for ch in r) for r in rels)       # ten tieng Viet co dau
    for rel, p in md.iter_files(root):
        if rel.endswith((".docx", ".xlsx")):
            with zipfile.ZipFile(p) as z:
                assert z.testzip() is None


def test_mutate_tat_dinh_va_co_thay_doi(ds_a, tmp_path):
    root_a, info_a = ds_a
    x, y = tmp_path / "x", tmp_path / "y"
    shutil.copytree(root_a, x)
    shutil.copytree(root_a, y)
    st_x = md.mutate(x, 10, seed=11, round_no=1)
    st_y = md.mutate(y, 10, seed=11, round_no=1)
    assert st_x == st_y
    assert st_x["sua"] > 0 and st_x["xoa"] > 0 and st_x["them"] > 0 and st_x["vung_file_lon"] > 0
    d_x, d_y = md.dataset_digest(x), md.dataset_digest(y)
    assert d_x == d_y != info_a["digest"]

    before = {rel: p.read_bytes() for rel, p in md.iter_files(root_a)}
    after = {rel: p.read_bytes() for rel, p in md.iter_files(x)}
    changed = sum(1 for r in before if r in after and before[r] != after[r])
    assert changed == st_x["sua"] + 1                               # +1: file lon
    assert len(set(before) - set(after)) == st_x["xoa"]
    assert len(set(after) - set(before)) == st_x["them"]
    for rel in after:                                               # file doi thi mtime phai moi hon
        if rel in before and before[rel] != after[rel]:
            assert (x / rel).stat().st_mtime > (root_a / rel).stat().st_mtime

    # vong khac -> thay doi khac
    md.mutate(y, 10, seed=11, round_no=2)
    assert md.dataset_digest(y) != d_x


# Bo loc exclude cua v1 GOC (tag v1-goc: shared/config.py + shared/snapshot.py), chep nguyen logic.
# Khop CHUOI CON (vd "AC" loai moi ten co "ac"). Ban toi uu da sua, nhung bench --ref v1-goc
# van chay code goc nen du lieu mau phai tranh duoc bo loc nay.
V1_GOC_PATTERNS = [
    "__pycache__", ".git", "node_modules", "work", "storage", "Temp", "temp", "TMP", "tmp",
    "LocalLow", "INetCache", "INetCookies", "Temporary Internet Files", "CryptnetUrlCache", "PackageCache",
    "$Recycle.Bin", "$RECYCLE.BIN", "Windows.old", "MSOCache", "System Volume Information", "Cache", "CachedData",
    "Packages", "PackageCache", "LocalState", "AC", "Wer", "CrashDumps", "SquirrelTemp", "npm-cache", "pip", "pip3",
    ".vs", ".tmp", ".TMP", ".temp", "~$", "pagefile.sys", "hiberfil.sys", "swapfile.sys", "Thumbs.db", "desktop.ini",
    "backup_system.db", "agent_config.txt", ".etl", "NTUSER.DAT", "ntuser.dat", "ntuser.dat.LOG1", "ntuser.dat.LOG2",
    "UsrClass.dat", "UsrClass.dat.LOG1", "UsrClass.dat.LOG2", ".LOG1", ".LOG2", ".regtrans-ms", ".evtx",
]


def v1_goc_should_exclude(name, patterns=V1_GOC_PATTERNS):
    low = name.lower()
    for p in patterns:
        pl = p.lower()
        if low == pl or (pl.startswith(".") and low.endswith(pl)):
            return True
        if pl.startswith("~") and low.startswith(pl.lstrip("~")) and low.startswith("~"):
            return True
        if p in name or pl in low:
            return True
    return False


def test_ten_file_khong_bi_bo_loc_v1_goc_loai(ds_a):
    """Neu du lieu mau dinh bo loc cua v1 goc, v1 se bo sot file va so do v1/v2 sai."""
    assert v1_goc_should_exclude("contract.docx")          # chung minh loi cua v1 goc
    root, _ = ds_a
    names = set()
    for rel, _ in md.iter_files(root):
        names.update(rel.split("/"))
    assert sorted(n for n in names if v1_goc_should_exclude(n)) == []
    for n in ("them_v1_0001.txt", "them_v2_0003.docx") + tuple(md.PHONG_BAN):
        assert not v1_goc_should_exclude(n)


def test_khong_ghi_de_thu_muc_co_san(tmp_path):
    (tmp_path / "co_file.txt").write_text("x")
    with pytest.raises(FileExistsError):
        md.generate(tmp_path, "1MB", seed=1)
