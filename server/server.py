"""
Server (trong do an: PC o nha) - web dieu khien + REST API cho agent + kho file backup.

Laptop chi can mo trinh duyet toi http://<IP Tailscale cua PC>:5000 de dieu khien.

  /                     giao dien web (SPA, file tinh trong server/static, khong CDN)
  /api/ui/*             API cho giao dien: phien dang nhap (cookie) + header X-CSRF-Token
  /api/jobs/*, /api/storage/*   API cho agent: header X-Auth-Token
  Kho chi cho THEM: khong co lenh xoa file backup, khong ghi de.

Chay:  python -m server            (hoac server\\start_server.bat)
"""
import hashlib
import hmac
import json
import logging
import os
import platform
import re
import secrets
import shutil
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from flask import Flask, g, jsonify, render_template, request, send_file, session  # noqa: E402

from shared import config, database  # noqa: E402
from shared.log import setup_logging  # noqa: E402
from server import scheduler  # noqa: E402

log = logging.getLogger("server")

FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}\.bkup$")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
JOB_STATUSES = {"running", "completed", "failed", "cancelled"}
TERMINAL = {"completed", "failed", "cancelled"}
STREAM_BUF = 1024 * 1024


class ApiError(Exception):
    def __init__(self, status, message, code=None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code or "error"


# ===================================================================== tien ich

def _secret_key():
    if config.SECRET_KEY:
        return config.SECRET_KEY
    path = os.path.join(config.INSTANCE_DIR, "secret_key")
    try:
        with open(path, encoding="ascii") as f:
            key = f.read().strip()
            if key:
                return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    os.makedirs(config.INSTANCE_DIR, exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write(key)
    return key


def ts(v):
    """Chuan hoa moc thoi gian ve ISO 8601 co mui gio (du lieu cu cua v1 lan lon UTC/gio may)."""
    if not v:
        return None
    s = str(v)
    try:
        if "T" not in s:      # CURRENT_TIMESTAMP cua SQLite = UTC
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat()
        d = datetime.fromisoformat(s)
        return (d if d.tzinfo else d.astimezone()).isoformat(timespec="seconds")
    except ValueError:
        return s


def _loads(v, default=None):
    try:
        return json.loads(v) if v else default
    except (TypeError, ValueError):
        return default


def job_out(j):
    p = _loads(j.get("params"), {}) or {}
    return {"id": j["id"], "type": j["job_type"], "status": j["status"], "progress": j.get("progress") or 0,
            "message": j.get("message") or "", "backup_id": j.get("backup_id"),
            "created_at": ts(j.get("created_at")), "started_at": ts(j.get("started_at")),
            "completed_at": ts(j.get("completed_at")), "updated_at": ts(j.get("updated_at")),
            "cancel_requested": bool(j.get("cancel_requested")),
            "params": {k: p[k] for k in ("components", "paths", "filename", "dry_run", "delete_extra",
                                         "target_dir", "restore_system", "schedule_id") if k in p}}


def backup_out(b):
    ss = _loads(b.get("snapshot_summary"), {}) or {}
    return {"id": b["id"], "filename": b["filename"], "size": b.get("size") or 0, "status": b["status"],
            "created_at": ts(b.get("created_at")), "backup_type": b.get("backup_type"),
            "components": ss.get("components") or [], "files": ss.get("total_files"),
            "source_bytes": ss.get("total_size"), "paths": _loads(b.get("paths"), []) or [],
            "stats": _loads(b.get("stats"), {}) or {}}


def schedule_out(s):
    p = scheduler.job_params(s)
    return {"id": s["id"], "name": s["name"], "schedule_type": s["schedule_type"],
            "interval_hours": s.get("interval_hours"), "time_of_day": s.get("time_of_day"),
            "day_of_week": s.get("day_of_week"), "enabled": bool(s.get("enabled")),
            "paths": p["paths"] or [], "components": p["components"] or list(config.BACKUP_COMPONENTS),
            "last_run": ts(s.get("last_run")), "next_run": ts(s.get("next_run"))}


def agent_out(a):
    online = False
    try:
        seen = datetime.fromisoformat(a["last_seen"])
        online = (datetime.now(seen.tzinfo) - seen).total_seconds() < config.AGENT_ONLINE_SECONDS
    except (TypeError, ValueError, KeyError):
        pass
    return {"hostname": a["hostname"], "ip": a.get("ip"), "version": a.get("version"),
            "platform": a.get("platform"), "last_seen": ts(a.get("last_seen")), "online": online,
            "current_job": a.get("current_job")}


def user_out(u, with_token=False):
    out = {"id": u["id"], "username": u["username"], "role": u["role"], "created_at": ts(u.get("created_at"))}
    if with_token:
        out["token"] = u["token"]
    return out


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "Dữ liệu gửi lên không hợp lệ (cần JSON)", "bad_json")
    return data


def _components(value):
    comps = [c for c in (value or []) if c in config.BACKUP_COMPONENTS]
    if not comps:
        raise ApiError(400, "Chọn ít nhất một thành phần", "no_components")
    return comps


def _paths(value):
    if value in (None, "", []):
        return None
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or len(value) > 20 or not all(isinstance(p, str) and 0 < len(p) < 1024
                                                                   for p in value):
        raise ApiError(400, "Danh sách thư mục không hợp lệ", "bad_paths")
    return [p.strip() for p in value]


def _reject_duplicate(user_id, job_type, params):
    """Bam 2 lan / gui lai cung 1 yeu cau -> khong tao them job giong het dang cho/chay."""
    with database.get_db() as conn:
        rows = conn.execute("SELECT params FROM jobs WHERE user_id=? AND job_type=? AND status IN ('pending','running')",
                            (user_id, job_type)).fetchall()
    for r in rows:
        if (_loads(r["params"], {}) or {}) == params:
            raise ApiError(409, "Tác vụ giống hệt đang chờ hoặc đang chạy", "duplicate")


def user_dir(user_id):
    d = os.path.join(config.STORAGE_DIR, f"user_{int(user_id)}")
    os.makedirs(d, exist_ok=True)
    return d


class LoginLimiter:
    """Sai mat khau 5 lan -> khoa IP 60 giay."""

    def __init__(self, max_fails=5, lock_seconds=60):
        self.max_fails, self.lock_seconds = max_fails, lock_seconds
        self.state, self.lock = {}, threading.Lock()

    def blocked(self, ip):
        with self.lock:
            fails, until = self.state.get(ip, (0, 0))
            return max(0, int(until - time.time()))

    def fail(self, ip):
        with self.lock:
            fails, _ = self.state.get(ip, (0, 0))
            fails += 1
            until = time.time() + self.lock_seconds if fails >= self.max_fails else 0
            self.state[ip] = (0 if until else fails, until)

    def ok(self, ip):
        with self.lock:
            self.state.pop(ip, None)


# ===================================================================== app

def create_app(start_scheduler=False):
    config.ensure_dirs()
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(
        SECRET_KEY=_secret_key(), SESSION_COOKIE_NAME="bks_session", SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=config.COOKIE_SECURE,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=None,
        SEND_FILE_MAX_AGE_DEFAULT=0)
    app.json.ensure_ascii = False
    limiter = LoginLimiter()

    created_pw = database.init_db()
    if created_pw:
        pw_file = os.path.join(config.INSTANCE_DIR, "admin_password.txt")
        with open(pw_file, "w", encoding="utf-8") as f:
            f.write(f"admin / {created_pw}\n")
        log.warning("=" * 60)
        log.warning("Tạo tài khoản quản trị lần đầu: admin / %s", created_pw)
        log.warning("(đã lưu ở %s - đổi mật khẩu rồi xoá file này)", pw_file)
        log.warning("=" * 60)

    # ---------------------------------------------------------------- loi + header
    @app.errorhandler(ApiError)
    def _api_error(e):
        return jsonify({"error": e.code, "message": e.message}), e.status

    @app.errorhandler(404)
    def _not_found(e):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not_found", "message": "Không tìm thấy"}), 404
        return e

    @app.errorhandler(405)
    def _not_allowed(e):
        return jsonify({"error": "method_not_allowed", "message": "Phương thức không được phép"}), 405

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    # ---------------------------------------------------------------- xac thuc UI
    def ui_auth(admin=False):
        def deco(f):
            @wraps(f)
            def wrapper(*a, **kw):
                uid = session.get("uid")
                user = database.get_user_by_id(uid) if uid else None
                if not user or session.get("pw") != user["password"][-16:]:
                    session.clear()
                    raise ApiError(401, "Phiên đăng nhập đã hết, hãy đăng nhập lại", "unauthorized")
                if request.method in WRITE_METHODS:
                    sent = request.headers.get("X-CSRF-Token", "")
                    if not hmac.compare_digest(sent, session.get("csrf", "")):
                        raise ApiError(403, "Thiếu hoặc sai mã CSRF, hãy tải lại trang", "csrf")
                if admin and user["role"] != "admin":
                    raise ApiError(403, "Chỉ quản trị viên được làm việc này", "forbidden")
                g.user = user
                return f(*a, **kw)
            return wrapper
        return deco

    def agent_auth(f):
        @wraps(f)
        def wrapper(*a, **kw):
            user = database.get_user_by_token(request.headers.get("X-Auth-Token", ""))
            if not user:
                raise ApiError(401, "Token không hợp lệ", "unauthorized")
            g.agent_user = user
            return f(*a, **kw)
        return wrapper

    def _touch_agent(current_job=None):
        h = request.headers
        port = h.get("X-Agent-Browser-Port", "")
        database.touch_agent(g.agent_user["id"], (h.get("X-Agent-Host") or request.remote_addr)[:100],
                             request.remote_addr, h.get("X-Agent-Version", "")[:20] or None,
                             h.get("X-Agent-Platform", "")[:120] or None,
                             int(port) if port.isdigit() else None, current_job)

    # ---------------------------------------------------------------- trang
    @app.get("/")
    def index():
        return render_template("app.html", version=config.VERSION)

    @app.get("/api/ping")
    def api_ping():
        return jsonify({"ok": True, "time": database.now_iso(), "version": config.VERSION})

    # ---------------------------------------------------------------- phien
    def _session_payload(user):
        return {"user": user_out(user), "csrf": session["csrf"], "version": config.VERSION,
                "components": config.BACKUP_COMPONENTS, "default_paths": config.DEFAULT_BACKUP_PATHS}

    @app.get("/api/ui/session")
    def ui_session():
        uid = session.get("uid")
        user = database.get_user_by_id(uid) if uid else None
        if not user or session.get("pw") != user["password"][-16:]:
            raise ApiError(401, "Chưa đăng nhập", "unauthorized")
        return jsonify(_session_payload(user))

    @app.post("/api/ui/login")
    def ui_login():
        ip = request.remote_addr or "?"
        wait = limiter.blocked(ip)
        if wait:
            raise ApiError(429, f"Sai quá nhiều lần, thử lại sau {wait} giây", "rate_limited")
        data = _body()
        user = database.authenticate(str(data.get("username", "")).strip(), str(data.get("password", "")))
        if not user:
            limiter.fail(ip)
            raise ApiError(401, "Sai tên đăng nhập hoặc mật khẩu", "bad_credentials")
        limiter.ok(ip)
        user = database.get_user_by_id(user["id"])
        session.clear()
        session.permanent = True
        session.update(uid=user["id"], csrf=secrets.token_urlsafe(24), pw=user["password"][-16:])
        log.info("Đăng nhập: %s từ %s", user["username"], ip)
        return jsonify(_session_payload(user))

    @app.post("/api/ui/logout")
    def ui_logout():
        session.clear()
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- tong quan
    @app.get("/api/ui/overview")
    @ui_auth()
    def ui_overview():
        uid = g.user["id"]
        st = database.backup_stats(uid)
        active = database.active_job(uid)
        scheds = [s for s in scheduler.list_schedules(uid) if s["enabled"] and s.get("next_run")]
        nxt = min(scheds, key=lambda s: s["next_run"]) if scheds else None
        try:
            du = shutil.disk_usage(config.STORAGE_DIR)
            disk = {"total": du.total, "free": du.free}
        except OSError:
            disk = None
        return jsonify({
            "stats": {"total_backups": st["total_backups"], "total_size": st["total_size"],
                      "last_backup": backup_out(st["last_backup"]) if st["last_backup"] else None},
            "active_job": job_out(active) if active else None,
            "agents": [agent_out(a) for a in database.list_agents(uid)],
            "jobs": [job_out(j) for j in database.list_jobs(uid, 8)],
            "backups": [backup_out(b) for b in database.list_backups(uid, 5)],
            "next_schedule": schedule_out(nxt) if nxt else None,
            "disk": disk, "server_time": database.now_iso(),
        })

    # ---------------------------------------------------------------- backup / restore
    @app.get("/api/ui/backups")
    @ui_auth()
    def ui_backups():
        return jsonify({"backups": [backup_out(b) for b in database.list_backups(g.user["id"])]})

    @app.post("/api/ui/backups")
    @ui_auth()
    def ui_backup_create():
        data = _body()
        comps = _components(data.get("components"))
        paths = _paths(data.get("paths")) if "files" in comps else None
        params = {"components": comps, "paths": paths}
        _reject_duplicate(g.user["id"], "backup", params)
        jid = database.create_job(g.user["id"], "backup", params)
        return jsonify({"job": job_out(database.get_job(jid))}), 201

    @app.post("/api/ui/backups/<int:backup_id>/restore")
    @ui_auth()
    def ui_restore(backup_id):
        b = database.get_backup(backup_id)
        if not b or b["user_id"] != g.user["id"]:
            raise ApiError(404, "Không tìm thấy bản sao lưu", "not_found")
        if b["status"] != "completed":
            raise ApiError(409, "Bản sao lưu chưa hoàn tất", "not_completed")
        data = _body()
        target = data.get("target_dir") or None
        if target is not None and (not isinstance(target, str) or len(target) > 1024):
            raise ApiError(400, "Thư mục đích không hợp lệ", "bad_target")
        params = {"filename": b["filename"], "dry_run": bool(data.get("dry_run")),
                  "delete_extra": bool(data.get("delete_extra")), "target_dir": target,
                  "restore_system": bool(data.get("restore_system", True))}
        _reject_duplicate(g.user["id"], "restore", params)
        jid = database.create_job(g.user["id"], "restore", params, backup_id=backup_id)
        return jsonify({"job": job_out(database.get_job(jid))}), 201

    @app.get("/api/ui/jobs")
    @ui_auth()
    def ui_jobs():
        limit = min(max(int(request.args.get("limit", 30)), 1), 200)
        return jsonify({"jobs": [job_out(j) for j in database.list_jobs(g.user["id"], limit)]})

    @app.post("/api/ui/jobs/<int:job_id>/cancel")
    @ui_auth()
    def ui_job_cancel(job_id):
        j = database.get_job(job_id)
        if not j or j["user_id"] != g.user["id"]:
            raise ApiError(404, "Không tìm thấy tác vụ", "not_found")
        return jsonify({"job": job_out(database.cancel_job(job_id))})

    # ---------------------------------------------------------------- lich
    def _own_schedule(sid):
        s = scheduler.get_schedule(sid)
        if not s or (s["user_id"] != g.user["id"] and g.user["role"] != "admin"):
            raise ApiError(404, "Không tìm thấy lịch", "not_found")
        return s

    @app.get("/api/ui/schedules")
    @ui_auth()
    def ui_schedules():
        return jsonify({"schedules": [schedule_out(s) for s in scheduler.list_schedules(g.user["id"])]})

    @app.post("/api/ui/schedules")
    @ui_auth()
    def ui_schedule_create():
        d = _body()
        name = str(d.get("name", "")).strip()[:80]
        stype = d.get("schedule_type")
        if not name:
            raise ApiError(400, "Hãy đặt tên cho lịch", "no_name")
        if stype not in scheduler.TYPES:
            raise ApiError(400, "Kiểu lịch không hợp lệ", "bad_type")
        hours = int(d.get("interval_hours") or 24)
        tod = str(d.get("time_of_day") or "02:00")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", tod):
            raise ApiError(400, "Giờ chạy phải dạng HH:MM", "bad_time")
        dow = int(d.get("day_of_week") or 0) % 7
        comps = _components(d.get("components") or config.BACKUP_COMPONENTS)
        paths = _paths(d.get("paths")) if "files" in comps else None
        sid = scheduler.create_schedule(g.user["id"], name, stype, max(1, min(hours, 720)), tod, dow, paths, comps)
        return jsonify({"schedule": schedule_out(scheduler.get_schedule(sid))}), 201

    @app.post("/api/ui/schedules/<int:sid>/toggle")
    @ui_auth()
    def ui_schedule_toggle(sid):
        _own_schedule(sid)
        scheduler.toggle_schedule(sid)
        return jsonify({"schedule": schedule_out(scheduler.get_schedule(sid))})

    @app.post("/api/ui/schedules/<int:sid>/run")
    @ui_auth()
    def ui_schedule_run(sid):
        s = _own_schedule(sid)
        jid = database.create_job(s["user_id"], "backup", scheduler.job_params(s))
        return jsonify({"job": job_out(database.get_job(jid))}), 201

    @app.delete("/api/ui/schedules/<int:sid>")
    @ui_auth()
    def ui_schedule_delete(sid):
        _own_schedule(sid)
        scheduler.delete_schedule(sid)
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- tai khoan
    @app.get("/api/ui/me")
    @ui_auth()
    def ui_me():
        return jsonify({"user": user_out(g.user, with_token=True), "server_url_hint": request.host_url.rstrip("/")})

    @app.post("/api/ui/me/password")
    @ui_auth()
    def ui_me_password():
        d = _body()
        ok, _ = database.verify_password(str(d.get("current", "")), g.user["password"])
        if not ok:
            raise ApiError(400, "Mật khẩu hiện tại không đúng", "bad_password")
        new = str(d.get("new", ""))
        if len(new) < 8:
            raise ApiError(400, "Mật khẩu mới cần ít nhất 8 ký tự", "weak_password")
        database.update_user(g.user["id"], password=new)
        session["pw"] = database.get_user_by_id(g.user["id"])["password"][-16:]
        return jsonify({"ok": True})

    @app.post("/api/ui/me/token")
    @ui_auth()
    def ui_me_token():
        return jsonify({"token": database.rotate_token(g.user["id"])})

    @app.get("/api/ui/system")
    @ui_auth()
    def ui_system():
        try:
            du = shutil.disk_usage(config.STORAGE_DIR)
            disk = {"total": du.total, "used": du.used, "free": du.free}
        except OSError:
            disk = None
        return jsonify({"version": config.VERSION, "hostname": platform.node(), "platform": platform.platform(),
                        "storage_dir": config.STORAGE_DIR if g.user["role"] == "admin" else None,
                        "disk": disk, "server_time": database.now_iso()})

    # ---------------------------------------------------------------- quan tri user
    @app.get("/api/ui/users")
    @ui_auth(admin=True)
    def ui_users():
        return jsonify({"users": [user_out(u, with_token=True) for u in database.list_users()]})

    @app.post("/api/ui/users")
    @ui_auth(admin=True)
    def ui_user_create():
        d = _body()
        username = str(d.get("username", "")).strip()
        password = str(d.get("password", ""))
        role = d.get("role") if d.get("role") in ("admin", "user") else "user"
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
            raise ApiError(400, "Tên đăng nhập 3-32 ký tự: chữ, số, . _ -", "bad_username")
        if len(password) < 8:
            raise ApiError(400, "Mật khẩu cần ít nhất 8 ký tự", "weak_password")
        if database.get_user_by_username(username):
            raise ApiError(409, f"Tên '{username}' đã tồn tại", "exists")
        uid = database.create_user(username, password, role)
        return jsonify({"user": user_out(database.get_user_by_id(uid), with_token=True)}), 201

    @app.patch("/api/ui/users/<int:uid>")
    @ui_auth(admin=True)
    def ui_user_update(uid):
        target = database.get_user_by_id(uid)
        if not target:
            raise ApiError(404, "Không tìm thấy người dùng", "not_found")
        d = _body()
        role = d.get("role") if d.get("role") in ("admin", "user") else None
        password = str(d.get("password") or "")
        if password and len(password) < 8:
            raise ApiError(400, "Mật khẩu cần ít nhất 8 ký tự", "weak_password")
        if role == "user" and target["role"] == "admin" and database.count_admins() <= 1:
            raise ApiError(409, "Phải còn ít nhất một quản trị viên", "last_admin")
        database.update_user(uid, password=password or None, role=role)
        return jsonify({"user": user_out(database.get_user_by_id(uid), with_token=True)})

    @app.post("/api/ui/users/<int:uid>/token")
    @ui_auth(admin=True)
    def ui_user_token(uid):
        if not database.get_user_by_id(uid):
            raise ApiError(404, "Không tìm thấy người dùng", "not_found")
        return jsonify({"token": database.rotate_token(uid)})

    @app.delete("/api/ui/users/<int:uid>")
    @ui_auth(admin=True)
    def ui_user_delete(uid):
        if uid == g.user["id"]:
            raise ApiError(409, "Không thể tự xoá tài khoản đang dùng", "self")
        if not database.get_user_by_id(uid):
            raise ApiError(404, "Không tìm thấy người dùng", "not_found")
        database.delete_user(uid)       # file backup trong kho KHONG bi xoa
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- duyet thu muc may agent
    def _agent_browser(path, params=None):
        agents = [a for a in database.list_agents(g.user["id"]) if a.get("browser_port")]
        if not agents:
            raise ApiError(503, "Chưa có agent nào kết nối - hãy chạy agent trước", "no_agent")
        a = agents[0]
        hosts = [a["ip"], "127.0.0.1"] if a.get("ip") not in (None, "127.0.0.1", "::1") else ["127.0.0.1"]
        last_err = None
        for host in hosts:
            host = f"[{host}]" if ":" in host else host
            try:
                r = requests.get(f"http://{host}:{a['browser_port']}{path}", params=params,
                                 headers={"X-Auth-Token": g.user["token"]}, timeout=8)
                return jsonify(r.json()), (200 if r.ok else 502)
            except (requests.RequestException, ValueError) as e:
                last_err = e
        raise ApiError(502, f"Không kết nối được agent {a['hostname']}: {last_err}", "agent_unreachable")

    @app.get("/api/ui/fs/quick")
    @ui_auth()
    def ui_fs_quick():
        return _agent_browser("/folders/quick")

    @app.get("/api/ui/fs/list")
    @ui_auth()
    def ui_fs_list():
        return _agent_browser("/folders/list", {"path": request.args.get("path", "")})

    # ================================================================ API cho agent
    @app.get("/api/jobs/poll")
    @agent_auth
    def api_poll():
        uid = g.agent_user["id"]
        if request.args.get("startup") == "1":
            database.fail_running_jobs(uid, "Agent khởi động lại khi tác vụ đang chạy")
        job = database.claim_next_job(uid)
        _touch_agent(job["id"] if job else None)
        if not job:
            return jsonify({"job": None})
        u = g.agent_user
        job["params"] = _loads(job.get("params"), {}) or {}
        job["_user"] = {"id": u["id"], "username": u["username"], "token": u["token"],
                        "encryption_key": u["encryption_key"]}
        return jsonify({"job": job})

    def _agent_job(job_id):
        j = database.get_job(job_id)
        if not j or j["user_id"] != g.agent_user["id"]:
            raise ApiError(404, "Không tìm thấy job", "not_found")
        return j

    @app.post("/api/jobs/<int:job_id>/update")
    @agent_auth
    def api_job_update(job_id):
        j = _agent_job(job_id)
        d = request.get_json(silent=True) or {}
        upd = {}
        status = d.get("status")
        if status in JOB_STATUSES and j["status"] not in TERMINAL:
            upd["status"] = status
        if j["status"] not in TERMINAL or status in TERMINAL:
            if "progress" in d:
                upd["progress"] = max(0, min(int(d.get("progress") or 0), 100))
            if "message" in d:
                upd["message"] = str(d.get("message") or "")[:1000]
        if d.get("completed") and j["status"] not in TERMINAL:
            upd["completed_at"] = database.now_iso()
        if upd:
            database.update_job(job_id, **upd)
        _touch_agent(None if upd.get("status") in TERMINAL else job_id)
        return jsonify({"ok": True, "cancel": bool(j.get("cancel_requested"))})

    @app.post("/api/jobs/<int:job_id>/backup_done")
    @agent_auth
    def api_backup_done(job_id):
        j = _agent_job(job_id)
        if j["job_type"] != "backup":
            raise ApiError(400, "Job không phải sao lưu", "bad_job")
        d = request.get_json(silent=True) or {}
        filename = str(d.get("filename", ""))
        if not FILENAME_RE.match(filename):
            raise ApiError(400, "Tên file không hợp lệ", "bad_filename")
        path = os.path.join(user_dir(g.agent_user["id"]), filename)
        if not os.path.isfile(path) or os.path.getsize(path) != int(d.get("size") or -1):
            raise ApiError(409, "File backup trên kho không khớp báo cáo của agent", "mismatch")
        comps = d.get("components") or []
        ss = dict(d.get("snapshot_summary") or {})
        ss["components"] = comps
        is_full = set(comps) >= set(config.BACKUP_COMPONENTS)
        bid = database.create_backup_record(g.agent_user["id"], filename, d.get("paths") or [],
                                            "full" if is_full else "selected")
        database.update_backup(bid, size=os.path.getsize(path), status="completed",
                               snapshot_summary=json.dumps(ss, ensure_ascii=False),
                               stats=json.dumps(d.get("stats") or {}, ensure_ascii=False))
        database.update_job(job_id, backup_id=bid)
        return jsonify({"ok": True, "backup_id": bid})

    # ---------------------------------------------------------------- kho (chi them, khong xoa)
    @app.put("/api/storage/backups/<filename>")
    @agent_auth
    def api_storage_put(filename):
        if not FILENAME_RE.match(filename):
            raise ApiError(400, "Tên file không hợp lệ", "bad_filename")
        d = user_dir(g.agent_user["id"])
        dest = os.path.join(d, filename)
        if os.path.exists(dest):
            raise ApiError(409, "File đã tồn tại - kho không cho ghi đè", "exists")
        tmp = os.path.join(d, f".{filename}.{secrets.token_hex(4)}.part")
        h, size = hashlib.sha256(), 0
        try:
            with open(tmp, "wb") as out:
                stream = request.stream
                while True:
                    block = stream.read(STREAM_BUF)
                    if not block:
                        break
                    size += len(block)
                    if size > config.MAX_UPLOAD_BYTES:
                        raise ApiError(413, "File vượt giới hạn dung lượng", "too_large")
                    h.update(block)
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
            if request.content_length is not None and size != request.content_length:
                raise ApiError(400, "Nhận thiếu dữ liệu", "incomplete")
            try:
                os.link(tmp, dest)          # loi neu dich da co -> khong bao gio ghi de
            except FileExistsError:
                raise
            except OSError:                 # o dia khong ho tro hard link (FAT/exFAT...)
                os.rename(tmp, dest)        # Windows: van loi neu dich da co
            else:
                os.remove(tmp)
        except BaseException as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            if isinstance(e, FileExistsError):
                raise ApiError(409, "File đã tồn tại - kho không cho ghi đè", "exists") from None
            raise
        log.info("Nhận %s của %s (%s byte)", filename, g.agent_user["username"], f"{size:,}")
        return jsonify({"ok": True, "size": size, "sha256": h.hexdigest(),
                        "path": f"user_{g.agent_user['id']}/{filename}"}), 201

    @app.get("/api/storage/backups/<filename>")
    @agent_auth
    def api_storage_get(filename):
        if not FILENAME_RE.match(filename):
            raise ApiError(400, "Tên file không hợp lệ", "bad_filename")
        path = os.path.join(user_dir(g.agent_user["id"]), filename)
        if not os.path.isfile(path):
            raise ApiError(404, "Không có file này", "not_found")
        return send_file(path, mimetype="application/octet-stream", conditional=True, max_age=0)

    @app.get("/api/storage/backups")
    @agent_auth
    def api_storage_list():
        d = user_dir(g.agent_user["id"])
        files = [{"filename": n, "size": os.path.getsize(os.path.join(d, n)),
                  "modified": ts(datetime.fromtimestamp(os.path.getmtime(os.path.join(d, n))).isoformat())}
                 for n in sorted(os.listdir(d)) if FILENAME_RE.match(n)]
        return jsonify({"files": files})

    if start_scheduler:
        scheduler.start_scheduler()
    return app


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Backup server (web + API + kho)")
    ap.add_argument("--host", default=config.SERVER_HOST, help="dia chi nghe (mac dinh 0.0.0.0; thu tren may: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=config.SERVER_PORT)
    args = ap.parse_args(argv)
    setup_logging("server", config.LOGS_DIR)
    app = create_app(start_scheduler=True)
    log.info("BACKUP SERVER %s - nghe http://%s:%s", config.VERSION, args.host, args.port)
    log.info("Dữ liệu: kho=%s | CSDL=%s", config.STORAGE_DIR, config.DB_PATH)
    try:
        from waitress import serve
    except ImportError:
        log.warning("Chưa cài waitress - dùng server thử nghiệm của Flask")
        app.run(host=args.host, port=args.port, threaded=True)
        return
    serve(app, host=args.host, port=args.port, threads=8,
          max_request_body_size=config.MAX_UPLOAD_BYTES, channel_timeout=300, ident="backup-server")


if __name__ == "__main__":
    main()
