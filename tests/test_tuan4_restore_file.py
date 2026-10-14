"""Tuan 4 (A): khoi phuc tung file - duyet snapshot, chi tai dung mau cua file (Range), so SHA-256."""
import hashlib
import os
import threading

import pytest
from werkzeug.serving import make_server

from bench import make_dataset
from core import packer
from core.errors import IntegrityError
from core.repo_http import HttpRepo
from core.repo_local import LocalRepo
from core.repository import Repository, init_repo
from tests.core_helpers import FAST_SCRYPT, PASSWORD, new_repo, reopen
from tests.stub_repo_server import create_stub_app


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    root = tmp_path_factory.mktemp("d") / "du_lieu"
    make_dataset.generate(root, "40MB", seed=41)
    return root


def pick_file(repo, sid, min_size=200_000):
    files = [e for e in repo.ls(sid) if e["type"] == "file" and e["size"] >= min_size and "tai_lieu" in e["path"]]
    return files[0]


def test_ls_va_sha256_tung_file(tmp_path, data):
    repo = new_repo(tmp_path / "kho")
    sid = repo.backup([str(data)])["snapshot_id"]
    items = repo.ls(sid, "du_lieu/tai_lieu")
    assert items and all(i["path"].startswith("du_lieu/tai_lieu") for i in items)
    f = next(i for i in items if i["type"] == "file")
    real = data / f["path"].split("/", 1)[1]
    assert f["sha256"] == hashlib.sha256(real.read_bytes()).hexdigest()
    sid2 = repo.backup([str(data)])["snapshot_id"]                      # lan 2 lay tu cache: van co sha256
    assert all(e.get("sha256") for e in repo.ls(sid2) if e["type"] == "file")


def test_khoi_phuc_1_file_chi_tai_dung_mau(tmp_path, data):
    repo = new_repo(tmp_path / "kho")
    sid = repo.backup([str(data)])["snapshot_id"]
    f = pick_file(repo, sid)
    total_packs = sum(os.path.getsize(tmp_path / "kho" / "packs" / p[:2] / p) for p in LocalRepo(tmp_path / "kho").list_packs())
    st = repo.restore(sid, tmp_path / "ra", include=f["path"])
    out = tmp_path / "ra" / f["path"]
    assert hashlib.sha256(out.read_bytes()).hexdigest() == f["sha256"] and st["verified"] == 1
    print(f"\n[4] khoi phuc 1 file {f['size']:,} byte: tai {st['bytes_downloaded']:,} / {total_packs:,} byte pack")
    assert st["bytes_downloaded"] < f["size"] + 200_000 < total_packs
    full = repo.restore(sid, tmp_path / "ra_full")
    assert full["bytes_downloaded"] == total_packs                       # khoi phuc het: tai ca pack


def test_khoi_phuc_1_file_qua_http_range(tmp_path, data):
    app = create_stub_app(tmp_path / "kho")
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.port}"
        repo = init_repo(HttpRepo(url, backoff=0), PASSWORD, scrypt=FAST_SCRYPT)
        sid = repo.backup([str(data)])["snapshot_id"]
        f = pick_file(repo, sid)
        r = Repository.open(HttpRepo(url, backoff=0), PASSWORD)
        st = r.restore(sid, tmp_path / "ra", include=f["path"])
        assert hashlib.sha256((tmp_path / "ra" / f["path"]).read_bytes()).hexdigest() == f["sha256"]
        assert app.config["stub_state"]["range_bytes"] == st["bytes_downloaded"] < f["size"] + 200_000
    finally:
        srv.shutdown()


def test_sua_mau_cua_file_bi_phat_hien_mau_khac_khong_anh_huong(tmp_path, data):
    repo = new_repo(tmp_path / "kho")
    sid = repo.backup([str(data)])["snapshot_id"]
    f = pick_file(repo, sid)
    snap_entry = next(e for e in repo.load_snapshot(sid)["tree"] if e["path"] == f["path"])
    cid = snap_entry["chunks"][0]
    pid = LocalRepo(tmp_path / "kho").locate_chunks([cid])[cid]
    p = tmp_path / "kho" / "packs" / pid[:2] / pid
    raw = bytearray(p.read_bytes())
    e = next(x for x in packer.read_index(repo.keys, bytes(raw)) if x.id.hex() == cid)
    raw[e.offset + e.length // 2] ^= 0x40                                # sua 1 byte trong blob cua file
    os.chmod(p, 0o600)
    p.write_bytes(bytes(raw))
    r = reopen(tmp_path / "kho")
    with pytest.raises(IntegrityError):
        r.restore(sid, tmp_path / "ra", include=f["path"])
    assert not (tmp_path / "ra" / f["path"]).exists()                    # khong ghi du lieu sai
    other = next(x for x in r.ls(sid) if x["type"] == "file" and x["path"] != f["path"]
                 and pid not in r.backend.locate_chunks(next(e["chunks"] for e in r.load_snapshot(sid)["tree"]
                                                              if e["path"] == x["path"])).values())
    r.restore(sid, tmp_path / "ra2", include=other["path"])              # file khac van lay duoc
    assert r.check()["errors"]                                           # check toan kho van bao loi
