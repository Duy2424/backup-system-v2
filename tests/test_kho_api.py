"""
Tuan 2-3 (B): API kho THAT (kho/app.py) - 4 lenh chinh, khong co lenh xoa, ma loi theo hop dong, Range,
va dien tap K5 chay thang vao kho that (khong phai stub).
"""
import hashlib
import threading

import pytest
import requests
from werkzeug.serving import make_server

from bench import dien_tap, make_dataset
from core.errors import IntegrityError, NotFound, RepoError
from core.repo_http import HttpRepo
from core.repository import Repository, init_repo
from kho.app import MAX_IDS, create_app
from tests.core_helpers import FAST_SCRYPT, PASSWORD, SMALL, file_hashes


class Kho:
    def __init__(self, root):
        self.app = create_app(root)
        self.srv = make_server("127.0.0.1", 0, self.app, threaded=True)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.port}"
        self.root = root

    def close(self):
        self.srv.shutdown()


@pytest.fixture()
def kho(tmp_path):
    k = Kho(tmp_path / "kho")
    yield k
    k.close()


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    root = tmp_path_factory.mktemp("d") / "du_lieu"
    make_dataset.generate(root, "2MB", seed=23)
    return root


def http(url, **kw):
    kw.setdefault("backoff", 0)
    kw.setdefault("retries", 1)
    return HttpRepo(url, **kw)


def test_bon_lenh_chinh_backup_roi_khoi_phuc_khop_hash(kho, data, tmp_path):
    repo = init_repo(http(kho.url), PASSWORD, SMALL, pack_target=256 * 1024, scrypt=FAST_SCRYPT)
    r1 = repo.backup([str(data)])
    assert r1["stats"]["packs_new"] >= 2
    r2 = Repository.open(http(kho.url), PASSWORD).backup([str(data)])
    assert (r2["stats"]["chunks_new"], r2["stats"]["packs_new"]) == (0, 0)      # lan 2 khong gui lai mau nao
    out = tmp_path / "ra"
    r = Repository.open(http(kho.url), PASSWORD)
    r.restore(r.resolve("latest"), out)
    assert file_hashes(out / "du_lieu") == file_hashes(data)
    assert r.check()["errors"] == []
    # khoi phuc 1 file: chi tai dung mau qua Range (206), khong tai ca pack
    one = next(e["path"] for e in r.load_snapshot(r.resolve("latest"))["tree"] if e["type"] == "file" and e["size"] > 0)
    st = r.restore(r.resolve("latest"), tmp_path / "mot", include=one)
    assert st["files"] == 1 and st["bytes_downloaded"] < kho.app.config["kho_state"]["bytes_in"] / 2
    h = requests.get(f"{kho.url}/health").json()
    assert h["ok"] and h["initialized"] and h["snapshots"] == 2 and h["packs"] == r1["stats"]["packs_new"]
    s = requests.get(f"{kho.url}/stats").json()
    assert s["bytes_on_disk"] > 0 and s["packs_created"] == r1["stats"]["packs_new"] and s["disk"]["free"] > 0


