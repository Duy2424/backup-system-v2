"""Tuan 8: dong goi - moi module bien dich duoc, cac lenh `python -m ...` khoi dong duoc, script cai dat in ke hoach dung."""
import compileall
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(*args, timeout=120):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


def test_moi_module_bien_dich_duoc():
    for pkg in ("core", "kho", "server", "agent", "shared", "bench"):
        assert compileall.compile_dir(str(ROOT / pkg), quiet=1, force=True), pkg


@pytest.mark.parametrize("mod", ["core", "kho", "server"])
def test_lenh_m_khoi_dong_duoc(mod):
    r = run("-m", mod, "--help")
    assert r.returncode == 0, r.stderr
    assert "usage" in r.stdout.lower() or "usage" in r.stderr.lower()


def test_core_init_backup_restore_bang_dong_lenh(tmp_path):
    kho, data, out = tmp_path / "kho", tmp_path / "data", tmp_path / "ra"
    data.mkdir()
    (data / "a.txt").write_text("xin chào", encoding="utf-8")
    (data / "b.bin").write_bytes(os.urandom(50_000))
    pw = tmp_path / "pw.txt"
    pw.write_text("mat-khau-demo", encoding="utf-8")
    assert run("-m", "core", "init", "--repo", str(kho), "--password-file", str(pw)).returncode == 0
    r = run("-m", "core", "backup", "--repo", str(kho), "--password-file", str(pw), "--quiet", str(data))
    assert r.returncode == 0 and "Snapshot" in r.stdout, r.stdout + r.stderr
    r = run("-m", "core", "restore", "--repo", str(kho), "--password-file", str(pw), "latest", "--target", str(out), "--quiet")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "data" / "a.txt").read_text(encoding="utf-8") == "xin chào"
    assert run("-m", "core", "check", "--repo", str(kho), "--password-file", str(pw)).returncode == 0


@pytest.mark.skipif(os.name != "nt", reason="script PowerShell cho Windows")
def test_cai_dat_agent_print_only():
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                        str(ROOT / "deploy" / "agent" / "cai_dat_agent.ps1"), "-PrintOnly"], capture_output=True, text=True,
                       timeout=120, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TASK \\BackupSystem\\BackupAgent [AtLogOn" in r.stdout and "RunLevel Highest" in r.stdout and "-B -m agent" in r.stdout
