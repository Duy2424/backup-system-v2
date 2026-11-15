"""
API kho v2 (Nguoi B, tuan 2-3) - kho CHI THEM: khong co lenh xoa, khong ghi de, PUT trung id = bo qua.
Hop dong: docs/repo-format.md muc 10.

  POST /chunks/missing          hoi kho thieu mau nao                  -> {"missing": [...]}
  PUT  /packs/<id>              nhan pack: SHA-256(body) = id, kiem tra cau truc KHONG can khoa (muc 6.3)
  GET  /packs/<id>              tra pack, ho tro Range (bytes=a-b, bytes=-N) de khoi phuc 1 file
  PUT  /snapshots/<id>          nhan snapshot - client luon goi SAU CUNG
  GET  /snapshots               danh sach snapshot (id, size, mtime)
  GET  /snapshots/<id>          byte snapshot
  POST /chunks/locate           mau nam o pack nao                     -> {"locations": {...}, "missing": [...]}
  GET|PUT /config, GET /keys, GET|PUT /keys/<id>                        ghi mot lan
  GET  /health, GET /stats      trang thai kho (tuan 4: web tong quan doc dedup / dung luong)

Moi method khac (DELETE, POST, PATCH, MOVE...) -> 405. Duong dan la -> 404. Loi tra JSON {"error","message"}.
Luu tru: core.repo_local.LocalRepo (ghi tmp\\ -> fsync -> doi ten / hard link; index cap nhat SAU khi doi ten;
khoi dong lai thi index duoc dung lai tu footer + bang ID cua moi pack).
Trien khai that: app chi nghe 127.0.0.1, Caddy dung truoc lo TLS + bat buoc chung chi client (mTLS) va chuyen
subject chung chi vao header X-Client-Subject de kho ghi log (deploy/kho/).
"""
import errno
import hashlib
import logging
import os
import shutil
import threading
import time
from datetime import datetime

from flask import Flask, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from core import packer
from core.errors import IntegrityError, NotFound, RepoError
from core.repo_local import MAX_SNAPSHOT, LocalRepo

log = logging.getLogger("kho")
VERSION = "1.0"
MAX_IDS = 10_000
MAX_SMALL = 1024 * 1024                  # config / key file
STATS_TTL = 30                           # giay: cache dung luong kho (dem file ton IO)


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _err(status, code, message):
    return jsonify({"error": code, "message": message}), status


def _disk_full(e):
    return getattr(e, "errno", None) == errno.ENOSPC or getattr(e, "winerror", None) == 112


