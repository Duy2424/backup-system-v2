"""Test 3e: lenh sqlcmd / Scheduled Task duoc sinh dung (khong can SQL Server, chay -PrintOnly)."""
import os
import subprocess
from pathlib import Path

import pytest

SQL = Path(__file__).resolve().parents[1] / "scripts" / "sql"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="script PowerShell cho Windows")


def ps(script, *args):
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", str(SQL / script), *args, "-PrintOnly"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_file_sql_co_checksum_va_kiem_tra():
    full, diff, log = ((SQL / f).read_text() for f in ("backup_full.sql", "backup_diff.sql", "backup_log.sql"))
    assert "BACKUP DATABASE [$(DB)]" in full and "DIFFERENTIAL" not in full
    assert "WITH DIFFERENTIAL" in diff
    assert "BACKUP LOG [$(DB)]" in log
    for s in (full, diff, log):
        assert "CHECKSUM" in s and "RESTORE VERIFYONLY" in s and "N'$(FILE)'" in s
    assert "SET RECOVERY FULL" in (SQL / "ensure_full_recovery.sql").read_text()
    grant = (SQL / "grant_system.sql").read_text()
    assert "db_backupoperator" in grant and "sysadmin" not in grant.split("--")[0]


@pytest.mark.parametrize("mode,tag,ext", [("Full", "FULL", "bak"), ("Diff", "DIFF", "bak"), ("Log", "LOG", "trn")])
def test_sql_backup_sinh_lenh_dung(mode, tag, ext):
    out = ps("sql_backup.ps1", "-Mode", mode, "-Database", "ShopDB,KhoHang", "-Instance", r"PC\SQLEXPRESS",
             "-OutDir", r"D:\SQLBackup", "-Now", "2026-10-14T01:30:00")
    for db in ("ShopDB", "KhoHang"):
        f = rf"D:\SQLBackup\{db}\{db}_{tag}_20261014_013000.{ext}"
        assert f"-i {SQL / 'ensure_full_recovery.sql'} -v DB={db}" in out
        assert f"-i {SQL / f'backup_{mode.lower()}.sql'} -v DB={db} -v FILE={f}" in out
        assert rf"-S PC\SQLEXPRESS -E -b" in out
        assert ("CHECK msdb" in out) == (mode != "Full")


def test_ten_csdl_la_bi_tu_choi():
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(SQL / "sql_backup.ps1"), "-Mode", "Full", "-Database", "x];DROP DATABASE y;--",
                        "-PrintOnly"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "khong hop le" in r.stdout


def test_register_tasks_3_lich():
    out = ps("register_tasks.ps1", "-Database", "ShopDB", "-OutDir", r"D:\SQLBackup")
    assert out.count("TASK \\BackupSystem\\") == 3
    assert "BackupSQL-Full [Chu Nhat 01:00]" in out
    assert "BackupSQL-Diff [Thu Hai-Thu Bay 01:30]" in out
    assert "BackupSQL-Log [moi 15 phut]" in out
    assert "-Mode Log -Database ShopDB" in out and "grant_system.sql -v DB=ShopDB" in out
    assert "RUN \\BackupSystem\\BackupSQL-Full" in out
