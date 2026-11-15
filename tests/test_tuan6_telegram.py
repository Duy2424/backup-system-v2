"""
Tuan 6 (B): bot Telegram - tin kem 2 nut Binh thuong / Su co, nhan bam nut, tra chat id, webhook /api/notify
(core verify/backup --notify-url), su kien tu job, cai dat Telegram tren web, RpoMonitor doi mau.
Khong goi Telegram that: notify.telegram duoc thay bang ham gia.
"""
import json
from datetime import datetime, timedelta

import pytest
import requests

from server import monitor, notify
from shared import config, database
from tests.test_tuan4_tong_quan import login, v2_backup


@pytest.fixture()
def fake_tg(env, monkeypatch):
    """Thay API Telegram bang ham gia ghi lai moi loi goi; cau hinh token + chat id trong settings."""
    calls = []

    def fake(method, token, http_timeout=15, **params):
        calls.append((method, token, params))
        if method == "sendMessage":
            return {"message_id": 100 + len(calls), "chat": {"id": params["chat_id"]}}
        if method == "getUpdates":
            return []
        return True
    monkeypatch.setattr(notify, "telegram", fake)
    monkeypatch.setattr(notify, "SYNC", True)
    database.set_setting("telegram_token", "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    database.set_setting("telegram_chat_id", "555")
    return calls


def test_dinh_dang_tin_va_nut():
    ev = {"id": 7, "level": "err", "title": "Sao lưu <THẤT BẠI>", "message": "Lỗi & dừng", "created_at": "2026-11-14T10:05:00+07:00",
          "ack": None}
    t = notify.format_event(ev)
    assert "<b>Sao lưu &lt;THẤT BẠI&gt;</b>" in t and "Lỗi &amp; dừng" in t and "10:05 14/11/2026" in t
    acked = notify.format_event({**ev, "ack": "su_co", "ack_by": "Duy", "ack_at": "2026-11-14T10:09:00+07:00"})
    assert "Đã xác nhận: <b>Sự cố</b> (Duy, 10:09 14/11/2026)" in acked
    kb = notify._buttons(7)["inline_keyboard"][0]
    assert [b["callback_data"] for b in kb] == ["ack:7:binh_thuong", "ack:7:su_co"]


def test_notify_ghi_su_kien_va_gui_telegram(fake_tg, env):
    uid = env.admin["id"]
    ev = notify.notify("backup", "Sao lưu THẤT BẠI · PC", "Lỗi đọc file", "err", uid)
    assert database.get_event(ev["id"])["telegram_msg_id"] == 101
    method, token, p = fake_tg[-1]
    assert method == "sendMessage" and p["chat_id"] == "555" and p["parse_mode"] == "HTML"
    assert "Sao lưu THẤT BẠI" in p["text"] and p["reply_markup"]["inline_keyboard"][0][1]["callback_data"] == f"ack:{ev['id']}:su_co"
    ok = notify.notify("backup", "Sao lưu xong", "", "ok", uid, buttons=False)
    assert fake_tg[-1][2]["reply_markup"] is None and database.get_event(ok["id"])["telegram_msg_id"]
    database.set_setting("telegram_notify_ok", "0")                     # khong bao khi thanh cong
    n = len(fake_tg)
    notify.notify("backup", "Sao lưu xong", "", "ok", uid)
    assert len(fake_tg) == n
    notify.notify("backup", "Sao lưu THẤT BẠI", "", "err", uid)          # loi van bao
    assert len(fake_tg) == n + 1
    database.set_setting("telegram_enabled", "0")
    notify.notify("backup", "Sao lưu THẤT BẠI", "", "err", uid)
    assert len(fake_tg) == n + 1 and "tắt" in notify.last_error()


def test_bam_nut_tren_telegram_xac_nhan_su_kien(fake_tg, env):
    uid = env.admin["id"]
    ev = notify.notify("anomaly", "CỔNG CHẶN BẤT THƯỜNG", "80% file đổi", "err", uid)
    poller = notify.TelegramPoller()
    poller.handle({"update_id": 1, "callback_query": {"id": "cq1", "data": f"ack:{ev['id']}:su_co",
                                                      "from": {"first_name": "Duy"},
                                                      "message": {"message_id": 101, "chat": {"id": 555}}}}, "tok")
    e = database.get_event(ev["id"])
    assert e["ack"] == "su_co" and e["ack_by"] == "Duy" and e["ack_at"]
    methods = [c[0] for c in fake_tg[-2:]]
    assert methods == ["answerCallbackQuery", "editMessageText"]
    assert "Đã xác nhận: <b>Sự cố</b>" in fake_tg[-1][2]["text"] and "reply_markup" not in fake_tg[-1][2]
    poller.handle({"update_id": 2, "callback_query": {"id": "cq2", "data": "ack:99999:su_co", "from": {}}}, "tok")
    assert fake_tg[-1][0] == "answerCallbackQuery" and "không còn" in fake_tg[-1][2]["text"]
    poller.handle({"update_id": 3, "message": {"text": "/start", "chat": {"id": 777}}}, "tok")
    assert fake_tg[-1][0] == "sendMessage" and fake_tg[-1][2]["chat_id"] == 777 and "<code>777</code>" in fake_tg[-1][2]["text"]
    assert database.get_setting("telegram_chat_id") == "555"            # khong tu dong doi chat id


def test_xac_nhan_tren_web_sua_tin_telegram(fake_tg, env):
    uid = env.admin["id"]
    ev = notify.notify("rpo", "RPO ĐỎ", "quá hạn", "err", uid)
    s = login(env)
    r = s.post(f"{env.url}/api/ui/events/{ev['id']}/ack", json={"verdict": "binh_thuong"}).json()["event"]
    assert r["ack"] == "binh_thuong" and r["telegram"] is True
    assert fake_tg[-1][0] == "editMessageText" and fake_tg[-1][2]["message_id"] == 101
    assert "Đã xác nhận: <b>Bình thường</b> (admin" in fake_tg[-1][2]["text"]


def test_su_kien_tu_job(env):
    uid = env.admin["id"]
    ev = notify.job_finished({"job_type": "backup", "status": "completed", "message": "Sao lưu v2 xong: 10 file"}, "PC", uid)
    assert (ev["kind"], ev["level"], ev["title"]) == ("backup", "ok", "Sao lưu xong · PC")
    ev = notify.job_finished({"job_type": "backup", "status": "failed", "message": "Lỗi: BẤT THƯỜNG - đã dừng"}, "PC", uid)
    assert ev["kind"] == "anomaly" and ev["level"] == "err" and "CỔNG CHẶN" in ev["title"]
    ev = notify.job_finished({"job_type": "backup", "status": "failed", "message": "Lỗi: mất kết nối"}, None, uid)
    assert ev["kind"] == "backup" and ev["level"] == "err" and ev["title"] == "Sao lưu THẤT BẠI"
    assert notify.job_finished({"job_type": "backup", "status": "cancelled", "message": ""}, "PC", uid) is None
    ev = notify.job_finished({"job_type": "verify", "status": "failed", "message": "1/5 khớp"}, "PC", uid)
    assert ev["kind"] == "verify" and ev["level"] == "err"
    ev = notify.job_finished({"job_type": "restore", "status": "completed", "message": "ok"}, "PC", uid)
    assert ev["kind"] == "restore" and ev["level"] == "ok"


def test_webhook_notify_tu_cli(env):
    uid, tok = env.admin["id"], env.admin["token"]
    rep = {"type": "verify", "result": "OK", "snapshot": "ab12" * 16, "snapshot_time": "2026-11-14T02:00:00", "host": "PC",
           "checked": 30, "ok": 30, "failed": [], "bytes": 52_428_800, "seconds": 3.4}
    r = requests.post(f"{env.url}/api/notify?token={tok}", json=rep)
    assert r.status_code == 200
    ev = database.get_event(r.json()["event_id"])
    assert ev["kind"] == "verify" and ev["level"] == "ok" and "30/30 file khớp SHA-256, 50,0 MB" in ev["message"]
    bad = dict(rep, result="LỖI", ok=28, failed=[{"path": "a/b.txt", "error": "SHA-256 không khớp"}])
    ev = database.get_event(requests.post(f"{env.url}/api/notify", json=bad, headers={"X-Auth-Token": tok}).json()["event_id"])
    assert ev["level"] == "err" and "a/b.txt" in ev["message"]
    an = {"type": "anomaly", "alarm": True, "reasons": ["file mồi bị sửa/xoá: ~bks_canary.txt"], "files": 500, "changed": 400,
          "added": 3, "removed": 2, "suspicious": 390}
    ev = database.get_event(requests.post(f"{env.url}/api/notify?token={tok}", json=an).json()["event_id"])
    assert ev["kind"] == "anomaly" and ev["level"] == "err" and "file mồi" in ev["message"] and "390" in ev["message"]
    sql = {"type": "verify_sql", "result": "OK", "database": "ShopDB", "restored_as": "ShopDB_kiemtra", "checkdb_exit": 0, "seconds": 12.5}
    ev = database.get_event(requests.post(f"{env.url}/api/notify?token={tok}", json=sql).json()["event_id"])
    assert ev["title"].startswith("Khôi phục thử CSDL: OK") and "ShopDB_kiemtra" in ev["message"]
    assert requests.post(f"{env.url}/api/notify?token=sai", json=rep).status_code == 401
    assert requests.post(f"{env.url}/api/notify?token={tok}", data="x").status_code == 400
    assert database.count_open_alerts(uid) == 2


def test_cai_dat_telegram_tren_web(fake_tg, env):
    database.set_setting("telegram_token", None)
    database.set_setting("telegram_chat_id", None)
    s = login(env)
    st = s.get(f"{env.url}/api/ui/settings/telegram").json()
    assert st["configured"] is False and st["has_token"] is False
    assert s.post(f"{env.url}/api/ui/settings/telegram", json={"token": "abc"}).status_code == 400
    assert s.post(f"{env.url}/api/ui/settings/telegram", json={"chat_id": "x1"}).status_code == 400
    assert s.post(f"{env.url}/api/ui/settings/telegram/test").status_code == 400          # chua cau hinh
    st = s.post(f"{env.url}/api/ui/settings/telegram",
                json={"token": "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "chat_id": "-100123", "notify_ok": False}).json()
    assert st["configured"] and st["token_masked"].startswith("123456") and st["token_masked"].endswith("AAAA")
    assert st["chat_id"] == "-100123" and st["notify_ok"] is False and st["enabled"] is True
    r = s.post(f"{env.url}/api/ui/settings/telegram/test").json()
    assert r["ok"] and r["event"]["telegram"] and fake_tg[-1][0] == "sendMessage" and fake_tg[-1][2]["chat_id"] == "-100123"
    # user thuong khong duoc dong vao cai dat Telegram
    database.create_user("duy", "mat-khau-123", "user")
    u = login(env, "duy", "mat-khau-123")
    assert u.get(f"{env.url}/api/ui/settings/telegram").status_code == 403


def test_rpo_monitor_bao_khi_doi_mau(fake_tg, env):
    uid = env.admin["id"]
    mon = monitor.RpoMonitor(notify.notify, interval=9999)
    mon.tick()                                                           # chua co ban nao -> do
    evs = database.list_events(uid, 5)
    assert len(evs) == 1 and evs[0]["kind"] == "rpo" and evs[0]["level"] == "err" and "RPO ĐỎ" in evs[0]["title"]
    mon.tick()                                                           # khong doi -> khong bao lai
    assert len(database.list_events(uid, 5)) == 1
    v2_backup(uid, "PC", hours_ago=1)
    red_id = database.list_events(uid, 1)[0]["id"]
    mon.tick()                                                           # tro lai xanh -> bao ok, khong nut
    evs = database.list_events(uid, 5)
    assert evs[0]["level"] == "ok" and "trở lại xanh" in evs[0]["title"]
    assert fake_tg[-1][2]["reply_markup"] is None
    assert database.get_setting(f"rpo_state_{uid}") == "xanh"
    red = database.get_event(red_id)                                     # canh bao do cu tu dong dong
    assert red["ack"] == "binh_thuong" and "tự hết" in red["ack_by"] and database.count_open_alerts(uid) == 0
