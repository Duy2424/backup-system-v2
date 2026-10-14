"""
CSDL SQLite: users, backups, jobs, schedules, agents.

- WAL + busy_timeout: UI poll lien tuc trong luc agent ghi tien do khong bi "database is locked".
- Mat khau bam scrypt; hash cu (salt$sha256) van dang nhap duoc va tu nang cap.
- Moi thoi diem luu dang ISO 8601 co mui gio.
- Migration theo PRAGMA user_version (CSDL cu cua v1 tu nang cap khi khoi dong).
"""
import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from shared import config

SCHEMA_VERSION = 2
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ===================================================================== mat khau / token

def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${dk.hex()}"


def verify_password(password, stored):
    """Tra ve (dung_mat_khau, can_bam_lai)."""
    try:
        if stored.startswith("scrypt$"):
            _, n, r, p, salt, dk = stored.split("$")
            calc = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                                  n=int(n), r=int(r), p=int(p), dklen=len(dk) // 2)
            ok = hmac.compare_digest(calc.hex(), dk)
            return ok, ok and (int(n), int(r), int(p)) != (_SCRYPT["n"], _SCRYPT["r"], _SCRYPT["p"])
        salt, digest = stored.split("$")            # dinh dang v1: salt$sha256(salt+pw)
        calc = hashlib.sha256((salt + password).encode()).hexdigest()
        ok = hmac.compare_digest(calc, digest)
        return ok, ok
    except (ValueError, TypeError):
        return False, False


def generate_token():
    return secrets.token_urlsafe(32)


def generate_encryption_key():
    """Khoa Fernet (32 byte ngau nhien, base64 urlsafe)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


# ===================================================================== ket noi

@contextmanager
def get_db():
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def init_db(admin_password=None):
    """
    Tao/nang cap bang. Neu chua co user nao: tao 'admin' voi mat khau `admin_password`
    (hoac config.ADMIN_PASSWORD, hoac ngau nhien). Tra ve mat khau vua tao (None neu khong tao).
    """
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            token TEXT UNIQUE NOT NULL,
            encryption_key TEXT NOT NULL,
            created_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            drive_file_id TEXT,
            size INTEGER DEFAULT 0,
            backup_type TEXT DEFAULT 'full',
            paths TEXT,
            snapshot_summary TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_type TEXT NOT NULL,
            params TEXT,
            backup_id INTEGER,
            status TEXT DEFAULT 'pending',
            progress INTEGER DEFAULT 0,
            message TEXT,
            created_at TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (backup_id) REFERENCES backups(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            schedule_type TEXT NOT NULL,
            interval_hours INTEGER DEFAULT 24,
            time_of_day TEXT DEFAULT '02:00',
            day_of_week INTEGER DEFAULT 0,
            backup_paths TEXT,
            enabled INTEGER DEFAULT 1,
            last_run TIMESTAMP,
            next_run TIMESTAMP,
            created_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            hostname TEXT NOT NULL,
            ip TEXT,
            version TEXT,
            platform TEXT,
            browser_port INTEGER,
            current_job INTEGER,
            last_seen TIMESTAMP,
            UNIQUE (user_id, hostname),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_user_status ON jobs(user_id, status);
        CREATE INDEX IF NOT EXISTS idx_backups_user ON backups(user_id, created_at);
        """)
        # --- migration tu CSDL v1 ---
        if "cancel_requested" not in _columns(conn, "jobs"):
            conn.execute("ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER DEFAULT 0")
        if "updated_at" not in _columns(conn, "jobs"):
            conn.execute("ALTER TABLE jobs ADD COLUMN updated_at TIMESTAMP")
        if "stats" not in _columns(conn, "backups"):
            conn.execute("ALTER TABLE backups ADD COLUMN stats TEXT")
        if "components" not in _columns(conn, "schedules"):
            conn.execute("ALTER TABLE schedules ADD COLUMN components TEXT")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        created_pw = None
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            created_pw = admin_password or config.ADMIN_PASSWORD or secrets.token_urlsafe(9)
            conn.execute(
                "INSERT INTO users (username, password, role, token, encryption_key, created_at) "
                "VALUES (?, ?, 'admin', ?, ?, ?)",
                ("admin", hash_password(created_pw), generate_token(), generate_encryption_key(), now_iso()))
        return created_pw


# ===================================================================== users

_USER_PUBLIC = "id, username, role, token, created_at"


def _one(conn, sql, args=()):
    row = conn.execute(sql, args).fetchone()
    return dict(row) if row else None


def get_user_by_username(username):
    with get_db() as conn:
        return _one(conn, "SELECT * FROM users WHERE username=?", (username,))


def get_user_by_id(user_id):
    with get_db() as conn:
        return _one(conn, "SELECT * FROM users WHERE id=?", (user_id,))


def get_user_by_token(token):
    if not token:
        return None
    with get_db() as conn:
        return _one(conn, "SELECT * FROM users WHERE token=?", (token,))


def authenticate(username, password):
    """Tra ve user neu dung mat khau (tu nang cap hash cu)."""
    user = get_user_by_username(username)
    if not user:
        hash_password(password)                 # can bang thoi gian tra loi
        return None
    ok, rehash = verify_password(password, user["password"])
    if not ok:
        return None
    if rehash:
        with get_db() as conn:
            conn.execute("UPDATE users SET password=? WHERE id=?", (hash_password(password), user["id"]))
    return user


def list_users():
    with get_db() as conn:
        return [dict(r) for r in conn.execute(f"SELECT {_USER_PUBLIC} FROM users ORDER BY id")]


