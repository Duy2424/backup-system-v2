"""
Bat server v1 (server/server.py) o tien trinh RIENG, chi phuc vu bench_v1.

Khong sua code v1: chi doi duong dan DB/kho sang thu muc cua lan bench, nghe o
127.0.0.1 (cong ngau nhien), va gan them 1 hook ghi so byte than request vao
file JSONL de bench biet "byte gui". Scheduler cua v1 KHONG duoc bat.

Dong dau tien in ra stdout la JSON: {"port", "id", "username", "token", "encryption_key"}.

Thuong khong chay tay; bench_v1.py tu goi:
  python bench/v1_server.py --workdir <thu muc> [--port 0]
"""
import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for sub in ("shared", "server"):
    p = str(REPO / sub)
    if p not in sys.path:
        sys.path.insert(0, p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    work = Path(args.workdir).resolve()
    work.mkdir(parents=True, exist_ok=True)

    import config  # v1 shared/config.py
    config.DB_PATH = str(work / "v1_server.db")
    config.STORAGE_DIR = str(work / "v1_kho")
    os.makedirs(config.STORAGE_DIR, exist_ok=True)

    import database
    import server as v1
    from flask import request
    from werkzeug.serving import make_server

    database.init_db()
    user = database.get_user_by_username("user1")
    log_path = work / "v1_requests.jsonl"
    log = open(log_path, "a", encoding="utf-8")

    @v1.app.before_request
    def _dem_byte():
        log.write(json.dumps({"method": request.method, "path": request.path,
                              "content_length": request.content_length or 0}) + "\n")
        log.flush()

    srv = make_server("127.0.0.1", args.port, v1.app, threaded=True)
    print(json.dumps({"port": srv.port, "id": user["id"], "username": user["username"],
                      "token": user["token"], "encryption_key": user["encryption_key"]}), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
