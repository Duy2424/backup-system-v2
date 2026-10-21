"""Tuan 5 (A): giu theo chinh sach (24 gio / 7 ngay / 4 tuan / 3 thang) + don kho, chay thu truoc."""
import os
from datetime import datetime, timedelta

import pytest

from core.errors import RepoError
from core.prune import plan_prune, run_prune, select_keep
from core.repo_local import LocalRepo
from tests.core_helpers import file_hashes, new_repo, reopen, write


def snap(i, t, host="PC"):
    return {"id": f"{i:064x}", "time": t.isoformat(), "host": host, "sources": [r"D:\Data"]}


def test_chon_ban_giu_kieu_restic():
    base = datetime(2026, 10, 20, 23, 0)
    snaps = [snap(i, base - timedelta(hours=6 * i)) for i in range(40)]        # 6 gio/ban, ~10 ngay
    keep, forget = select_keep(snaps, {"hourly": 0, "daily": 3, "weekly": 0, "monthly": 0})
    days = sorted({datetime.fromisoformat(s["time"]).date() for s in snaps if s["id"] in keep})
    assert len(keep) == 3 and len(days) == 3 and days[-1] == base.date()      # ban moi nhat cua 3 ngay gan nhat
    assert len(forget) == 37
    keep2, _ = select_keep(snaps + [{"id": "e" * 64, "error": "hong", "time": ""}], {})
    assert "e" * 64 in keep2 and snaps[0]["id"] in keep2                       # khong xoa ban hong; luon giu ban moi nhat


def test_chay_thu_khong_doi_gi_roi_ap_dung(tmp_path):
    repo = new_repo(tmp_path / "kho", pack_target=512 * 1024)
    src = tmp_path / "Data"
    start = datetime(2026, 9, 1, 8, 0)
    for d in range(12):                                                       # 12 ngay, moi ngay du lieu moi
        write(src / f"ngay_{d:02d}.bin", os.urandom(300_000))
        if d >= 3:
            (src / f"ngay_{d - 3:02d}.bin").unlink()                          # chi giu 3 file gan nhat
        repo.backup([str(src)], when=start + timedelta(days=d))
    latest_hashes = file_hashes(src)
    before = sorted(os.listdir(tmp_path / "kho" / "snapshots"))
    plan = plan_prune(repo, {"hourly": 0, "daily": 4, "weekly": 0, "monthly": 0})
    assert len(plan.forget) == 8 and plan.delete_packs
    assert sorted(os.listdir(tmp_path / "kho" / "snapshots")) == before        # chay thu: chua xoa gi
    freed = run_prune(repo, plan, log=lambda *_: None)
    r = reopen(tmp_path / "kho")
    assert len(r.list_snapshots()) == 4 and freed > 0
    assert r.check()["errors"] == []
    r.restore(r.resolve("latest"), tmp_path / "ra")
    assert file_hashes(tmp_path / "ra" / "Data") == latest_hashes
    assert not (tmp_path / "kho" / "locks" / "prune.lock").exists()


def test_chep_lai_pack_dung_mot_phan(tmp_path):
    repo = new_repo(tmp_path / "kho")                                         # pack 16 MiB: ca 2 lan vao 1-2 pack
    src = tmp_path / "Data"
    write(src / "giu.bin", os.urandom(200_000))
    write(src / "bo.bin", os.urandom(800_000))
    repo.backup([str(src)], when=datetime(2026, 1, 1))
    (src / "bo.bin").unlink()
    repo.backup([str(src)], when=datetime(2026, 3, 1), parent=None)
    plan = plan_prune(repo, {"hourly": 0, "daily": 0, "weekly": 0, "monthly": 1})
    assert len(plan.forget) == 1 and len(plan.repack) == 1                    # pack con 1 mau dung/2 -> chep lai
    run_prune(repo, plan, log=lambda *_: None)
    r = reopen(tmp_path / "kho")
    assert r.check()["errors"] == []
    r.restore(r.resolve("latest"), tmp_path / "ra")
    assert (tmp_path / "ra" / "Data" / "giu.bin").read_bytes() == (src / "giu.bin").read_bytes()


def test_khong_don_qua_api(tmp_path):
    from core.repo_http import HttpRepo
    from core.repository import Repository
    r = Repository.__new__(Repository)
    r.backend = HttpRepo("http://127.0.0.1:1")
    with pytest.raises(RepoError):
        plan_prune(r)
