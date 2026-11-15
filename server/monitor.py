"""
Tuan 4 (B) - so lieu cho trang tong quan: RPO xanh/vang/do, ti le khu trung lap, tinh trang kho, may va snapshot.
Tuan 6 (B) - RpoMonitor: thread nen, 5 phut mot lan; RPO doi mau -> ghi su kien + gui Telegram.

RPO (Recovery Point Objective) o day = neu mat du lieu BAY GIO thi mat toi da bao lau du lieu
= tuoi cua ban sao luu THANH CONG gan nhat. Muc tieu: config.RPO_HOURS (mac dinh 24 gio).
  xanh : tuoi <= muc tieu
  vang : muc tieu < tuoi <= 2 x muc tieu, hoac lan sao luu gan nhat THAT BAI (du ban truoc van trong muc tieu)
  do   : tuoi > 2 x muc tieu, hoac chua co ban nao
"""
import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime

import requests

from shared import config, database
from shared.text import vn_num

log = logging.getLogger("monitor")
KHO_TTL = 20
_kho_cache = {"at": 0.0, "value": None, "key": None}


def invalidate_kho():
    """Goi sau khi agent bao sao luu xong: lan doc ke tiep lay so lieu moi cua kho ngay."""
    _kho_cache["at"] = 0.0


def _parse(iso):
    try:
        d = datetime.fromisoformat(str(iso))
        return d if d.tzinfo else d.astimezone()
    except (TypeError, ValueError):
        return None


def _hours_text(h):
    if h < 1:
        return f"{int(round(h * 60))} phút"
    if h < 48:
        return f"{vn_num(h, 0 if h >= 10 else 1)} giờ"
    return f"{vn_num(h / 24, 1)} ngày"


def rpo_status(last_ok, now=None, target_hours=None, last_failed=False):
    """Tra ve {"status": "xanh"|"vang"|"do", "age_hours", "target_hours", "last_ok", "message"}."""
    target = float(config.RPO_HOURS if target_hours is None else target_hours)
    now = now or datetime.now().astimezone()
    t = _parse(last_ok)
    if t is None:
        return {"status": "do", "age_hours": None, "target_hours": target, "last_ok": None,
                "message": "Chưa có bản sao lưu thành công nào"}
    age = max(0.0, (now - t).total_seconds() / 3600)
    if age > 2 * target:
        st, msg = "do", f"Bản gần nhất cách đây {_hours_text(age)}, quá hạn mục tiêu {_hours_text(target)}"
    elif age > target:
        st, msg = "vang", f"Bản gần nhất cách đây {_hours_text(age)}, đã trễ mục tiêu {_hours_text(target)}"
    elif last_failed:
        st, msg = "vang", f"Lần sao lưu gần nhất thất bại; bản thành công cuối cách đây {_hours_text(age)}"
    else:
        st, msg = "xanh", f"Bản gần nhất cách đây {_hours_text(age)}, trong mục tiêu {_hours_text(target)}"
    return {"status": st, "age_hours": round(age, 2), "target_hours": target,
            "last_ok": t.isoformat(timespec="seconds"), "message": msg}


# ---------------------------------------------------------------- khu trung lap
def _json(v, default=None):
    try:
        return json.loads(v) if v else (default if default is not None else {})
    except (TypeError, ValueError):
        return default if default is not None else {}


def _stats(b):
    return _json(b.get("stats"))


def dedup(backups):
    """Tong du lieu logic cua moi snapshot v2 / tong byte da gui len kho. Vd 3 ban cua 500 MB chi gui 580 MB -> 2,6x."""
    v2 = [b for b in backups if b.get("status") == "completed" and _stats(b).get("engine") == "v2"]
    logical = sum(int(_stats(b).get("bytes") or 0) for b in v2)
    uploaded = sum(int(_stats(b).get("bytes_uploaded") or b.get("size") or 0) for b in v2)
    return {"snapshots": len(v2), "logical": logical, "uploaded": uploaded, "saved": max(0, logical - uploaded),
            "ratio": round(logical / uploaded, 2) if uploaded else None}


# ---------------------------------------------------------------- kho
def _dir_stats(root):
    from core.repo_local import LocalRepo
    repo = LocalRepo(root)
    total = {"packs": 0, "snapshots": 0}
    for name in total:
        for dp, _, files in os.walk(os.path.join(root, name)):
            for f in files:
                try:
                    total[name] += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
    try:
        du = shutil.disk_usage(root)
        disk = {"total": du.total, "free": du.free}
    except OSError:
        disk = None
    return {"packs": len(repo.list_packs()), "snapshots": len(repo.list_snapshots()), "keys": len(repo.list_keys()),
            "bytes_on_disk": total["packs"] + total["snapshots"], "disk": disk, "initialized": repo.exists(),
            "reachable": True}


