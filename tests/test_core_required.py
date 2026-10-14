"""
Test BAT BUOC tuan 2 (ke hoach DACN):
  1. Backup roi restore toan bo bo du lieu -> SHA-256 tung file khop 100%.
  2. Sua 1 byte bat ky trong 1 pack -> restore/check PHAI bao loi xac thuc, khong tra du lieu sai.
  3. Backup 2 lan lien tiep khong doi gi -> lan 2 sinh 0 chunk moi, 0 pack moi.
  4. Sua 1 doan giua file lon -> chi vai chunk moi (in ra so chunk moi/tong).
  5. Sai mat khau khoa -> khong mo duoc kho.
  6. File rong, file 0 byte, ten tieng Viet co dau, duong dan > 260 ky tu.
Chay xem so lieu in ra:  python -m pytest -s tests/test_core_required.py
"""
import os
import random
import shutil

import pytest

from bench import make_dataset
from core.errors import IntegrityError, WrongPassword
from core.repo_local import LocalRepo
from core.repository import Repository
from tests.core_helpers import PASSWORD, dirs_of, file_hashes, new_repo, reopen, write


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    """Bo du lieu mau tat dinh (~12 MB: file lon, docx/xlsx, anh, van ban, nhieu file nho) + file dac biet."""
    root = tmp_path_factory.mktemp("data") / "du_lieu"
    make_dataset.generate(root, "12MB", seed=5)
    write(root / "dac_biet" / "rỗng.txt", b"")
    write(root / "dac_biet" / "Hợp đồng thuê nhà – bản cuối (đã ký).docx", os.urandom(70_000))
    (root / "dac_biet" / "thư mục rỗng").mkdir()
    deep = root / "dac_biet" / "/".join(f"cap_{i:02d}_ten_thu_muc_kha_dai" for i in range(10))
    write(deep / "tệp sâu.txt", "đường dẫn dài hơn 260 ký tự".encode())
    assert len(str(deep / "tệp sâu.txt")) > 260
    return root


# ---------------------------------------------------------------- 1
def test_1_backup_restore_khop_100(tmp_path, dataset):
    repo = new_repo(tmp_path / "kho")
    res = repo.backup([str(dataset)])
    st = res["stats"]
    print(f"\n[1] {st['files']} file, {st['bytes']:,} byte -> {st['chunks_new']} mau, {st['packs_new']} pack")
    out = tmp_path / "ra"
    rst = repo.restore(res["snapshot_id"], out)
    before, after = file_hashes(dataset), file_hashes(out / "du_lieu")
    assert after == before and len(after) == st["files"]
    assert dirs_of(out / "du_lieu") == dirs_of(dataset)                 # ca thu muc rong
    assert rst["files"] == st["files"]
    assert reopen(tmp_path / "kho").check()["errors"] == []


