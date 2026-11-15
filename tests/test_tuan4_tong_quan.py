"""
Tuan 4 (B): trang tong quan v2 - RPO xanh/vang/do, ti le khu trung lap, may & snapshot, tinh trang kho;
job 'verify' (khoi phuc thu) va 'check' (kiem tra kho) tao tu web, agent chay bang loi v2; lich 'verify'.
"""
import json
import os
from datetime import datetime, timedelta

import pytest
import requests

from server import monitor, scheduler
from shared import config, database
from tests.core_helpers import PASSWORD, new_repo, write


def login(env, username="admin", password="admin-pass-123"):
    s = requests.Session()
    r = s.post(f"{env.url}/api/ui/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    s.headers["X-CSRF-Token"] = r.json()["csrf"]
    return s


def v2_backup(uid, host, hours_ago, files=100, nbytes=50_000_000, uploaded=40_000_000, chunks=120, new=110):
    """Ghi mot ban ghi backup v2 da hoan tat (nhu agent bao ve server) voi thoi diem lui ve truoc."""
    t = (datetime.now().astimezone() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    bid = database.create_backup_record(uid, "v2-" + "a" * 64, [r"D:\Data"], "selected")
    database.update_backup(bid, size=uploaded, status="completed", host=host,
                           snapshot_summary=json.dumps({"total_files": files, "total_size": nbytes, "components": ["files"]}),
                           stats=json.dumps({"engine": "v2", "files": files, "bytes": nbytes, "bytes_uploaded": uploaded,
                                             "chunks": chunks, "chunks_new": new, "seconds": 4.2}))
    with database.get_db() as conn:
        conn.execute("UPDATE backups SET created_at=? WHERE id=?", (t, bid))
    return bid


# ---------------------------------------------------------------- RPO
def test_rpo_xanh_vang_do():
    now = datetime(2026, 11, 14, 10, 0).astimezone()
    at = lambda h: (now - timedelta(hours=h)).isoformat()      # noqa: E731
    assert monitor.rpo_status(None, now, 24)["status"] == "do"
    assert monitor.rpo_status(at(2), now, 24)["status"] == "xanh"
    assert monitor.rpo_status(at(23.9), now, 24)["status"] == "xanh"
    assert monitor.rpo_status(at(30), now, 24)["status"] == "vang"
    assert monitor.rpo_status(at(49), now, 24)["status"] == "do"
    assert monitor.rpo_status(at(2), now, 24, last_failed=True)["status"] == "vang"
    r = monitor.rpo_status(at(2), now, 24)
    assert r["age_hours"] == 2 and r["target_hours"] == 24 and "trong mục tiêu" in r["message"]
    assert "Chưa có" in monitor.rpo_status(None, now)["message"]


def test_ti_le_khu_trung_lap():
    st = lambda b, u: json.dumps({"engine": "v2", "bytes": b, "bytes_uploaded": u})   # noqa: E731
    backups = [{"status": "completed", "stats": st(500, 500), "size": 500},
               {"status": "completed", "stats": st(500, 40), "size": 40},
               {"status": "completed", "stats": st(500, 40), "size": 40},
               {"status": "completed", "stats": json.dumps({"files": 3}), "size": 999},        # v1: bo qua
               {"status": "failed", "stats": st(500, 1), "size": 1}]
    d = monitor.dedup(backups)
    assert d["snapshots"] == 3 and d["logical"] == 1500 and d["uploaded"] == 580
    assert d["ratio"] == 2.59 and d["saved"] == 920
    assert monitor.dedup([])["ratio"] is None


# ---------------------------------------------------------------- kho
def test_kho_stats_doc_thu_muc(tmp_path, monkeypatch):
    repo = new_repo(tmp_path / "kho")
    write(tmp_path / "d" / "a.bin", os.urandom(20_000))
    repo.backup([str(tmp_path / "d")])
    monkeypatch.setattr(config, "KHO_DIR", str(tmp_path / "kho"))
    k = monitor.kho_stats(force=True)
    assert k["source"] == "dir" and k["reachable"] and k["initialized"]
    assert k["packs"] == 1 and k["snapshots"] == 1 and k["bytes_on_disk"] > 20_000 and k["disk"]["free"] > 0


def test_kho_stats_url_khong_ket_noi(monkeypatch):
    monkeypatch.setattr(config, "KHO_DIR", "")
    monkeypatch.setattr(config, "KHO_URL", "http://127.0.0.1:9")
    k = monitor.kho_stats(force=True)
    assert k["source"] == "url" and k["reachable"] is False and "error" in k


def test_kho_stats_qua_api_kho_that(tmp_path, monkeypatch):
    import threading
    from werkzeug.serving import make_server
    from kho.app import create_app
    srv = make_server("127.0.0.1", 0, create_app(tmp_path / "kho"), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(config, "KHO_DIR", "")
        monkeypatch.setattr(config, "KHO_URL", f"http://127.0.0.1:{srv.port}")
        k = monitor.kho_stats(force=True)
        assert k["reachable"] and k["packs"] == 0 and k["initialized"] is False and k["version"]
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- API tong quan + su kien
def test_tong_quan_co_rpo_may_snapshot_dedup_su_kien(env, monkeypatch):
    monkeypatch.setattr(config, "KHO_DIR", "")
    monkeypatch.setattr(config, "KHO_URL", "")
    uid = env.admin["id"]
    v2_backup(uid, "PC-KHO", hours_ago=30, nbytes=500, uploaded=500)
    v2_backup(uid, "PC-KHO", hours_ago=2, nbytes=500, uploaded=40)
    v2_backup(uid, "LAPTOP-DUY", hours_ago=60, nbytes=100, uploaded=100)
    database.touch_agent(uid, "PC-KHO", "127.0.0.1", "1.5.0", "Windows")
    ev = database.add_event("anomaly", "Cổng chặn bất thường", "80% file đổi", "err", uid)
    database.add_event("backup", "Sao lưu xong", "", "ok", uid)

    s = login(env)
    ov = s.get(f"{env.url}/api/ui/overview").json()
    v2 = ov["v2"]
    assert v2["rpo"]["status"] == "xanh" and v2["rpo"]["target_hours"] == config.RPO_HOURS
    by_host = {m["hostname"]: m for m in v2["machines"]}
    assert by_host["PC-KHO"]["online"] and by_host["PC-KHO"]["rpo"]["status"] == "xanh"
    assert by_host["LAPTOP-DUY"]["online"] is False and by_host["LAPTOP-DUY"]["rpo"]["status"] == "do"
    assert len(v2["snapshots"]) == 3 and v2["snapshots"][0]["host"] == "PC-KHO" and v2["snapshots"][0]["uploaded"] == 40
    assert v2["snapshots"][0]["snapshot"] == "a" * 64 and v2["snapshots"][0]["files"] == 100
    assert v2["dedup"] == {"snapshots": 3, "logical": 1100, "uploaded": 640, "saved": 460, "ratio": 1.72}
    assert v2["kho"] is None
    assert ov["alerts_open"] == 1 and [e["kind"] for e in ov["events"]] == ["backup", "anomaly"]

    # trang Thong bao: liet ke, loc chua xac nhan, xac nhan
    r = s.get(f"{env.url}/api/ui/events?open=1").json()
    assert [e["id"] for e in r["events"]] == [ev["id"]] and r["alerts_open"] == 1
    bad = s.post(f"{env.url}/api/ui/events/{ev['id']}/ack", json={"verdict": "khac"})
    assert bad.status_code == 400
    r = s.post(f"{env.url}/api/ui/events/{ev['id']}/ack", json={"verdict": "su_co"}).json()["event"]
    assert r["ack"] == "su_co" and r["ack_by"] == "admin" and r["ack_at"]
    assert s.get(f"{env.url}/api/ui/overview").json()["alerts_open"] == 0
    assert s.post(f"{env.url}/api/ui/events/99999/ack", json={"verdict": "su_co"}).status_code == 404


def test_tong_quan_chua_co_gi_thi_rpo_do(env, monkeypatch):
    monkeypatch.setattr(config, "KHO_URL", "")
    s = login(env)
    v2 = s.get(f"{env.url}/api/ui/overview").json()["v2"]
    assert v2["rpo"]["status"] == "do" and v2["machines"] == [] and v2["snapshots"] == []
    k = s.get(f"{env.url}/api/ui/kho").json()
    assert k["kho"] is None and k["dedup"]["ratio"] is None and k["rpo_hours"] == config.RPO_HOURS


# ---------------------------------------------------------------- job verify / check qua web, agent chay v2
def test_khoi_phuc_thu_va_kiem_tra_kho_tu_web(env, tmp_path, monkeypatch):
    import agent.agent as A
    from server import notify
    monkeypatch.setattr(notify, "SYNC", True)
    repo = new_repo(tmp_path / "kho_v2")
    data = tmp_path / "Data"
    write(data / "a.txt", "nội dung".encode() * 100)
    write(data / "b.bin", os.urandom(30_000))
    repo.backup([str(data)])
    (tmp_path / "pw.txt").write_text(PASSWORD, encoding="utf-8")
    monkeypatch.setattr(config, "ENGINE", "v2")
    monkeypatch.setattr(config, "V2_REPO", str(tmp_path / "kho_v2"))
    monkeypatch.setattr(config, "V2_PASSWORD_FILE", str(tmp_path / "pw.txt"))
    monkeypatch.setattr(A, "_v2", None)
    uid = env.admin["id"]
    api = A.ServerApi(config.SERVER_URL, env.admin["token"])
    s = login(env)

    r = s.post(f"{env.url}/api/ui/kho/verify", json={"sample": 5})
    assert r.status_code == 201 and r.json()["job"]["type"] == "verify"
    assert s.post(f"{env.url}/api/ui/kho/verify", json={"sample": 5}).status_code == 409      # trung
    A.run_job(api, api.poll())
    j = database.get_job(r.json()["job"]["id"])
    assert j["status"] == "completed" and "2/2 file khớp SHA-256" in j["message"], j["message"]
    ev = database.list_events(uid, 1)[0]
    assert ev["kind"] == "verify" and ev["level"] == "ok" and ev["title"].startswith("Khôi phục thử: OK")

    r = s.post(f"{env.url}/api/ui/kho/check", json={"full": True})
    A.run_job(api, api.poll())
    j = database.get_job(r.json()["job"]["id"])
    assert j["status"] == "completed" and "toàn vẹn" in j["message"], j["message"]

    # lam hong 1 pack -> kiem tra phai bao loi -> su kien err
    from core.repo_local import LocalRepo
    pid = LocalRepo(tmp_path / "kho_v2").list_packs()[0]
    p = tmp_path / "kho_v2" / "packs" / pid[:2] / pid
    raw = bytearray(p.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    os.chmod(p, 0o600)
    p.write_bytes(bytes(raw))
    r = s.post(f"{env.url}/api/ui/kho/check", json={"full": False})
    A.run_job(api, api.poll())
    j = database.get_job(r.json()["job"]["id"])
    assert j["status"] == "failed" and "KHO CÓ LỒI" not in j["message"] and "LỖI" in j["message"].upper()
    ev = database.list_events(uid, 1)[0]
    assert ev["kind"] == "kho" and ev["level"] == "err" and database.count_open_alerts(uid) == 1


def test_lich_khoi_phuc_thu_hang_tuan(env):
    s = login(env)
    r = s.post(f"{env.url}/api/ui/schedules", json={"name": "Khôi phục thử CN", "schedule_type": "weekly",
                                                   "time_of_day": "03:00", "day_of_week": 6, "job_type": "verify"})
    assert r.status_code == 201, r.text
    sc = r.json()["schedule"]
    assert sc["job_type"] == "verify" and sc["components"] == list(config.BACKUP_COMPONENTS)   # components mac dinh, khong dung
    n = scheduler.check_due(now=datetime.now() + timedelta(days=8))
    assert n == 1
    job = database.list_jobs(env.admin["id"], 1)[0]
    assert job["job_type"] == "verify" and json.loads(job["params"])["sample"] == 20
    r = s.post(f"{env.url}/api/ui/schedules/{sc['id']}/run")
    assert r.status_code == 201 and r.json()["job"]["type"] == "verify"
    r = s.post(f"{env.url}/api/ui/schedules", json={"name": "SL", "schedule_type": "daily", "components": ["files"]})
    assert r.json()["schedule"]["job_type"] == "backup"
