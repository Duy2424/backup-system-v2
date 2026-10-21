"""Tuan 6: cong chan bat thuong (ransomware) truoc khi gui + khoi phuc thu hang tuan."""
import os
import random

import pytest

from bench import make_dataset
from core.anomaly import AnomalyDetected, entropy
from core.repo_local import LocalRepo
from tests.core_helpers import new_repo, reopen, write


@pytest.fixture()
def setup(tmp_path):
    root = tmp_path / "du_lieu"
    make_dataset.generate(root, "6MB", seed=61)
    write(root / "~bks_canary_dung_sua.txt", "File mồi - không ai được sửa".encode())
    repo = new_repo(tmp_path / "kho")
    repo.backup([str(root)])
    return repo, root, tmp_path


def text_files(root):
    return [p for _, p in make_dataset.iter_files(root) if p.suffix in (".txt", ".csv", ".md", ".json", ".ini", ".xml")
            and "canary" not in p.name]


def counts(tmp_path):
    return len(LocalRepo(tmp_path / "kho").list_packs()), len(os.listdir(tmp_path / "kho" / "snapshots"))


def test_entropy():
    assert entropy(b"a" * 1000) == 0 and entropy(os.urandom(65536)) > 7.9
    assert entropy("Báo cáo doanh thu tháng".encode() * 100) < 5


def test_thay_doi_binh_thuong_khong_bao_dong(setup):
    repo, root, _ = setup
    make_dataset.mutate(root, 5, seed=61, round_no=1)
    res = repo.backup([str(root)])
    assert res["anomaly"]["alarm"] is False and res["anomaly"]["changed"] > 0


def test_ransomware_ma_hoa_file_bi_chan_truoc_khi_gui(setup):
    repo, root, tmp = setup
    files = text_files(root)
    rng = random.Random(1)
    for p in rng.sample(files, int(len(files) * 0.8)):
        p.write_bytes(os.urandom(max(p.stat().st_size, 1)))             # "ma hoa" giu nguyen ten
    before = counts(tmp)
    with pytest.raises(AnomalyDetected) as ex:
        repo.backup([str(root)])
    print(f"\n[6] {ex.value.report['reasons']}")
    assert counts(tmp) == before                                         # KHONG gui pack/snapshot nao
    assert ex.value.report["suspicious"] >= len(files) // 2
    assert repo.backup([str(root)], force=True)["anomaly"]["alarm"]      # --force van chay (co danh dau)


def test_file_moi_bi_sua_bao_dong_ngay(setup):
    repo, root, tmp = setup
    (root / "~bks_canary_dung_sua.txt").write_bytes(b"da bi ma hoa")
    with pytest.raises(AnomalyDetected, match="file mồi"):
        repo.backup([str(root)])


def test_duoi_file_ransomware(setup):
    repo, root, _ = setup
    for p in text_files(root):
        p.rename(p.with_name(p.name + ".locked"))
    with pytest.raises(AnomalyDetected):
        repo.backup([str(root)])


def test_khoi_phuc_thu_ok_va_phat_hien_pack_hong(setup):
    repo, root, tmp = setup
    rep = repo.verify_restore(sample=10, seed=3, workdir=tmp)
    assert rep["result"] == "OK" and rep["ok"] == rep["checked"] == 10
    for pid in LocalRepo(tmp / "kho").list_packs():                      # lam hong moi pack
        p = tmp / "kho" / "packs" / pid[:2] / pid
        raw = bytearray(p.read_bytes())
        raw[len(raw) // 3] ^= 0xFF
        os.chmod(p, 0o600)
        p.write_bytes(bytes(raw))
    bad = reopen(tmp / "kho").verify_restore(sample=10, seed=3, workdir=tmp)
    assert bad["result"] == "LỖI" and bad["failed"]
    assert not [d for d in os.listdir(tmp) if d.startswith("bks-verify-")]   # khong de lai thu muc tam