def create_user(username, password, role="user"):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password, role, token, encryption_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (username, hash_password(password), role, generate_token(), generate_encryption_key(), now_iso()))
        return cur.lastrowid


def update_user(user_id, username=None, password=None, role=None):
    sets, args = [], []
    if username:
        sets.append("username=?")
        args.append(username)
    if password:
        sets.append("password=?")
        args.append(hash_password(password))
    if role:
        sets.append("role=?")
        args.append(role)
    if sets:
        with get_db() as conn:
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*args, user_id))


def rotate_token(user_id):
    token = generate_token()
    with get_db() as conn:
        conn.execute("UPDATE users SET token=? WHERE id=?", (token, user_id))
    return token


def delete_user(user_id):
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))


def count_admins():
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]


# ===================================================================== backups

_BACKUP_COLS = {"size", "snapshot_summary", "status", "stats", "filename", "paths", "backup_type"}


def create_backup_record(user_id, filename, paths, backup_type="full"):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO backups (user_id, filename, paths, backup_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, filename, json.dumps(paths, ensure_ascii=False), backup_type, now_iso()))
        return cur.lastrowid


def update_backup(backup_id, **kwargs):
    bad = set(kwargs) - _BACKUP_COLS
    if bad:
        raise ValueError(f"Cot khong hop le: {bad}")
    if kwargs:
        with get_db() as conn:
            conn.execute(f"UPDATE backups SET {', '.join(f'{k}=?' for k in kwargs)} WHERE id=?",
                         (*kwargs.values(), backup_id))


def list_backups(user_id, limit=None):
    sql = "SELECT * FROM backups WHERE user_id=? ORDER BY id DESC"
    with get_db() as conn:
        if limit:
            return [dict(r) for r in conn.execute(sql + " LIMIT ?", (user_id, limit))]
        return [dict(r) for r in conn.execute(sql, (user_id,))]


def get_backup(backup_id):
    with get_db() as conn:
        return _one(conn, "SELECT * FROM backups WHERE id=?", (backup_id,))


def backup_stats(user_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size), 0) AS total FROM backups "
            "WHERE user_id=? AND status='completed'", (user_id,)).fetchone()
        last = _one(conn, "SELECT * FROM backups WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
    return {"total_backups": row["n"], "total_size": row["total"], "last_backup": last}


# ===================================================================== jobs

_JOB_COLS = {"status", "progress", "message", "completed_at", "backup_id", "started_at", "cancel_requested"}
ACTIVE = ("pending", "running")


def create_job(user_id, job_type, params=None, backup_id=None):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (user_id, job_type, params, backup_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, job_type, json.dumps(params or {}, ensure_ascii=False), backup_id, now_iso(), now_iso()))
        return cur.lastrowid


def claim_next_job(user_id):
    """Lay (nguyen tu) job pending cu nhat CUA user nay va chuyen sang running."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM jobs WHERE user_id=? AND status='pending' ORDER BY id LIMIT 1", (user_id,)).fetchone()
        if not row:
            return None
        t = now_iso()
        conn.execute("UPDATE jobs SET status='running', started_at=?, updated_at=? WHERE id=?", (t, t, row["id"]))
        job = dict(row)
        job.update(status="running", started_at=t)
        return job


def update_job(job_id, **kwargs):
    bad = set(kwargs) - _JOB_COLS
    if bad:
        raise ValueError(f"Cot khong hop le: {bad}")
    kwargs["updated_at"] = now_iso()
    with get_db() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(f'{k}=?' for k in kwargs)} WHERE id=?",
                     (*kwargs.values(), job_id))


def get_job(job_id):
    with get_db() as conn:
        return _one(conn, "SELECT * FROM jobs WHERE id=?", (job_id,))


def list_jobs(user_id, limit=20):
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM jobs WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))]


def active_job(user_id):
    with get_db() as conn:
        return _one(conn, "SELECT * FROM jobs WHERE user_id=? AND status IN ('pending','running') "
                          "ORDER BY status='running' DESC, id LIMIT 1", (user_id,))


def fail_running_jobs(user_id, message):
    """Agent khoi dong lai -> cac job 'running' cu khong con ai xu ly."""
    with get_db() as conn:
        conn.execute("UPDATE jobs SET status='failed', message=?, completed_at=?, updated_at=? "
                     "WHERE user_id=? AND status='running'", (message, now_iso(), now_iso(), user_id))


def cancel_job(job_id):
    """pending -> cancelled ngay; running -> danh dau de agent tu dung."""
    with get_db() as conn:
        job = _one(conn, "SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] not in ACTIVE:
            return job
        if job["status"] == "pending":
            conn.execute("UPDATE jobs SET status='cancelled', message='Đã huỷ', completed_at=?, updated_at=? "
                         "WHERE id=?", (now_iso(), now_iso(), job_id))
        else:
            conn.execute("UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?", (now_iso(), job_id))
        return _one(conn, "SELECT * FROM jobs WHERE id=?", (job_id,))


# ===================================================================== agents

def touch_agent(user_id, hostname, ip, version=None, platform=None, browser_port=None, current_job=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO agents (user_id, hostname, ip, version, platform, browser_port, current_job, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, hostname) DO UPDATE SET
                ip=excluded.ip, version=COALESCE(excluded.version, agents.version),
                platform=COALESCE(excluded.platform, agents.platform),
                browser_port=COALESCE(excluded.browser_port, agents.browser_port),
                current_job=excluded.current_job, last_seen=excluded.last_seen
        """, (user_id, hostname, ip, version, platform, browser_port, current_job, now_iso()))


def list_agents(user_id):
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM agents WHERE user_id=? ORDER BY last_seen DESC", (user_id,))]