def kho_stats(force=False):
    """Tinh trang kho v2: doc thu muc (KHO_DIR) hoac goi GET /stats (KHO_URL). Cache 60 giay. None = khong cau hinh."""
    key = (config.KHO_DIR, config.KHO_URL)
    if not force and _kho_cache["key"] == key and time.monotonic() - _kho_cache["at"] < KHO_TTL:
        return _kho_cache["value"]
    v = None
    if config.KHO_DIR:
        if os.path.isdir(config.KHO_DIR):
            v = {**_dir_stats(config.KHO_DIR), "source": "dir", "where": config.KHO_DIR}
        else:
            v = {"source": "dir", "where": config.KHO_DIR, "reachable": False, "error": "Thư mục không tồn tại"}
    elif config.KHO_URL:
        url = config.KHO_URL.rstrip("/")
        try:
            r = requests.get(url + "/stats", timeout=2,
                             cert=(config.KHO_CERT, config.KHO_KEY) if config.KHO_CERT else None,
                             verify=config.KHO_CA or True)
            d = r.json()
            v = {"packs": d.get("packs"), "snapshots": d.get("snapshots"), "keys": d.get("keys"),
                 "bytes_on_disk": d.get("bytes_on_disk"), "disk": d.get("disk"), "initialized": d.get("has_config"),
                 "rejected": d.get("rejected"), "requests": d.get("requests"), "version": d.get("version"),
                 "started": d.get("started"), "last_write": d.get("last_write"), "source": "url", "where": url,
                 "reachable": True}
        except (requests.RequestException, ValueError) as e:
            v = {"source": "url", "where": url, "reachable": False, "error": str(e)[:200]}
    _kho_cache.update(at=time.monotonic(), value=v, key=key)
    return v


# ---------------------------------------------------------------- tong quan v2
def _online(agent):
    t = _parse(agent.get("last_seen"))
    return bool(t) and (datetime.now(t.tzinfo) - t).total_seconds() < config.AGENT_ONLINE_SECONDS


def snapshot_out(b):
    st, ss = _stats(b), _json(b.get("snapshot_summary"))
    return {"backup_id": b["id"], "snapshot": b["filename"][3:] if b["filename"].startswith("v2-") else None,
            "created_at": b.get("created_at"), "host": b.get("host"), "files": st.get("files", ss.get("total_files")),
            "bytes": st.get("bytes", ss.get("total_size")), "uploaded": st.get("bytes_uploaded", b.get("size")),
            "chunks": st.get("chunks"), "chunks_new": st.get("chunks_new"), "seconds": st.get("seconds"),
            "components": ss.get("components") or [], "anomaly": bool(st.get("anomaly_alarm")), "status": b.get("status")}


def overview_v2(user_id):
    backups = database.list_backups(user_id, 300)
    completed = sorted((b for b in backups if b.get("status") == "completed"),
                       key=lambda b: str(b.get("created_at") or ""), reverse=True)        # moi nhat truoc
    last_job = (database.list_jobs(user_id, 1) or [None])[0]
    last_failed = bool(last_job and last_job["job_type"] == "backup" and last_job["status"] == "failed")
    rpo = rpo_status(completed[0]["created_at"] if completed else None, last_failed=last_failed)

    by_host = {}
    for b in completed:                                   # list_backups: moi nhat truoc
        by_host.setdefault(b.get("host") or "?", b)
    machines, seen = [], set()
    for a in database.list_agents(user_id):
        b = by_host.get(a["hostname"])
        machines.append({"hostname": a["hostname"], "online": _online(a), "last_seen": a.get("last_seen"),
                         "ip": a.get("ip"), "last_backup": b["created_at"] if b else None,
                         "rpo": rpo_status(b["created_at"] if b else None)})
        seen.add(a["hostname"])
    for host, b in by_host.items():
        if host not in seen:
            machines.append({"hostname": host, "online": False, "last_seen": None, "ip": None,
                             "last_backup": b["created_at"], "rpo": rpo_status(b["created_at"])})
    snapshots = [snapshot_out(b) for b in completed if _stats(b).get("engine") == "v2"][:8]
    return {"rpo": rpo, "machines": machines, "snapshots": snapshots, "dedup": dedup(backups), "kho": kho_stats()}


# ---------------------------------------------------------------- theo doi RPO (tuan 6)
class RpoMonitor(threading.Thread):
    """Moi `interval` giay: RPO cua tung user doi mau -> ghi su kien (+ Telegram qua `notifier`)."""

    def __init__(self, notifier, interval=300):
        super().__init__(name="rpo-monitor", daemon=True)
        self.notifier, self.interval = notifier, interval
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:       # noqa: BLE001 - thread nen khong duoc chet
                log.exception("RpoMonitor lỗi")
            self._stop.wait(self.interval)

    def tick(self):
        for u in database.list_users():
            check_user(u, self.notifier)


def check_user(u, notifier):
    """RPO cua mot user doi mau so voi lan truoc -> su kien (+ Telegram). Tro lai xanh: tu dong dong canh bao RPO cu."""
    rpo = overview_v2(u["id"])["rpo"]
    key = f"rpo_state_{u['id']}"
    prev = database.get_setting(key)
    if prev == rpo["status"]:
        return rpo["status"]
    database.set_setting(key, rpo["status"])
    if rpo["status"] == "do":
        notifier("rpo", f"RPO ĐỎ: {u['username']} quá hạn sao lưu", rpo["message"], "err", u["id"], data=rpo)
    elif rpo["status"] == "vang":
        notifier("rpo", f"RPO VÀNG: {u['username']} sắp quá hạn sao lưu", rpo["message"], "warn", u["id"], data=rpo)
    elif prev in ("vang", "do"):
        database.auto_ack_rpo(u["id"])
        notifier("rpo", f"RPO trở lại xanh: {u['username']}", rpo["message"], "ok", u["id"], data=rpo, buttons=False)
    return rpo["status"]


def check_user_id(user_id, notifier):
    """Dung sau khi agent bao sao luu xong (thread nen) de RPO doi mau ngay, khong cho chu ky 5 phut."""
    try:
        u = database.get_user_by_id(user_id)
        if u:
            check_user(u, notifier)
    except Exception:       # noqa: BLE001
        log.exception("check_user_id lỗi")


_monitor = None


def start_rpo_monitor(notifier, interval=300):
    global _monitor
    if _monitor is None or not _monitor.is_alive():
        _monitor = RpoMonitor(notifier, interval)
        _monitor.start()
    return _monitor
