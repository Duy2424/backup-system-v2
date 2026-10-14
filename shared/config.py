"""
Cau hinh chung cho server va agent.

Thu tu uu tien: bien moi truong > agent/agent_config.txt (chi cho agent) > mac dinh.
Module KHONG tao thu muc khi import; entry point goi ensure_dirs().

Bien moi truong thuong dung (dat tren PC chay server):
  BACKUP_HOST / BACKUP_PORT     dia chi nghe cua web + API (mac dinh 0.0.0.0:5000)
  BACKUP_SECRET_KEY             khoa phien Flask (khong dat -> tu sinh, luu instance/secret_key)
  BACKUP_ADMIN_PASSWORD         mat khau admin lan khoi tao dau tien (khong dat -> tu sinh, in ra console)
  BACKUP_COOKIE_SECURE=1        bat khi truy cap qua HTTPS (vd sau Caddy)
  BACKUP_WORK_DIR / BACKUP_STORAGE_DIR / BACKUP_DB   doi vi tri du lieu
Agent:
  BACKUP_SERVER_URL / BACKUP_AGENT_TOKEN   (hoac sua agent/agent_config.txt)
"""
import os
import platform

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WINDOWS = platform.system() == "Windows"
VERSION = "1.5.0"


def _env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _read_kv(path):
    """Doc file dang KEY=VALUE (bo dong trong / dong # comment)."""
    out = {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip().upper()] = v.strip()
    except OSError:
        pass
    return out


# ===== THU MUC / FILE =====
WORK_DIR = _env("BACKUP_WORK_DIR", os.path.join(BASE_DIR, "work"))
BACKUP_TEMP_DIR = os.path.join(WORK_DIR, "backup_temp")
RESTORE_TEMP_DIR = os.path.join(WORK_DIR, "restore_temp")
SNAPSHOTS_DIR = os.path.join(WORK_DIR, "snapshots")
LOGS_DIR = os.path.join(WORK_DIR, "logs")
SQL_BACKUP_TEMP = os.path.join(WORK_DIR, "sql_backups")
INSTANCE_DIR = _env("BACKUP_INSTANCE_DIR", os.path.join(BASE_DIR, "instance"))
STORAGE_DIR = _env("BACKUP_STORAGE_DIR", os.path.join(BASE_DIR, "storage"))
DB_PATH = _env("BACKUP_DB", os.path.join(BASE_DIR, "backup_system.db"))

# ===== SERVER =====
SERVER_HOST = _env("BACKUP_HOST", "0.0.0.0")
SERVER_PORT = int(_env("BACKUP_PORT", "5000"))
SECRET_KEY = _env("BACKUP_SECRET_KEY")              # None -> server tu sinh va luu
ADMIN_PASSWORD = _env("BACKUP_ADMIN_PASSWORD")       # chi dung khi CSDL chua co user nao
COOKIE_SECURE = _env("BACKUP_COOKIE_SECURE", "0") == "1"
MAX_UPLOAD_BYTES = int(_env("BACKUP_MAX_UPLOAD_GB", "64")) * 1024 ** 3
AGENT_ONLINE_SECONDS = 20                            # agent im lang lau hon -> coi la offline

# ===== AGENT =====
AGENT_CONFIG_FILE = os.path.join(BASE_DIR, "agent", "agent_config.txt")
_agent_cfg = _read_kv(AGENT_CONFIG_FILE)
SERVER_URL = _env("BACKUP_SERVER_URL", _agent_cfg.get("SERVER_URL", "http://127.0.0.1:5000")).rstrip("/")
AGENT_TOKEN = _env("BACKUP_AGENT_TOKEN", _agent_cfg.get("AGENT_TOKEN", ""))
AGENT_POLL_INTERVAL = float(_env("BACKUP_POLL_INTERVAL", _agent_cfg.get("POLL_INTERVAL", "3")))
# Folder browser cua agent (server goi vao de web UI duyet thu muc may agent).
# 127.0.0.1 khi agent va server cung may (khuyen nghi); 0.0.0.0 neu server o may khac.
BROWSER_HOST = _env("BACKUP_BROWSER_HOST", _agent_cfg.get("BROWSER_HOST", "127.0.0.1"))
BROWSER_PORT = int(_env("BACKUP_BROWSER_PORT", _agent_cfg.get("BROWSER_PORT", "5001")))

# ===== THANH PHAN BACKUP =====
# Tick muc nao thi chi backup/restore muc do; tick het = backup toan bo.
BACKUP_COMPONENTS = [
    "ipv4",       # IPv4: dia chi, subnet mask, gateway, DNS
    "ipv6",       # IPv6: dia chi, prefix, gateway, DNS
    "firewall",   # Windows Firewall 3 profile + rules
    "hosts",      # File hosts
    "shares",     # SMB share
    "route",      # Persistent route
    "portproxy",  # netsh portproxy
    "defender",   # Windows Defender
    "files",      # Thu muc nguoi dung tu chon
]

_sample_candidates = [os.path.join(BASE_DIR, "agent", "sample_data"), os.path.join(BASE_DIR, "sample_data")]
_sample_data = next((p for p in _sample_candidates if os.path.exists(p)), _sample_candidates[0])
if IS_WINDOWS:
    DEFAULT_BACKUP_PATHS = [r"C:\Users\Administrator", r"C:\Users\Public", _sample_data]
else:
    DEFAULT_BACKUP_PATHS = [_sample_data]

# ===== SQL SERVER =====
SQL_SERVER_INSTANCE = _env("SQL_INSTANCE", "localhost")
SQL_DATABASES = []  # rong = tu dong tim

# ===== LOAI TRU =====
# Mau glob, so khop KHONG phan biet hoa thuong voi TEN (khong phai ca duong dan).
# Ban v1 goc so khop CHUOI CON nen "AC" loai nham moi file co chu "ac" (contract.docx...).
EXCLUDE_DIRS = [
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    "$Recycle.Bin", "System Volume Information", "Windows.old", "MSOCache",
    "Temp", "Tmp", "INetCache", "INetCookies", "Temporary Internet Files",
    "CryptnetUrlCache", "PackageCache", "Cache", "CachedData", "Code Cache", "GPUCache",
    "Packages", "LocalState", "CrashDumps", "SquirrelTemp", "npm-cache", "pip", ".vs", "WER",
]
EXCLUDE_FILES = [
    "*.tmp", "*.temp", "~$*", "pagefile.sys", "hiberfil.sys", "swapfile.sys",
    "Thumbs.db", "desktop.ini", "backup_system.db", "backup_system.db-*", "agent_config.txt",
    "*.etl", "*.evtx", "*.blf", "*.regtrans-ms", "*.LOG1", "*.LOG2",
    "NTUSER.DAT*", "UsrClass.dat*",
]
# Gop chung (tuong thich code cu dung config.EXCLUDE_PATTERNS)
EXCLUDE_PATTERNS = EXCLUDE_DIRS + EXCLUDE_FILES


def exclude_abs_paths():
    """Thu muc du lieu cua chinh he thong (khong bao gio backup)."""
    return [WORK_DIR, STORAGE_DIR, INSTANCE_DIR]


CHUNK_SIZE = 1024 * 1024  # 1 MiB - kich thuoc khoi doc/ghi/mang


def ensure_dirs(*extra):
    for d in (WORK_DIR, BACKUP_TEMP_DIR, RESTORE_TEMP_DIR, SNAPSHOTS_DIR, LOGS_DIR,
              SQL_BACKUP_TEMP, INSTANCE_DIR, STORAGE_DIR, *extra):
        os.makedirs(d, exist_ok=True)