# ---------------------------------------------------------------- 2
@pytest.mark.parametrize("vi_tri", ["dau", "giua", "index", "cuoi"])
def test_2_sua_1_byte_trong_pack_bi_phat_hien(tmp_path, dataset, vi_tri):
    src = tmp_path / "kho"
    repo = new_repo(src, pack_target=2 * 1024 * 1024)                  # nhieu pack nho
    sid = repo.backup([str(dataset)])["snapshot_id"]
    pid = LocalRepo(src).list_packs()[1]
    p = src / "packs" / pid[:2] / pid
    raw = bytearray(p.read_bytes())
    pos = {"dau": 2, "giua": len(raw) // 2, "index": len(raw) - 16 - 200, "cuoi": len(raw) - 1}[vi_tri]
    raw[pos] ^= random.Random(pos).randrange(1, 256)
    os.chmod(p, 0o600)
    p.write_bytes(bytes(raw))

    r = reopen(src)
    rep = r.check()
    assert any(pid[:12] in e for e in rep["errors"]), rep            # check bao loi dung pack
    out = tmp_path / "ra"
    with pytest.raises(IntegrityError):
        r.restore(sid, out)
    # khong tra du lieu sai: file nao da duoc ghi ra thi phai dung y nhu goc, khong de lai file do dang
    good = file_hashes(dataset)
    got = file_hashes(out / "du_lieu") if (out / "du_lieu").exists() else {}
    assert all(good[k] == v for k, v in got.items())
    assert not any(k.endswith(".bks-part") for k in got)


# ---------------------------------------------------------------- 3
def test_3_backup_lai_khong_doi_gi_khong_sinh_mau_moi(tmp_path, dataset):
    repo = new_repo(tmp_path / "kho")
    repo.backup([str(dataset)])
    s2 = repo.backup([str(dataset)])["stats"]
    print(f"\n[3] lan 2: mau moi {s2['chunks_new']}, pack moi {s2['packs_new']}, "
          f"doc lai {s2['files_read']} file, bo qua {s2['files_cached']} file khong doi")
    assert (s2["chunks_new"], s2["packs_new"], s2["files_read"]) == (0, 0, 0)
    s3 = repo.backup([str(dataset)], parent=None)["stats"]             # ep doc lai het: van khu trung
    assert (s3["chunks_new"], s3["packs_new"]) == (0, 0) and s3["files_read"] == s3["files"]


# ---------------------------------------------------------------- 4
@pytest.mark.parametrize("kieu", ["ghi_de", "chen"])
def test_4_sua_giua_file_lon_chi_vai_mau_moi(tmp_path, kieu):
    src = tmp_path / "src"
    big = src / "csdl.mdf"
    data = random.Random(4).randbytes(48 * 1024 * 1024)
    write(big, data)
    repo = new_repo(tmp_path / "kho")
    s1 = repo.backup([str(src)])["stats"]
    mid = len(data) // 2
    if kieu == "ghi_de":
        data = data[:mid] + os.urandom(4096) + data[mid + 4096:]
    else:
        data = data[:mid] + b"chen them 100 byte".ljust(100, b"!") + data[mid:]
    write(big, data)
    s2 = repo.backup([str(src)])["stats"]
    print(f"\n[4] {kieu}: mau moi {s2['chunks_new']}/{s2['chunks']} "
          f"({s2['bytes_new']:,}/{s2['bytes']:,} byte du lieu goc), lan dau {s1['chunks']} mau")
    assert 1 <= s2["chunks_new"] <= 3
    assert s2["bytes_new"] < 0.25 * s2["bytes"]
    out = tmp_path / "ra"
    repo.restore("latest" and repo.resolve("latest"), out)
    assert (out / "src" / "csdl.mdf").read_bytes() == data


# ---------------------------------------------------------------- 5
def test_5_sai_mat_khau_khong_mo_duoc_kho(tmp_path):
    new_repo(tmp_path / "kho")
    with pytest.raises(WrongPassword):
        Repository.open(LocalRepo(tmp_path / "kho"), PASSWORD + "x")
    with pytest.raises(WrongPassword):
        Repository.open(LocalRepo(tmp_path / "kho"), "")
    assert reopen(tmp_path / "kho").keys is not None


# ---------------------------------------------------------------- 6
def test_6_file_rong_ten_tieng_viet_duong_dan_dai(tmp_path):
    src = tmp_path / "Tài liệu"
    write(src / "rỗng.txt", b"")
    write(src / "0 byte.bin", b"")
    write(src / "Biên bản họp – ngày 14·10.docx", "Nội dung tiếng Việt có dấu".encode())
    (src / "thư mục trống").mkdir()
    deep = src / "/".join(f"thu_muc_long_nhau_so_{i:02d}" for i in range(12))
    write(deep / "Ổ cứng sâu.txt", b"x" * 1000)
    assert len(str(deep / "Ổ cứng sâu.txt")) > 260
    mt = 1_700_000_000_123_456_700
    os.utime(src / "rỗng.txt", ns=(mt, mt))

    repo = new_repo(tmp_path / "kho")
    res = repo.backup([str(src)])
    tree = {e["path"]: e for e in repo.load_snapshot(res["snapshot_id"])["tree"]}
    assert tree["Tài liệu/rỗng.txt"]["chunks"] == [] and tree["Tài liệu/0 byte.bin"]["size"] == 0
    out = tmp_path / "ra"
    repo.restore(res["snapshot_id"], out)
    assert file_hashes(out / "Tài liệu") == file_hashes(src)
    assert "thư mục trống" in dirs_of(out / "Tài liệu")
    assert os.stat(out / "Tài liệu" / "rỗng.txt").st_mtime_ns == mt       # tra lai mtime goc
    shutil.rmtree("\\\\?\\" + str(out) if os.name == "nt" else out)
