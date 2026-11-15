"""
Tuan 3 (B): script trien khai kho - Caddyfile mTLS, cap/thu hoi chung chi (openssl), cai dich vu + icacls cam xoa,
tuong lua. Script PowerShell chay -PrintOnly (khong can quyen admin); phan chung chi chay THAT neu may co openssl
(Git for Windows) va kiem tra mTLS that voi API kho.
"""
import os
import shutil
import ssl
import subprocess
import threading
from pathlib import Path

import pytest
import requests
from werkzeug.serving import make_server

from core.errors import RepoError
from core.repo_http import HttpRepo
from core.repository import init_repo
from kho.app import create_app
from tests.core_helpers import FAST_SCRYPT, PASSWORD

DEPLOY = Path(__file__).resolve().parents[1] / "deploy" / "kho"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="script PowerShell cho Windows")


def ps(script, *args, check=True):
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", str(DEPLOY / script), *args], capture_output=True, text=True, timeout=180,
                       encoding="utf-8", errors="replace")
    if check:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


def _openssl():
    for c in (shutil.which("openssl"), r"C:\Program Files\Git\mingw64\bin\openssl.exe",
              r"C:\Program Files\Git\usr\bin\openssl.exe"):
        if c and os.path.isfile(c):
            return c
    return None


def test_caddyfile_bat_buoc_chung_chi_client_va_khong_mo_lenh_xoa():
    text = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    assert "client_auth" in text and "require_and_verify" in text
    assert "trusted_ca_cert_file certs/ca.crt" in text and "import clients.caddy" in text
    assert "reverse_proxy 127.0.0.1:8080" in text and "X-Client-Subject" in text
    assert "max_size 256MB" in text
    assert "method" not in text.lower() or "delete" not in text.lower()


def test_make_certs_print_only_sinh_lenh_dung(tmp_path):
    out = ps("make_certs.ps1", "-InitCA", "-CaddyDir", str(tmp_path), "-PrintOnly").stdout
    assert "req -x509" in out and "CA:TRUE" in out and "ca.key" in out
    out = ps("make_certs.ps1", "-Server", "-San", "IP:100.64.0.9,DNS:pc-kho", "-CaddyDir", str(tmp_path), "-PrintOnly").stdout
    assert "serverAuth" in out and "subjectAltName=IP:100.64.0.9,DNS:pc-kho" in out and "/CN=server" in out
    out = ps("make_certs.ps1", "-Client", "laptop-duy", "-CaddyDir", str(tmp_path), "-PrintOnly").stdout
    assert "clientAuth" in out and "/CN=laptop-duy" in out
    assert "trusted_leaf_cert_file certs/clients/laptop-duy.crt" in out
    r = ps("make_certs.ps1", "-Client", "ten;xau", "-CaddyDir", str(tmp_path), "-PrintOnly", check=False)
    assert r.returncode == 1 and "khong hop le" in r.stdout


