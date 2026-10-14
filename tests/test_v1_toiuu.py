"""Test ban v1 toi uu: ma hoa, loc file, backup/restore that qua HTTP, bao mat API."""
import gzip
import hashlib
import io
import json
import os
import tarfile
import time
from datetime import datetime

import pytest

from shared import config, database, encryption_utils as eu
from shared.snapshot import ExcludeMatcher, scan_files


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def tree_hashes(root):
    out = {}
    for dp, _, files in os.walk(root):
        for f in files:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root).replace("\\", "/")] = sha(p)
    return out


# ===================================================================== ma hoa

@pytest.mark.parametrize("size", [0, 1, eu.SEG_SIZE - 1, eu.SEG_SIZE, eu.SEG_SIZE + 1, 3 * eu.SEG_SIZE + 7])
def test_bkp2_khu_hoi(tmp_path, size):
    src, enc, dec = tmp_path / "a", tmp_path / "a.bkup", tmp_path / "a.out"
    src.write_bytes(os.urandom(size))
    eu.encrypt_file(src, enc, "khoa-thu")
    assert enc.read_bytes()[:4] == b"BKP2"
    eu.decrypt_file(enc, dec, "khoa-thu")
    assert dec.read_bytes() == src.read_bytes()


def test_bkp2_sua_1_byte_cat_cut_sai_khoa_deu_bi_tu_choi(tmp_path):
    src, enc = tmp_path / "a", tmp_path / "a.bkup"
    src.write_bytes(os.urandom(3 * eu.SEG_SIZE + 100))
    eu.encrypt_file(src, enc, "k")
    data = enc.read_bytes()
    for pos in (20, len(data) // 2, len(data) - 1):           # sua 1 byte o dau / giua / cuoi
        bad = bytearray(data)
        bad[pos] ^= 0x01
        (tmp_path / "bad").write_bytes(bad)
        with pytest.raises(eu.IntegrityError):
            eu.decrypt_file(tmp_path / "bad", tmp_path / "x", "k")
    (tmp_path / "cut").write_bytes(data[: eu.HEADER_LEN + eu.SEG_SIZE + eu.TAG])   # bo doan cuoi
    with pytest.raises(eu.IntegrityError):
        eu.decrypt_file(tmp_path / "cut", tmp_path / "x", "k")
    with pytest.raises(eu.IntegrityError):
        eu.decrypt_file(enc, tmp_path / "x", "khoa-sai")


def test_doc_duoc_dinh_dang_cu_cbc(tmp_path):
    src, enc, dec = tmp_path / "a", tmp_path / "a.bkup", tmp_path / "b"
    src.write_bytes(os.urandom(2 * eu.SEG_SIZE + 33))
    eu.encrypt_file_legacy(src, enc, "k")
    assert enc.read_bytes()[:4] == b"BKUP"
    eu.decrypt_file(enc, dec, "k")
    assert dec.read_bytes() == src.read_bytes()


# ===================================================================== loc file

def test_bo_loc_khong_con_khop_chuoi_con(tmp_path):
    for rel in ["contract.docx", "backup.txt", "answer.txt", "Thumbs.db", "~$baocao.docx", "x.tmp",
                "__pycache__/a.pyc", "Temp/b.txt", "ok/Báo cáo.docx"]:
        p = tmp_path / "d" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    got = {rel for rel, _, _ in scan_files([str(tmp_path / "d")], ExcludeMatcher.from_config(config))}
    assert got == {"d/contract.docx", "d/backup.txt", "d/answer.txt", "d/ok/Báo cáo.docx"}


# ===================================================================== backup / restore that

def make_data(root):
    files = {
        "tai_lieu/Hợp đồng số 1.docx": os.urandom(300_000),
        "tai_lieu/contract.docx": b"hop dong " * 5000,
        "van_ban/ghi_chu.txt": "Sao lưu tiếng Việt có dấu\n".encode() * 2000,
        "rong.txt": b"",
        "lon/data.bin": os.urandom(3 * 1024 * 1024 + 123),
        "sau/" + "/".join(["thu_muc_con_dai"] * 18) + "/file_sau.txt": b"duong dan > 260 ky tu",
    }
    for rel, data in files.items():
        p = os.path.join(root, *rel.split("/"))
        os.makedirs("\\\\?\\" + os.path.dirname(os.path.abspath(p)) if os.name == "nt" else os.path.dirname(p),
                    exist_ok=True)
        with open(("\\\\?\\" + os.path.abspath(p)) if os.name == "nt" else p, "wb") as f:
            f.write(data)
    return files


def long_hashes(root):
    from shared.snapshot import long_path
    out = {}
    for dp, _, files in os.walk(long_path(root)):
        for f in files:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, long_path(root)).replace("\\", "/")] = sha(p)
    return out