def test_khong_co_lenh_xoa_khong_ghi_de(kho, data):
    repo = init_repo(http(kho.url), PASSWORD, SMALL, pack_target=256 * 1024, scrypt=FAST_SCRYPT)
    sid = repo.backup([str(data)])["snapshot_id"]
    be = http(kho.url)
    first = next(h for e in repo.load_snapshot(sid)["tree"] for h in e.get("chunks", ()))
    pid = be.locate_chunks([first])[first]
    kid = be.list_keys()[0]
    pack_before = be.get_pack(pid)
    for method, path in (("DELETE", f"/packs/{pid}"), ("DELETE", f"/snapshots/{sid}"), ("DELETE", f"/keys/{kid}"),
                         ("DELETE", "/config"), ("POST", f"/packs/{pid}"), ("PATCH", f"/snapshots/{sid}"),
                         ("MOVE", f"/packs/{pid}"), ("DELETE", "/snapshots")):
        r = requests.request(method, kho.url + path, data=b"x")
        assert r.status_code == 405 and r.json()["error"] == "method_not_allowed", (method, path, r.status_code)
    # ghi de pack bang du lieu rac: SHA-256 khac id -> 400, file khong doi
    r = requests.put(f"{kho.url}/packs/{pid}", data=b"rac" * 100)
    assert r.status_code == 200 and r.json()["status"] == "exists"        # id da co: bo qua, khong doc body
    bad = "f" * 64
    r = requests.put(f"{kho.url}/packs/{bad}", data=b"rac" * 100, headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 400 and r.json()["error"] == "hash_mismatch"
    r = requests.put(f"{kho.url}/snapshots/{bad}", data=b"rac" * 100)
    assert r.status_code == 400 and r.json()["error"] == "hash_mismatch"
    assert be.get_pack(pid) == pack_before and be.get_snapshot(sid)
    # body dung cau truc nhung khong phai pack
    junk = b"BSV2PK\x01\x00" + b"\x00" * 100
    r = requests.put(f"{kho.url}/packs/{hashlib.sha256(junk).hexdigest()}", data=junk)
    assert r.status_code == 400 and r.json()["error"] == "bad_pack"
    # config ghi mot lan: giong -> exists, khac -> 409
    cfg = be.get_config()
    assert be.put_config(cfg) == "exists"
    with pytest.raises(RepoError):
        be.put_config(cfg + b" ")
    assert requests.put(f"{kho.url}/config", data=cfg + b" ").status_code == 409
    assert kho.app.config["kho_state"]["rejected"] >= 10


def test_ma_loi_gioi_han_va_range(kho, data):
    repo = init_repo(http(kho.url), PASSWORD, SMALL, pack_target=256 * 1024, scrypt=FAST_SCRYPT)
    sid = repo.backup([str(data)])["snapshot_id"]
    be = http(kho.url)
    first = next(h for e in repo.load_snapshot(sid)["tree"] for h in e.get("chunks", ()))
    pid = be.locate_chunks([first])[first]
    pack = be.get_pack(pid)

    assert requests.get(f"{kho.url}/packs/khong-hex").json()["error"] == "bad_id"
    assert requests.get(f"{kho.url}/packs/{'a' * 64}").status_code == 404
    assert requests.get(f"{kho.url}/khong-co").json()["error"] == "not_found"
    r = requests.post(f"{kho.url}/chunks/missing", json={"ids": ["a" * 64] * (MAX_IDS + 1)})
    assert r.status_code == 413 and r.json()["error"] == "too_many_ids"
    assert requests.post(f"{kho.url}/chunks/missing", json={"ids": ["XYZ"]}).json()["error"] == "bad_request"
    assert requests.post(f"{kho.url}/chunks/missing", json={"ids": ["a" * 64, first]}).json()["missing"] == ["a" * 64]
    # khong co Content-Length (gui chunked) -> 411
    r = requests.put(f"{kho.url}/packs/{'b' * 64}", data=iter([b"abc"]))
    assert r.status_code == 411 and r.json()["error"] == "length_required"
    # Range: duoi pack (footer), doan giua, va sai
    r = requests.get(f"{kho.url}/packs/{pid}", headers={"Range": "bytes=-16"})
    assert r.status_code == 206 and r.content == pack[-16:] and r.headers["ETag"] == f'"{pid}"'
    r = requests.get(f"{kho.url}/packs/{pid}", headers={"Range": "bytes=8-39"})
    assert r.status_code == 206 and r.content == pack[8:40]
    r = requests.get(f"{kho.url}/packs/{pid}", headers={"Range": f"bytes={len(pack) + 10}-"})
    assert r.status_code == 416 and r.json()["error"] == "range_not_satisfiable"
    assert be.get_pack_tail(pid, 16) == pack[-16:]
    with pytest.raises(NotFound):
        be.get_snapshot("c" * 64)
    with pytest.raises(IntegrityError):
        be.put_pack("d" * 64, b"khong khop")


def test_dien_tap_k5_vao_kho_that_moi_lenh_xoa_bi_tu_choi(kho, tmp_path):
    init_repo(http(kho.url), PASSWORD, scrypt=FAST_SCRYPT)
    pw = tmp_path / "pw.txt"
    pw.write_text(PASSWORD, encoding="utf-8")
    rows = dien_tap.main(["k5", "--repo", kho.url, "--password-file", str(pw), "--size", "1MB", "--pack-mb", "1",
                          "--retries", "0", "--workdir", str(tmp_path / "w"), "--csv", str(tmp_path / "dt.csv")])
    *attacks, final = rows
    assert len(attacks) == 7                                   # kho that: khong dung toi config / key
    for r in attacks:
        assert "ket_qua=TU CHOI" in r["ghi_chu"] or "ket_qua=BO QUA (exists)" in r["ghi_chu"], r
    assert "chap_nhan=0 nguyen_ven=co snapshot_con=co digest=khop" in final["ghi_chu"]
    assert "kho=that" in final["ghi_chu"]


def test_ghi_log_subject_chung_chi_client(kho, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="kho"):
        requests.get(f"{kho.url}/health", headers={"X-Client-Subject": "CN=laptop-duy"})
    assert any("CN=laptop-duy GET /health -> 200" in m for m in caplog.messages)
