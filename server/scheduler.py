"""
Lap lich backup tu dong (chay tren may server).

- CRUD bang `schedules`.
- start_scheduler(): luong nen, moi 30 s tao job backup cho lich den han.
- Kieu lich: hourly (moi N gio) / daily (gio co dinh) / weekly (thu + gio, Thu Hai = 0).
- Lich den han ma job truoc cua chinh lich do van dang chay -> bo qua lan nay (khong chong job).
"""
import json
import logging
import threading
import time as _time
from datetime import datetime, timedelta

from shared import database

log = logging.getLogger("server.scheduler")
TYPES = ("hourly", "daily", "weekly")


def _parse_hhmm(value):
    try:
        hh, mm = str(value or "02:00").split(":")
        hh, mm = int(hh), int(mm)
        if 0 <= hh < 24 and 0 <= mm < 60:
            return hh, mm
    except ValueError:
        pass
    return 2, 0


def compute_next_run(schedule_type, interval_hours, time_of_day, day_of_week, frm=None):
    now = frm or datetime.now()
    st = (schedule_type or "daily").lower()
    if st == "hourly":
        return now + timedelta(hours=max(1, int(interval_hours or 1)))
    hh, mm = _parse_hhmm(time_of_day)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if st == "weekly":
        target += timedelta(days=(int(day_of_week or 0) % 7 - now.weekday()) % 7)
        return target if target > now else target + timedelta(days=7)
    return target if target > now else target + timedelta(days=1)


def create_schedule(user_id, name, schedule_type, interval_hours, time_of_day, day_of_week,
                    backup_paths, components=None):
    nxt = compute_next_run(schedule_type, interval_hours, time_of_day, day_of_week).isoformat(timespec="seconds")
    with database.get_db() as conn:
        cur = conn.execute(
            """INSERT INTO schedules (user_id, name, schedule_type, interval_hours, time_of_day, day_of_week,
                                      backup_paths, components, enabled, next_run, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (user_id, name, schedule_type, interval_hours, time_of_day, day_of_week,
             json.dumps(backup_paths, ensure_ascii=False) if backup_paths else None,
             json.dumps(components) if components else None, nxt, database.now_iso()))
        return cur.lastrowid


def list_schedules(user_id=None):
    with database.get_db() as conn:
        if user_id is None:
            rows = conn.execute("SELECT * FROM schedules ORDER BY id DESC")
        else:
            rows = conn.execute("SELECT * FROM schedules WHERE user_id=? ORDER BY id DESC", (user_id,))
        return [dict(r) for r in rows]


def get_schedule(sched_id):
    with database.get_db() as conn:
        row = conn.execute("SELECT * FROM schedules WHERE id=?", (sched_id,)).fetchone()
        return dict(row) if row else None


def toggle_schedule(sched_id):
    s = get_schedule(sched_id)
    if not s:
        return None
    new = 0 if s["enabled"] else 1
    with database.get_db() as conn:
        if new:     # bat lai -> tinh moc ke tiep tu bay gio, khong chay bu
            nxt = compute_next_run(s["schedule_type"], s["interval_hours"], s["time_of_day"],
                                   s["day_of_week"]).isoformat(timespec="seconds")
            conn.execute("UPDATE schedules SET enabled=1, next_run=? WHERE id=?", (nxt, sched_id))
        else:
            conn.execute("UPDATE schedules SET enabled=0 WHERE id=?", (sched_id,))
    return bool(new)


def delete_schedule(sched_id):
    with database.get_db() as conn:
        conn.execute("DELETE FROM schedules WHERE id=?", (sched_id,))


def job_params(s):
    def _load(v):
        try:
            return json.loads(v) if v else None
        except ValueError:
            return None
    return {"paths": _load(s.get("backup_paths")), "components": _load(s.get("components")),
            "schedule_id": s["id"]}


def _mark_run(s, now):
    nxt = compute_next_run(s["schedule_type"], s["interval_hours"], s["time_of_day"], s["day_of_week"], frm=now)
    with database.get_db() as conn:
        conn.execute("UPDATE schedules SET last_run=?, next_run=? WHERE id=?",
                     (now.isoformat(timespec="seconds"), nxt.isoformat(timespec="seconds"), s["id"]))


def check_due(now=None):
    """Quet 1 luot. Tra ve so job da tao."""
    now = now or datetime.now()
    created = 0
    for s in list_schedules():
        if not s.get("enabled"):
            continue
        try:
            due = now >= datetime.fromisoformat(s["next_run"]).replace(tzinfo=None) if s.get("next_run") else True
        except ValueError:
            due = True
        if not due:
            continue
        active = database.active_job(s["user_id"])
        if active and json.loads(active.get("params") or "{}").get("schedule_id") == s["id"]:
            log.info("Lịch '%s' đến hạn nhưng lần trước chưa xong - bỏ qua lần này", s["name"])
        else:
            database.create_job(s["user_id"], "backup", params=job_params(s))
            created += 1
            log.info("Tạo job sao lưu theo lịch '%s' (user %s)", s["name"], s["user_id"])
        _mark_run(s, now)
    return created


_started = False
_lock = threading.Lock()


def start_scheduler(interval=30):
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def loop():
        while True:
            try:
                check_due()
            except Exception:       # noqa: BLE001
                log.exception("Lỗi khi quét lịch")
            _time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="backup-scheduler").start()
    log.info("Scheduler đã chạy (chu kỳ %ss)", interval)