def test_backup_restore_qua_http(env):
    from agent import backup_logic, restore_logic
    data = env.tmp / "du_lieu"
    make_data(str(data))
    before = long_hashes(str(data))
    assert any(len(str(data / k)) > 260 for k in before)

    res = backup_logic.perform_backup(env.admin, paths=[str(data)], components=["files"])
    assert res["snapshot_summary"]["total_files"] == len(before)
    stored = os.path.join(config.STORAGE_DIR, f"user_{env.admin['id']}", res["filename"])
    assert os.path.getsize(stored) == res["size"]
    assert hashlib.sha256(open(stored, "rb").read()).hexdigest() == res["sha256"]
    assert not os.listdir(config.BACKUP_TEMP_DIR)        # khong de lai file tam

    # Hong hoa: xoa 1 file, sua 1 file, them 1 file thua
    os.remove(data / "van_ban" / "ghi_chu.txt")
    (data / "tai_lieu" / "contract.docx").write_bytes(b"bi ransomware ma hoa")
    (data / "thua.txt").write_text("tao sau khi sao luu")

    dry = restore_logic.perform_restore(env.admin, res["filename"], dry_run=True)
    s = dry["compare_result"]["summary"]
    assert (s["to_add"], s["to_overwrite"], s["to_delete"]) == (1, 1, 1)
    assert not (data / "van_ban" / "ghi_chu.txt").exists()     # chay thu khong doi gi

    restore_logic.perform_restore(env.admin, res["filename"])
    after = long_hashes(str(data))
    assert after.pop("thua.txt")                                   # mac dinh KHONG xoa file thua
    assert after == before

    restore_logic.perform_restore(env.admin, res["filename"], delete_extra=True)
    assert not (data / "thua.txt").exists()

    out = env.tmp / "khoi_phuc_ra_cho_khac"
    restore_logic.perform_restore(env.admin, res["filename"], target_dir=str(out))
    assert long_hashes(str(out / "du_lieu")) == before
    assert not os.listdir(config.RESTORE_TEMP_DIR)


