"""
Test tuan 3: backup qua HTTP (stub API kho), dut mang giua chung, thu lai, mTLS that, toc do.
Stub chi de test - API kho that do Nguoi B viet.
"""
import ipaddress
import ssl
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from werkzeug.serving import make_server

from bench import make_dataset
from core.errors import IntegrityError, NotFound, RepoError
from core.repo_http import HttpRepo
from core.repository import Repository, init_repo
from tests.core_helpers import FAST_SCRYPT, PASSWORD, file_hashes, write
from tests.stub_repo_server import create_stub_app


class Stub:
    def __init__(self, root, ssl_context=None, **kw):
        self.app = create_stub_app(root, **kw)
        self.state = self.app.config["stub_state"]
        self.srv = make_server("127.0.0.1", 0, self.app, threaded=True, ssl_context=ssl_context)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"{'https' if ssl_context else 'http'}://127.0.0.1:{self.srv.port}"

    def close(self):
        self.srv.shutdown()


@pytest.fixture()
def stub(tmp_path):
    stubs = []

    def make(**kw):
        s = Stub(tmp_path / f"kho{len(stubs)}", **kw)
        stubs.append(s)
        return s
    yield make
    for s in stubs:
        s.close()


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    root = tmp_path_factory.mktemp("d") / "du_lieu"
    make_dataset.generate(root, "6MB", seed=31)
    return root


def http(url, **kw):
    kw.setdefault("backoff", 0)
    kw.setdefault("retries", 2)
    return HttpRepo(url, **kw)


# ---------------------------------------------------------------- 3a/3c backup + restore qua HTTP
def test_backup_restore_qua_http_khop_hash(stub, data, tmp_path):
    s = stub()
    repo = init_repo(http(s.url), PASSWORD, scrypt=FAST_SCRYPT)
    r1 = repo.backup([str(data)])
    r2 = Repository.open(http(s.url), PASSWORD).backup([str(data)])
    assert (r2["stats"]["chunks_new"], r2["stats"]["packs_new"]) == (0, 0)
    out = tmp_path / "ra"
    repo2 = Repository.open(http(s.url), PASSWORD)
    repo2.restore(repo2.resolve("latest"), out)
    assert file_hashes(out / "du_lieu") == file_hashes(data)
    assert repo2.check()["errors"] == []                          # check qua HTTP (khong co list_packs)
    assert len(s.state["received"]) == len(set(s.state["received"])) == r1["stats"]["chunks_new"]


# ---------------------------------------------------------------- 3b dut mang giua chung
def test_dut_mang_sau_n_pack_chay_lai_khong_gui_trung(stub, data, tmp_path):
    s = stub(fail_after_packs=2)
    repo = init_repo(http(s.url), PASSWORD, pack_target=256 * 1024, scrypt=FAST_SCRYPT)
    with pytest.raises(RepoError):
        repo.backup([str(data)])
    assert s.state["packs_ok"] == 2
    da_gui = set(s.state["received"])
    assert http(s.url).list_snapshots() == []                     # chua co snapshot: khong ai thay ban do dang

    s.state["fail_after"] = None                                   # "cam lai day mang"
    res = Repository.open(http(s.url), PASSWORD).backup([str(data)])
    st = res["stats"]
    print(f"\n[3b] lan 1 gui {len(da_gui)} mau roi dut; lan 2 gui them {st['chunks_new']}/{st['chunks']} mau")
    dem = Counter(s.state["received"])
    assert max(dem.values()) == 1                                  # khong mau nao gui 2 lan
    assert st["chunks_new"] == len(set(dem)) - len(da_gui)
    out = tmp_path / "ra"
    r = Repository.open(http(s.url), PASSWORD)
    r.restore(res["snapshot_id"], out)
    assert file_hashes(out / "du_lieu") == file_hashes(data)


def test_loi_tam_thoi_tu_thu_lai(stub, data):
    s = stub(flaky=3)
    init_repo(http(s.url, retries=5), PASSWORD, scrypt=FAST_SCRYPT).backup([str(data)])
    assert s.state["flaky"] == 0 and http(s.url).list_snapshots()


def test_ma_loi_duoc_chuyen_dung_kieu(stub):
    s = stub()
    c = http(s.url)
    with pytest.raises(NotFound):
        c.get_pack("a" * 64)
    with pytest.raises(IntegrityError):
        c.put_pack("b" * 64, b"khong khop sha")
    with pytest.raises(RepoError):
        http(s.url).put_config(b"{}") and http(s.url).put_config(b'{"khac":1}')
    import requests
    assert requests.delete(f"{s.url}/packs/{'a' * 64}").status_code == 405       # khong co lenh xoa


def test_het_lan_thu_thi_bao_loi_ro(stub):
    s = stub(flaky=10)
    with pytest.raises(RepoError, match="thất bại sau 3 lần"):
        http(s.url, retries=2).list_snapshots()


# ---------------------------------------------------------------- mTLS that
def _cert(subject, issuer_key, issuer_name, key, ca=False, server=False):
    now = datetime.now(timezone.utc)
    b = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer_name).public_key(key.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
         .not_valid_after(now + timedelta(days=1))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
    if server:
        b = b.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
        b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
    elif not ca:
        b = b.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), False)
    return b.sign(issuer_key, hashes.SHA256())


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    d = tmp_path_factory.mktemp("pki")
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM)                      # noqa: E731
    kpem = lambda k: k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,   # noqa: E731
                                     serialization.NoEncryption())
    name = lambda cn: x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])        # noqa: E731
    ca_key, srv_key, cli_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    ca = _cert(name("CA thu"), ca_key, name("CA thu"), ca_key, ca=True)
    srv = _cert(name("kho"), ca_key, ca.subject, srv_key, server=True)
    cli = _cert(name("laptop-duy"), ca_key, ca.subject, cli_key)
    for n, b in {"ca.pem": pem(ca), "srv.pem": pem(srv), "srv.key": kpem(srv_key),
                 "cli.pem": pem(cli), "cli.key": kpem(cli_key)}.items():
        (d / n).write_bytes(b)
    return d


def test_mtls_bat_buoc_chung_chi_client(stub, pki, tmp_path):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(pki / "srv.pem", pki / "srv.key")
    ctx.load_verify_locations(pki / "ca.pem")
    ctx.verify_mode = ssl.CERT_REQUIRED
    s = stub(ssl_context=ctx)
    with pytest.raises(RepoError):                                 # khong co chung chi client
        http(s.url, ca=str(pki / "ca.pem"), retries=0).list_snapshots()
    with pytest.raises(RepoError):                                 # khong tin CA cua server
        http(s.url, cert=str(pki / "cli.pem"), key=str(pki / "cli.key"), retries=0).list_snapshots()
    c = http(s.url, cert=str(pki / "cli.pem"), key=str(pki / "cli.key"), ca=str(pki / "ca.pem"))
    src = tmp_path / "nho"
    write(src / "a.txt", "qua mTLS".encode())
    repo = init_repo(c, PASSWORD, scrypt=FAST_SCRYPT)
    repo.backup([str(src)])
    repo.restore(repo.resolve("latest"), tmp_path / "ra")
    assert (tmp_path / "ra" / "nho" / "a.txt").read_text(encoding="utf-8") == "qua mTLS"
