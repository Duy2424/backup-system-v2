"""Agent chay job web bang loi v2: sao luu -> ban ghi v2 tren server -> khoi phuc tai cho."""
import os

import pytest

from shared import config, database
from tests.core_helpers import PASSWORD, file_hashes, new_repo, write


def test_khoi_phuc_tai_cho_core(tmp_path):
    src = tmp_path / "Data"
    write(src / "a.txt", b"aaa")
    write(src / "con" / "b.bin", os.urandom(5000))
    repo = new_repo(tmp_path / "kho")
    sid = repo.backup([str(src)])["snapshot_id"]
    goc = file_hashes(src)
    (src / "a.txt").write_bytes(b"bi ma hoa")
    os.remove(src / "con" / "b.bin")
    write(src / "thua.txt", b"x")
    dry = repo.restore(sid, in_place=True, delete_extra=True, dry_run=True)
    assert (dry["to_write"], dry["deleted"]) == (2, 1) and (src / "thua.txt").exists()
    st = repo.restore(sid, in_place=True)
    assert st["unchanged"] == 0 and st["files"] == 2 and (src / "thua.txt").exists()   # mac dinh khong xoa
    st2 = repo.restore(sid, in_place=True, delete_extra=True)
    assert st2["files"] == 0 and st2["unchanged"] == 2 and st2["deleted"] == 1
    assert file_hashes(src) == goc


def test_job_web_chay_bang_v2(env, tmp_path, monkeypatch):
    import agent.agent as A
    from agent import system_state
    new_repo(tmp_path / "kho_v2")
    (tmp_path / "pw.txt").write_text(PASSWORD, encoding="utf-8")
    monkeypatch.setattr(config, "ENGINE", "v2")
    monkeypatch.setattr(config, "V2_REPO", str(tmp_path / "kho_v2"))
    monkeypatch.setattr(config, "V2_PASSWORD_FILE", str(tmp_path / "pw.txt"))
    monkeypatch.setattr(A, "_v2", None)
    applied = []
    monkeypatch.setattr(system_state, "restore_system_state", lambda st: applied.append(st))   # KHONG doi mang that

    data = tmp_path / "Data"
    write(data / "Hợp đồng.docx", os.urandom(300_000))
    write(data / "ghi chú.txt", "nội dung".encode())
    goc = file_hashes(data)
    uid = env.admin["id"]
    api = A.ServerApi(config.SERVER_URL, env.admin["token"])

    jid = database.create_job(uid, "backup", {"components": ["files", "ipv4"], "paths": [str(data)]})
    A.run_job(api, api.poll())
    job = database.get_job(jid)
    assert job["status"] == "completed" and "v2" in job["message"], job["message"]
    b = database.get_backup(job["backup_id"])
    assert b["filename"].startswith("v2-") and b["size"] > 0 and '"engine": "v2"' in b["stats"]

    (data / "ghi chú.txt").write_bytes(b"bi sua")
    os.remove(data / "Hợp đồng.docx")
    rid = database.create_job(uid, "restore", {"filename": b["filename"], "dry_run": False, "delete_extra": False,
                                               "target_dir": None, "restore_system": True}, backup_id=b["id"])
    A.run_job(api, api.poll())
    rj = database.get_job(rid)
    assert rj["status"] == "completed", rj["message"]
    assert file_hashes(data) == goc
    assert applied and applied[0]["components"] == ["ipv4"]          # cau hinh mang lay tu chinh snapshot
