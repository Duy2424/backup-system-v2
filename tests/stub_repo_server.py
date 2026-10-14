"""
STUB TOI THIEU cua API kho (docs/repo-format.md muc 10) - CHI DUNG DE TEST client HTTP.
Ban that do Nguoi B viet (chay sau Caddy mTLS, icacls deny delete, NSSM). Khong dung stub nay
de chay that.

Luu tru dung core.repo_local.LocalRepo. Them 2 che do gay loi cho test:
  fail_after_packs=N  sau N pack ghi thanh cong, moi PUT /packs tra 503 (mo phong dut mang)
  flaky=K             K request dau tien (bat ky) tra 503 roi binh thuong (loi tam thoi)
state["received"]: moi chunk_id da nhan trong cac pack ghi thanh cong (de kiem tra gui trung).
"""
import hashlib
import re
import threading

from flask import Flask, jsonify, request

from core import packer
from core.errors import IntegrityError, NotFound, RepoError
from core.repo_local import LocalRepo

MAX_IDS = 10_000


def create_stub_app(root, fail_after_packs=None, flaky=0):
    app = Flask(__name__)
    repo = LocalRepo(root)
    lock = threading.Lock()
    state = {"fail_after": fail_after_packs, "flaky": flaky, "packs_ok": 0, "received": [], "requests": 0}
    app.config["stub_state"] = state

    def err(status, code, message):
        return jsonify({"error": code, "message": message}), status

    @app.before_request
    def _flaky():
        with lock:
            state["requests"] += 1
            if state["flaky"] > 0:
                state["flaky"] -= 1
                return err(503, "unavailable", "loi tam thoi (stub)")

    @app.errorhandler(NotFound)
    def _nf(e):
        return err(404, "not_found", str(e))

    def _ids():
        d = request.get_json(silent=True)
        if not isinstance(d, dict) or not isinstance(d.get("ids"), list):
            return None, err(400, "bad_request", "can {\"ids\": [...]}")
        if len(d["ids"]) > MAX_IDS:
            return None, err(413, "too_many_ids", "toi da 10000 ID")
        if not all(packer.is_hex_id(i) for i in d["ids"]):
            return None, err(400, "bad_request", "ID phai la 64 hex thuong")
        return d["ids"], None

    def _body(limit):
        if request.content_length is None:
            return None, err(411, "length_required", "can Content-Length")
        if request.content_length > limit:
            return None, err(413, "too_large", "qua lon")
        return request.get_data(), None

    @app.post("/chunks/missing")
    def missing():
        ids, e = _ids()
        return e or jsonify({"missing": repo.missing_chunks(ids)})

    @app.post("/chunks/locate")
    def locate():
        ids, e = _ids()
        if e:
            return e
        loc = repo.locate_chunks(ids)
        return jsonify({"locations": loc, "missing": [i for i in ids if i not in loc]})

    @app.put("/packs/<pid>")
    def put_pack(pid):
        if not packer.is_hex_id(pid):
            return err(400, "bad_id", "pack_id khong hop le")
        data, e = _body(packer.MAX_PACK_SIZE)
        if e:
            return e
        with lock:
            if state["fail_after"] is not None and state["packs_ok"] >= state["fail_after"]:
                return err(503, "unavailable", "mo phong dut mang (stub)")
        if hashlib.sha256(data).hexdigest() != pid:
            return err(400, "hash_mismatch", "sha256(body) khac pack_id")
        try:
            status = repo.put_pack(pid, data)
        except IntegrityError as ex:
            return err(400, "bad_pack", str(ex))
        if status == "created":
            _, _, ids = packer.parse_structure(data)
            with lock:
                state["packs_ok"] += 1
                state["received"].extend(i.hex() for i in ids)
            return jsonify({"status": "created", "chunks": len(ids)}), 201
        return jsonify({"status": "exists"}), 200

    @app.get("/packs/<pid>")
    def get_pack(pid):
        data = repo.get_pack(pid)
        rng = request.headers.get("Range")
        if rng:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng)
            if not m or (not m.group(1) and not m.group(2)):
                return err(416, "range_not_satisfiable", rng)
            if not m.group(1):                                   # dang hau to: bytes=-N
                a, b = max(0, len(data) - int(m.group(2))), len(data) - 1
            else:
                a = int(m.group(1))
                b = min(int(m.group(2)), len(data) - 1) if m.group(2) else len(data) - 1
            if a >= len(data):
                return err(416, "range_not_satisfiable", rng)
            app.config["stub_state"]["range_bytes"] = app.config["stub_state"].get("range_bytes", 0) + (b - a + 1)
            return data[a:b + 1], 206, {"Content-Type": "application/octet-stream",
                                        "Content-Range": f"bytes {a}-{b}/{len(data)}"}
        return data, 200, {"Content-Type": "application/octet-stream", "ETag": f'"{pid}"'}

    @app.put("/snapshots/<sid>")
    def put_snapshot(sid):
        data, e = _body(256 * 1024 * 1024)
        if e:
            return e
        if hashlib.sha256(data).hexdigest() != sid:
            return err(400, "hash_mismatch", "sha256(body) khac snapshot_id")
        try:
            status = repo.put_snapshot(sid, data)
        except IntegrityError as ex:
            return err(400, "bad_snapshot", str(ex))
        return jsonify({"status": status}), 201 if status == "created" else 200

    @app.get("/snapshots")
    def list_snapshots():
        return jsonify({"snapshots": repo.list_snapshots()})

    @app.get("/snapshots/<sid>")
    def get_snapshot(sid):
        return repo.get_snapshot(sid), 200, {"Content-Type": "application/octet-stream"}

    @app.get("/config")
    def get_config():
        return repo.get_config(), 200, {"Content-Type": "application/json"}

    @app.put("/config")
    def put_config():
        data, e = _body(1024 * 1024)
        if e:
            return e
        try:
            status = repo.put_config(data)
        except RepoError as ex:
            return err(409, "conflict", str(ex))
        return jsonify({"status": status}), 201 if status == "created" else 200

    @app.get("/keys")
    def list_keys():
        return jsonify({"keys": repo.list_keys()})

    @app.get("/keys/<kid>")
    def get_key(kid):
        return repo.get_key(kid), 200, {"Content-Type": "application/json"}

    @app.put("/keys/<kid>")
    def put_key(kid):
        data, e = _body(1024 * 1024)
        if e:
            return e
        try:
            status = repo.put_key(kid, data)
        except IntegrityError:
            return err(400, "hash_mismatch", "key_id khac sha256(body)")
        return jsonify({"status": status}), 201 if status == "created" else 200

    return app
