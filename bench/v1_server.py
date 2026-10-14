"""
Bat server v1 o tien trinh RIENG, chi phuc vu bench_v1.

  --src <thu muc>  ma nguon can do: repo hien tai (ban toi uu) hoac git worktree cua tag v1-goc.

Khong sua code server: doi duong dan DB/kho sang thu muc cua lan bench, nghe 127.0.0.1
(cong ngau nhien), boc ung dung bang 1 WSGI middleware dem byte than request (dung ca voi
upload chunked khong co Content-Length) ghi ra <workdir>/v1_requests.jsonl. Scheduler KHONG bat.

Dong dau tien in ra stdout la JSON: {"port", "id", "username", "token", "encryption_key"}.
"""
import argparse
import json
import os
import sys
from pathlib import Path


class _CountingInput:
    def __init__(self, inner):
        self.inner, self.n = inner, 0

    def read(self, *a):
        b = self.inner.read(*a)
        self.n += len(b)
        return b

    def readline(self, *a):
        b = self.inner.readline(*a)
        self.n += len(b)
        return b

    def readinto(self, buf):
        k = self.inner.readinto(buf)
        self.n += k or 0
        return k

    def __iter__(self):
        for line in self.inner:
            self.n += len(line)
            yield line

    def __getattr__(self, name):
        return getattr(self.inner, name)


class CountingMiddleware:
    def __init__(self, app, log_path):
        self.app, self.log = app, open(log_path, "a", encoding="utf-8")

    def __call__(self, environ, start_response):
        counter = _CountingInput(environ["wsgi.input"])
        environ["wsgi.input"] = counter
        try:
            return self.app(environ, start_response)
        finally:
            self.log.write(json.dumps({"method": environ.get("REQUEST_METHOD"), "path": environ.get("PATH_INFO"),
                                       "content_length": counter.n}) + "\n")
            self.log.flush()


def _new_style(src, work):
    sys.path.insert(0, str(src))
    from shared import config, database
    config.DB_PATH = str(work / "v1_server.db")
    config.STORAGE_DIR = str(work / "v1_kho")
    config.INSTANCE_DIR = str(work / "v1_instance")
    config.SECRET_KEY = "bench"
    config.ADMIN_PASSWORD = "bench-admin-pass"
    from server.server import create_app
    app = create_app()
    if not database.get_user_by_username("bench"):
        database.create_user("bench", "bench-user-pass")
    return app, database.get_user_by_username("bench")


def _old_style(src, work):
    for sub in ("shared", "server"):
        sys.path.insert(0, str(src / sub))
    import config  # v1 goc: shared/config.py
    config.DB_PATH = str(work / "v1_server.db")
    config.STORAGE_DIR = str(work / "v1_kho")
    os.makedirs(config.STORAGE_DIR, exist_ok=True)
    import database
    import server as v1
    database.init_db()
    return v1.app, database.get_user_by_username("user1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--src", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    work, src = Path(args.workdir).resolve(), Path(args.src).resolve()
    work.mkdir(parents=True, exist_ok=True)
    app, user = (_new_style if (src / "shared" / "__init__.py").exists() else _old_style)(src, work)

    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", args.port, CountingMiddleware(app, work / "v1_requests.jsonl"), threaded=True)
    print(json.dumps({"port": srv.port, "id": user["id"], "username": user["username"],
                      "token": user["token"], "encryption_key": user["encryption_key"]}), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