def test_file_backup_bi_sua_thi_khong_khoi_phuc(env):
    from agent import backup_logic, restore_logic
    data = env.tmp / "d"
    data.mkdir()
    (data / "a.bin").write_bytes(os.urandom(2_500_000))
    res = backup_logic.perform_backup(env.admin, paths=[str(data)], components=["files"])
    stored = os.path.join(config.STORAGE_DIR, f"user_{env.admin['id']}", res["filename"])
    raw = bytearray(open(stored, "rb").read())
    raw[len(raw) // 2] ^= 0xFF
    open(stored, "wb").write(raw)
    (data / "a.bin").write_bytes(b"hien tai")
    with pytest.raises(eu.IntegrityError):
        restore_logic.perform_restore(env.admin, res["filename"])
    assert (data / "a.bin").read_bytes() == b"hien tai"            # khong ghi du lieu sai


def test_khoi_phuc_ban_backup_cu_cua_v1(env, tmp_path):
    from agent import restore_logic
    src = tmp_path / "goc"
    src.mkdir()
    (src / "a.txt").write_text("du lieu v1")
    tar_path = tmp_path / "archive.tar.gz"
    snap = {"files": {"goc/a.txt": {"abs_path": str(src / "a.txt"), "size": 10, "mtime": 0,
                                    "hash": sha(src / "a.txt")}}, "paths": [str(src)]}
    meta = {"components": ["files"], "paths": [str(src)], "created_at": datetime.now().isoformat()}
    with tarfile.open(tar_path, "w:gz") as tar:
        for name, obj in (("_meta/metadata.json", meta), ("_meta/snapshot.json", snap), ("_meta/system_state.json", {})):
            b = json.dumps(obj).encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            tar.addfile(ti, io.BytesIO(b))
        tar.add(src / "a.txt", arcname="_data/goc/a.txt")
    d = os.path.join(config.STORAGE_DIR, f"user_{env.admin['id']}")
    os.makedirs(d, exist_ok=True)
    eu.encrypt_file_legacy(tar_path, os.path.join(d, "backup_cu.bkup"), env.admin["encryption_key"])
    out = tmp_path / "ra"
    restore_logic.perform_restore(env.admin, "backup_cu.bkup", target_dir=str(out))
    assert (out / "goc" / "a.txt").read_text() == "du lieu v1"


def test_huy_giua_chung_khong_de_lai_file_do_dang(env):
    from agent import backup_logic
    data = env.tmp / "d"
    data.mkdir()
    for i in range(6):
        (data / f"f{i}.bin").write_bytes(os.urandom(1_500_000))

    seen = []

    def cb(p, m):
        if m.startswith("Đã xử lý"):        # dang stream du lieu len server
            seen.append(p)
            raise backup_logic.JobCancelled()
    with pytest.raises(backup_logic.JobCancelled):
        backup_logic.perform_backup(env.admin, paths=[str(data)], components=["files"], progress_cb=cb)
    assert seen, "phai huy trong luc dang gui du lieu"
    d = os.path.join(config.STORAGE_DIR, f"user_{env.admin['id']}")
    deadline = time.time() + 5          # server can vai tram ms de nhan ra client da ngat
    while os.path.isdir(d) and os.listdir(d) and time.time() < deadline:
        time.sleep(0.1)
    assert not os.path.isdir(d) or os.listdir(d) == []      # khong co .part, khong co .bkup do dang


# ===================================================================== API / bao mat

def login(client, user="admin", pw="admin-pass-123"):
    r = client.post("/api/ui/login", json={"username": user, "password": pw})
    return r


def test_dang_nhap_csrf_va_header_bao_mat(env):
    c = env.app.test_client()
    assert login(c, pw="sai").status_code == 401
    r = login(c)
    assert r.status_code == 200
    csrf = r.get_json()["csrf"]
    assert "Content-Security-Policy" in r.headers
    assert c.post("/api/ui/backups", json={"components": ["files"]}).status_code == 403     # thieu CSRF
    r = c.post("/api/ui/backups", json={"components": ["files"]}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 201
    assert c.get("/api/ui/overview").get_json()["active_job"]["status"] == "pending"
    # bam 2 lan -> khong tao job trung
    r2 = c.post("/api/ui/backups", json={"components": ["files"]}, headers={"X-CSRF-Token": csrf})
    assert r2.status_code == 409 and r2.get_json()["error"] == "duplicate"


def test_khoa_ip_sau_5_lan_sai(env):
    c = env.app.test_client()
    for _ in range(5):
        login(c, pw="sai")
    assert login(c).status_code == 429


def test_mat_khau_kieu_cu_van_dang_nhap_va_tu_nang_cap(env):
    import hashlib as hl
    legacy = "abc$" + hl.sha256(b"abcmatkhau-cu").hexdigest()
    uid = database.create_user("cu", "tam-thoi-123")
    with database.get_db() as conn:
        conn.execute("UPDATE users SET password=? WHERE id=?", (legacy, uid))
    assert login(env.app.test_client(), "cu", "matkhau-cu").status_code == 200
    assert database.get_user_by_id(uid)["password"].startswith("scrypt$")


def test_agent_chi_lay_duoc_job_cua_minh(env):
    c = env.app.test_client()
    b_id = database.create_user("nguoi_b", "mat-khau-b-123")
    b = database.get_user_by_id(b_id)
    jid = database.create_job(env.admin["id"], "backup", {"components": ["files"]})
    hb = {"X-Auth-Token": b["token"], "X-Agent-Host": "MAY-B"}
    assert c.get("/api/jobs/poll", headers=hb).get_json()["job"] is None          # khong thay job cua admin
    assert c.post(f"/api/jobs/{jid}/update", json={"status": "failed"}, headers=hb).status_code == 404
    ha = {"X-Auth-Token": env.admin["token"], "X-Agent-Host": "MAY-A"}
    job = c.get("/api/jobs/poll", headers=ha).get_json()["job"]
    assert job["id"] == jid and job["_user"]["id"] == env.admin["id"]
    assert c.get("/api/jobs/poll", headers={"X-Auth-Token": "sai"}).status_code == 401


def test_kho_chi_cho_them(env):
    c = env.app.test_client()
    h = {"X-Auth-Token": env.admin["token"]}
    assert c.put("/api/storage/backups/a.bkup", data=b"abc", headers=h).status_code == 201
    assert c.put("/api/storage/backups/a.bkup", data=b"xyz", headers=h).status_code == 409     # khong ghi de
    assert c.delete("/api/storage/backups/a.bkup", headers=h).status_code == 405              # khong co lenh xoa
    assert c.post("/api/storage/delete", json={"filename": "a.bkup"}, headers=h).status_code in (404, 405)
    assert c.put("/api/storage/backups/..%5Cx.bkup", data=b"x", headers=h).status_code in (400, 404)
    assert c.get("/api/storage/backups/a.bkup", headers=h).data == b"abc"


def test_lich_tinh_moc_ke_tiep():
    from server.scheduler import compute_next_run
    now = datetime(2026, 10, 14, 10, 0)          # thu Tu
    assert compute_next_run("daily", 24, "02:00", 0, now) == datetime(2026, 10, 15, 2, 0)
    assert compute_next_run("daily", 24, "23:30", 0, now) == datetime(2026, 10, 14, 23, 30)
    assert compute_next_run("weekly", 24, "03:00", 0, now) == datetime(2026, 10, 19, 3, 0)
    assert compute_next_run("hourly", 6, None, 0, now) == datetime(2026, 10, 14, 16, 0)