def create_app(root, repo=None):
    """root: thu muc kho (co the chua ton tai - init se tao). repo: LocalRepo co san (test)."""
    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = MAX_SNAPSHOT + 1024 * 1024      # lon hon moi gioi han rieng ben duoi
    repo = repo or LocalRepo(root)
    lock = threading.Lock()
    state = {"started": _now(), "requests": 0, "packs_created": 0, "snapshots_created": 0, "bytes_in": 0,
             "rejected": 0, "last_write": None}
    cache = {"at": 0.0, "value": None}
    app.config["kho_repo"], app.config["kho_state"] = repo, state

    # ------------------------------------------------------------ loi / log
    @app.errorhandler(HTTPException)
    def _http_error(e):
        code = {404: "not_found", 405: "method_not_allowed", 413: "too_large", 416: "range_not_satisfiable",
                411: "length_required"}.get(e.code, "error")
        msg = {404: "Không có đường dẫn này", 405: "Kho chỉ cho THÊM: không có lệnh xoá/sửa",
               413: "Quá lớn", 416: "Range không hợp lệ"}.get(e.code, e.description)
        if e.code in (405, 413):
            state["rejected"] += 1
        return _err(e.code, code, msg)

    @app.errorhandler(NotFound)
    def _nf(e):
        return _err(404, "not_found", str(e))

    @app.before_request
    def _begin():
        g.t0 = time.perf_counter()
        state["requests"] += 1

    @app.after_request
    def _log(resp):
        who = request.headers.get("X-Client-Subject") or request.remote_addr or "?"
        ms = (time.perf_counter() - getattr(g, "t0", time.perf_counter())) * 1000
        log.info("%s %s %s -> %s (%s byte vào, %.0f ms)", who, request.method, request.path, resp.status_code,
                 f"{request.content_length or 0:,}", ms)
        resp.headers.setdefault("Cache-Control", "no-store")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    # ------------------------------------------------------------ tien ich
    def _ids():
        d = request.get_json(silent=True)
        if not isinstance(d, dict) or not isinstance(d.get("ids"), list):
            return None, _err(400, "bad_request", 'Cần JSON {"ids": [...]}')
        if len(d["ids"]) > MAX_IDS:
            return None, _err(413, "too_many_ids", f"Tối đa {MAX_IDS} ID mỗi lần")
        if not all(packer.is_hex_id(i) for i in d["ids"]):
            return None, _err(400, "bad_request", "ID phải là 64 ký tự hex thường")
        return d["ids"], None

    def _body(limit):
        n = request.content_length
        if n is None:
            return None, _err(411, "length_required", "Cần Content-Length")
        if n > limit:
            state["rejected"] += 1
            return None, _err(413, "too_large", f"Tối đa {limit:,} byte")
        data = request.get_data()
        if len(data) != n:
            return None, _err(400, "incomplete", f"Nhận {len(data):,}/{n:,} byte")
        state["bytes_in"] += len(data)
        return data, None

    def _put(kind, write, data):
        """Ghi mot lan (pack/snapshot/key/config). Tra ve response theo ket qua."""
        try:
            with lock:
                status = write(data)
        except IntegrityError as ex:
            state["rejected"] += 1
            return _err(400, f"bad_{kind}", str(ex))
        except RepoError as ex:
            state["rejected"] += 1
            return _err(409, "conflict", str(ex))
        except OSError as ex:
            if _disk_full(ex):
                log.error("Đĩa kho đầy: %s", ex)
                return _err(507, "insufficient_storage", "Đĩa kho đầy")
            raise
        if status == "created":
            state["last_write"] = _now()
        return status

    # ------------------------------------------------------------ 4 lenh chinh (muc 10.1)
    @app.post("/chunks/missing")
    def missing():
        ids, e = _ids()
        if e:
            return e
        return jsonify({"missing": repo.missing_chunks(ids)})

    @app.put("/packs/<pid>")
    def put_pack(pid):
        if not packer.is_hex_id(pid):
            return _err(400, "bad_id", "pack_id phải là 64 ký tự hex thường")
        if repo._pack_path(pid).is_file():
            return jsonify({"status": "exists"}), 200
        data, e = _body(packer.MAX_PACK_SIZE)
        if e:
            return e
        if hashlib.sha256(data).hexdigest() != pid:
            state["rejected"] += 1
            return _err(400, "hash_mismatch", "SHA-256(body) khác pack_id trong URL")
        r = _put("pack", lambda d: repo.put_pack(pid, d), data)
        if r == "created":
            state["packs_created"] += 1
            _, _, ids = packer.parse_structure(data)
            cache["at"] = 0
            return jsonify({"status": "created", "chunks": len(ids)}), 201
        if r == "exists":
            return jsonify({"status": "exists"}), 200
        return r

    @app.get("/packs/<pid>")
    def get_pack(pid):
        if not packer.is_hex_id(pid):
            return _err(400, "bad_id", "pack_id phải là 64 ký tự hex thường")
        path = repo._pack_path(pid)
        if not path.is_file():
            return _err(404, "not_found", f"Không có pack {pid[:12]}")
        # send_file(conditional=True): Range bytes=a-b va bytes=-N -> 206; sai -> 416
        return send_file(str(path), mimetype="application/octet-stream", conditional=True, etag=pid, max_age=0)

    @app.put("/snapshots/<sid>")
    def put_snapshot(sid):
        if not packer.is_hex_id(sid):
            return _err(400, "bad_id", "snapshot_id phải là 64 ký tự hex thường")
        data, e = _body(MAX_SNAPSHOT)
        if e:
            return e
        if hashlib.sha256(data).hexdigest() != sid:
            state["rejected"] += 1
            return _err(400, "hash_mismatch", "SHA-256(body) khác snapshot_id trong URL")
        r = _put("snapshot", lambda d: repo.put_snapshot(sid, d), data)
        if r in ("created", "exists"):
            if r == "created":
                state["snapshots_created"] += 1
                cache["at"] = 0
            return jsonify({"status": r}), 201 if r == "created" else 200
        return r

    # ------------------------------------------------------------ lenh doc / ghi-mot-lan (muc 10.2)
    @app.post("/chunks/locate")
    def locate():
        ids, e = _ids()
        if e:
            return e
        loc = repo.locate_chunks(ids)
        return jsonify({"locations": loc, "missing": [i for i in ids if i not in loc]})

    @app.get("/snapshots")
    def list_snapshots():
        return jsonify({"snapshots": repo.list_snapshots()})

    @app.get("/snapshots/<sid>")
    def get_snapshot(sid):
        if not packer.is_hex_id(sid):
            return _err(400, "bad_id", "snapshot_id phải là 64 ký tự hex thường")
        return repo.get_snapshot(sid), 200, {"Content-Type": "application/octet-stream", "ETag": f'"{sid}"'}

    @app.get("/config")
    def get_config():
        return repo.get_config(), 200, {"Content-Type": "application/json"}

    @app.put("/config")
    def put_config():
        data, e = _body(MAX_SMALL)
        if e:
            return e
        r = _put("config", repo.put_config, data)
        return (jsonify({"status": r}), 201 if r == "created" else 200) if r in ("created", "exists") else r

    @app.get("/keys")
    def list_keys():
        return jsonify({"keys": repo.list_keys()})

    @app.get("/keys/<kid>")
    def get_key(kid):
        if not packer.is_hex_id(kid):
            return _err(400, "bad_id", "key_id phải là 64 ký tự hex thường")
        return repo.get_key(kid), 200, {"Content-Type": "application/json"}

    @app.put("/keys/<kid>")
    def put_key(kid):
        if not packer.is_hex_id(kid):
            return _err(400, "bad_id", "key_id phải là 64 ký tự hex thường")
        data, e = _body(MAX_SMALL)
        if e:
            return e
        if hashlib.sha256(data).hexdigest() != kid:
            return _err(400, "hash_mismatch", "key_id khác SHA-256(body)")
        r = _put("key", lambda d: repo.put_key(kid, d), data)
        return (jsonify({"status": r}), 201 if r == "created" else 200) if r in ("created", "exists") else r

    # ------------------------------------------------------------ trang thai (tuan 4)
    def _usage():
        if time.monotonic() - cache["at"] < STATS_TTL and cache["value"] is not None:
            return cache["value"]
        total = {"packs": 0, "snapshots": 0}
        for name in total:
            d = os.path.join(root, name)
            for dp, _, files in os.walk(d):
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
        v = {"packs": len(repo.list_packs()), "snapshots": len(repo.list_snapshots()), "keys": len(repo.list_keys()),
             "bytes_packs": total["packs"], "bytes_snapshots": total["snapshots"],
             "bytes_on_disk": total["packs"] + total["snapshots"], "disk": disk, "has_config": repo.exists()}
        cache["at"], cache["value"] = time.monotonic(), v
        return v

    @app.get("/health")
    def health():
        u = _usage()
        return jsonify({"ok": True, "version": VERSION, "packs": u["packs"], "snapshots": u["snapshots"],
                        "initialized": u["has_config"], "time": _now()})

    @app.get("/stats")
    def stats():
        return jsonify({**_usage(), "version": VERSION, "kho": root, **state, "time": _now()})

    return app
