"""
Folder browser: HTTP mini tren agent de web UI (qua server) duyet thu muc may agent.

  GET /folders/quick           -> thu muc hay dung + o dia
  GET /folders/list?path=...   -> thu muc con (va toi da 200 file) tai path
  GET /folders/ping

Bao mat (v1 goc nghe 0.0.0.0, khong xac thuc, cho CORS *):
  - BAT BUOC header X-Auth-Token = token cua agent (server gui kem khi proxy).
  - Mac dinh chi nghe 127.0.0.1 (agent cung may voi server). Server o may khac thi dat
    BROWSER_HOST=0.0.0.0 trong agent_config.txt.
"""
import hmac
import json
import logging
import os
import platform
import string
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from shared import config

log = logging.getLogger("agent.browser")
IS_WINDOWS = platform.system() == "Windows"
MAX_FILES = 200


def get_drives():
    if not IS_WINDOWS:
        return ["/"]
    return [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]


def get_quick_picks():
    if not IS_WINDOWS:
        return [{"name": p, "path": p, "icon": "folder"} for p in ("/home", "/tmp") if os.path.isdir(p)]
    home = os.environ.get("USERPROFILE", r"C:\Users\Administrator")
    cands = [("Desktop", os.path.join(home, "Desktop"), "desktop"),
             ("Documents", os.path.join(home, "Documents"), "doc"),
             ("Downloads", os.path.join(home, "Downloads"), "download"),
             ("Pictures", os.path.join(home, "Pictures"), "image"),
             ("Thư mục người dùng", home, "user"),
             ("Public", r"C:\Users\Public", "users")]
    picks = [{"name": n, "path": p, "icon": i} for n, p, i in cands if os.path.isdir(p)]
    picks += [{"name": f"Ổ {d[0]}:", "path": d, "icon": "drive"} for d in get_drives()]
    return picks


def list_directory(path):
    if not path:
        if IS_WINDOWS:
            return {"current": "", "parent": None, "files": [],
                    "folders": [{"name": d, "path": d, "is_drive": True} for d in get_drives()]}
        path = "/"
    path = os.path.normpath(path)
    if not os.path.isdir(path):
        return {"error": f"Không phải thư mục hoặc không tồn tại: {path}"}
    folders, files = [], []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        folders.append({"name": e.name, "path": e.path, "is_drive": False})
                    elif e.is_file(follow_symlinks=False) and len(files) < MAX_FILES:
                        files.append({"name": e.name, "path": e.path, "size": e.stat().st_size})
                except OSError:
                    continue
    except PermissionError:
        return {"error": "Không có quyền truy cập thư mục này"}
    except OSError as e:
        return {"error": str(e)}
    folders.sort(key=lambda x: x["name"].lower())
    files.sort(key=lambda x: x["name"].lower())
    parent = os.path.dirname(path.rstrip("\\/"))
    if IS_WINDOWS and len(path) <= 3:
        parent = ""
    return {"current": path, "parent": parent if parent != path else None, "folders": folders, "files": files}


class BrowserHandler(BaseHTTPRequestHandler):
    server_version = "BackupAgentBrowser/1.5"

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        token = self.headers.get("X-Auth-Token", "")
        if not config.AGENT_TOKEN or not hmac.compare_digest(token, config.AGENT_TOKEN):
            return self._json({"error": "unauthorized"}, 401)
        u = urlparse(self.path)
        try:
            if u.path == "/folders/list":
                return self._json(list_directory(parse_qs(u.query).get("path", [""])[0]))
            if u.path == "/folders/quick":
                return self._json({"quick_picks": get_quick_picks(), "drives": get_drives(),
                                   "hostname": platform.node()})
            if u.path == "/folders/ping":
                return self._json({"ok": True, "hostname": platform.node()})
            return self._json({"error": "not_found"}, 404)
        except Exception as e:      # noqa: BLE001
            log.exception("Loi folder browser")
            return self._json({"error": str(e)}, 500)

    def log_message(self, fmt, *args):
        pass


def start_browser_server(host=None, port=None):
    """Chay trong thread nen. Tra ve server (hoac None neu khong mo duoc cong)."""
    host, port = host or config.BROWSER_HOST, port or config.BROWSER_PORT
    try:
        httpd = ThreadingHTTPServer((host, port), BrowserHandler)
    except OSError as e:
        log.error("Khong mo duoc folder browser %s:%s - %s", host, port, e)
        return None
    threading.Thread(target=httpd.serve_forever, name="folder-browser", daemon=True).start()
    log.info("Folder browser nghe %s:%s", host, port)
    return httpd