@pytest.mark.skipif(_openssl() is None, reason="can openssl (Git for Windows) de tao chung chi that")
def test_chung_chi_that_mtls_kho_tu_choi_khong_co_chung_chi(tmp_path):
    cdir = tmp_path / "caddy"
    cdir.mkdir()
    ps("make_certs.ps1", "-InitCA", "-CaddyDir", str(cdir))
    ps("make_certs.ps1", "-Server", "-San", "IP:127.0.0.1,DNS:localhost", "-CaddyDir", str(cdir))
    ps("make_certs.ps1", "-Client", "laptop-test", "-CaddyDir", str(cdir))
    certs = cdir / "certs"
    for f in ("ca.crt", "ca.key", "server.crt", "server.key", "clients/laptop-test.crt", "clients/laptop-test.key",
              "clients/ca.crt"):
        assert (certs / f).is_file(), f
    allow = (cdir / "clients.caddy").read_text(encoding="utf-8")
    assert "trusted_leaf_cert_file certs/clients/laptop-test.crt" in allow
    cdir2 = tmp_path / "caddy-khac"                                  # CA khac (ke tan cong tu cap chung chi)
    cdir2.mkdir()
    ps("make_certs.ps1", "-InitCA", "-CaddyDir", str(cdir2))
    ps("make_certs.ps1", "-Client", "ke-la", "-CaddyDir", str(cdir2))

    # Mo phong Caddy: TLS server BAT BUOC chung chi client do CA noi bo ky, phia sau la API kho that
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2        # TLS 1.3 tu choi client sau handshake -> client chi thay "mat ket noi"
    ctx.load_cert_chain(str(certs / "server.crt"), str(certs / "server.key"))
    ctx.load_verify_locations(str(certs / "ca.crt"))
    ctx.verify_mode = ssl.CERT_REQUIRED
    srv = make_server("127.0.0.1", 0, create_app(tmp_path / "kho"), threaded=True, ssl_context=ctx)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"https://127.0.0.1:{srv.port}"
    try:
        good = HttpRepo(url, cert=str(certs / "clients/laptop-test.crt"), key=str(certs / "clients/laptop-test.key"),
                        ca=str(certs / "ca.crt"), retries=0)
        init_repo(good, PASSWORD, scrypt=FAST_SCRYPT)
        assert good.list_keys()
        assert requests.get(f"{url}/health", cert=(str(certs / "clients/laptop-test.crt"), str(certs / "clients/laptop-test.key")),
                            verify=str(certs / "ca.crt")).json()["initialized"]
        with pytest.raises(RepoError, match="TLS|mất kết nối"):         # khong co chung chi client -> bi tu choi
            HttpRepo(url, ca=str(certs / "ca.crt"), retries=0).list_keys()
        with pytest.raises(RepoError, match="TLS|mất kết nối"):         # chung chi do CA KHAC ky -> bi tu choi
            HttpRepo(url, cert=str(cdir2 / "certs/clients/ke-la.crt"), key=str(cdir2 / "certs/clients/ke-la.key"),
                     ca=str(certs / "ca.crt"), retries=0).list_keys()
    finally:
        srv.shutdown()

    # Thu hoi: chung chi roi khoi allow-list, file chuyen sang revoked\
    ps("make_certs.ps1", "-Revoke", "laptop-test", "-CaddyDir", str(cdir))
    assert "laptop-test" not in (cdir / "clients.caddy").read_text(encoding="utf-8")
    assert not (certs / "clients/laptop-test.crt").exists()
    assert any(p.name.startswith("laptop-test.") and p.suffix == ".crt" for p in (certs / "revoked").iterdir())


def test_cai_dat_kho_print_only_cam_xoa_dung_thu_muc():
    out = ps("cai_dat_kho.ps1", "-KhoDir", r"D:\kho-test", "-Port", "8081", "-PrintOnly").stdout
    for d in ("packs", "snapshots", "keys"):
        assert rf"CMD icacls.exe D:\kho-test\{d} /deny *S-1-5-19:(OI)(CI)(DE,DC)" in out, d
    assert r"CMD icacls.exe D:\kho-test\tmp /grant *S-1-5-19:(OI)(CI)(M)" in out
    assert r"CMD icacls.exe D:\kho-test /deny *S-1-5-19:(OI)(NP)(IO)(DE)" in out      # config khong xoa duoc
    assert r"CMD icacls.exe D:\kho-test /deny *S-1-5-19:(DC)" in out
    assert "TASK \\BackupSystem\\BackupKho [AtStartup] NT AUTHORITY\\LOCAL SERVICE:" in out
    assert '-B -m kho --kho "D:\\kho-test" --host 127.0.0.1 --port 8081' in out
    out2 = ps("cai_dat_kho.ps1", "-KhoDir", r"D:\kho-test", "-CaddyExe", r"D:\tools\caddy.exe", "-PrintOnly").stdout
    assert "BackupKhoCaddy [AtStartup]" in out2 and "run --config Caddyfile" in out2
    out3 = ps("cai_dat_kho.ps1", "-KhoDir", r"D:\kho-test", "-Uninstall", "-PrintOnly").stdout
    assert "TASK remove" in out3 and "/remove:d" in out3


def test_tuong_lua_print_only_mac_dinh_chan_chi_mo_tailscale():
    out = ps("tuong_lua.ps1", "-InterfaceAlias", "Tailscale", "-PrintOnly").stdout
    assert "DefaultInboundAction Block" in out and "DefaultOutboundAction Allow" in out
    assert "TCP 8443 Allow interface=Tailscale" in out and "TCP 5000 Allow interface=Tailscale" in out
    assert "TCP 8080 Block (moi card)" in out
    assert "REMOVE rule" in ps("tuong_lua.ps1", "-Undo", "-PrintOnly").stdout
