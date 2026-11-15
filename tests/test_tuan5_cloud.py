"""Tuan 5 (B): script day kho len cloud Object Lock (rclone copy --immutable, khong sync) va bai thu xoa bi tu choi."""
import os
import subprocess
from pathlib import Path

import pytest

CLOUD = Path(__file__).resolve().parents[1] / "deploy" / "cloud"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="script PowerShell cho Windows")


def ps(script, *args, check=True):
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", str(CLOUD / script), *args, "-PrintOnly"], capture_output=True, text=True, timeout=120,
                       encoding="utf-8", errors="replace")
    if check:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


def test_day_len_cloud_chi_them_khong_sync():
    out = ps("day_len_cloud.ps1", "-KhoDir", r"D:\kho-v2", "-Remote", "b2kho:bucket/kho").stdout
    assert r"RCLONE copy D:\kho-v2 b2kho:bucket/kho --immutable --checksum" in out
    assert "--exclude tmp/**" in out and "--exclude logs/**" in out
    assert r"RCLONE check D:\kho-v2 b2kho:bucket/kho --one-way" in out
    assert "RCLONE sync" not in out and "delete" not in out.lower()
    assert '"type":"cloud"' in out and '"title":"Day kho len cloud: OK"' in out
    out2 = ps("day_len_cloud.ps1", "-KhoDir", r"D:\kho-v2", "-Remote", "b2kho:bucket/kho", "-RcloneConfig", r"D:\rc.conf").stdout
    assert r"--config D:\rc.conf" in out2


def test_day_len_cloud_dang_ky_lich_hang_ngay():
    out = ps("day_len_cloud.ps1", "-KhoDir", r"D:\kho-v2", "-Remote", "b2kho:bucket/kho", "-Register",
             "-NotifyUrl", "http://127.0.0.1:5000/api/notify?token=abc").stdout
    assert "TASK \\BackupSystem\\DayLenCloud [hang ngay 02:30] SYSTEM: powershell.exe" in out
    assert "-Remote \"b2kho:bucket/kho\"" in out and "-NotifyUrl \"http://127.0.0.1:5000/api/notify?token=abc\"" in out


def test_remote_khong_hop_le():
    r = ps("day_len_cloud.ps1", "-Remote", "b2kho:bucket; rm -rf", check=False)
    assert r.returncode == 1 and "khong hop le" in r.stdout


def test_thu_xoa_dung_hard_delete_theo_backend():
    out = ps("thu_xoa_bi_tu_choi.ps1", "-Remote", "b2kho:bucket/kho").stdout
    assert "RCLONE deletefile b2kho:bucket/kho/packs/ab/<pack-id> --b2-hard-delete" in out
    assert "RCLONE lsf b2kho:bucket/kho/packs/ab/<pack-id>" in out and "TU CHOI" in out
    out = ps("thu_xoa_bi_tu_choi.ps1", "-Remote", "s3kho:bucket/kho", "-Backend", "S3", "-File", "snapshots/abc").stdout
    assert "RCLONE deletefile s3kho:bucket/kho/snapshots/abc --s3-versions" in out


def test_rclone_conf_mau_khong_chua_key_that():
    text = (CLOUD / "rclone.conf.example").read_text(encoding="utf-8")
    assert "[b2kho]" in text and "hard_delete = false" in text and "<keyID>" in text and "<applicationKey>" in text
    assert "[miniokho]" in text and "--with-lock" in text and "COMPLIANCE" in text
