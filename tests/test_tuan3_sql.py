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


def _pitr(tmp_path, stop):
    d = tmp_path / "ShopDB"
    d.mkdir(exist_ok=True)
    for n in ("ShopDB_FULL_20261011_010000.bak", "ShopDB_DIFF_20261013_013000.bak", "ShopDB_DIFF_20261014_013000.bak",
              "ShopDB_LOG_20261014_014500.trn", "ShopDB_LOG_20261014_100000.trn", "ShopDB_LOG_20261014_101500.trn",
              "ShopDB_LOG_20261014_103000.trn", "ShopDB_LOG_20261012_090000.trn", "ShopDB_FULL_20261018_010000.bak"):
        (d / n).write_bytes(b"")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SQL / "restore_pitr.ps1"),
                        "-Database", "ShopDB", "-StopAt", stop, "-BackupDir", str(tmp_path), "-PrintOnly"],
                       capture_output=True, text=True, timeout=120)
    return r


def test_khoi_phuc_ve_thoi_diem_chon_dung_file(tmp_path):
    r = _pitr(tmp_path, "2026-10-14 10:07:00")
    assert r.returncode == 0, r.stdout + r.stderr
    sql = [l[4:] for l in r.stdout.splitlines() if l.startswith("SQL ")]
    assert "ShopDB_FULL_20261011_010000.bak" in sql[0] and "NORECOVERY" in sql[0] and "MOVE" in sql[0]
    assert "ShopDB_DIFF_20261014_013000.bak" in sql[1]                     # diff moi nhat truoc moc
    logs = [s for s in sql if s.startswith("RESTORE LOG")]
    assert [s.split("ShopDB_LOG_")[1][:15] for s in logs] == ["20261014_014500", "20261014_100000", "20261014_101500"]
    assert all("STOPAT = N'2026-10-14T10:07:00'" in s for s in logs)
    assert sql[-1] == "RESTORE DATABASE [ShopDB_khoiphuc] WITH RECOVERY;"
    assert not any("20261012_090000" in s or "20261018" in s for s in sql)   # log cu / full sau moc bi bo


def test_khoi_phuc_khong_co_full_truoc_moc(tmp_path):
    r = _pitr(tmp_path, "2026-10-10 00:00:00")
    assert r.returncode == 1 and "Khong co ban FULL" in r.stdout


def test_register_tasks_3_lich():
    out = ps("register_tasks.ps1", "-Database", "ShopDB", "-OutDir", r"D:\SQLBackup")
    assert out.count("TASK \\BackupSystem\\") == 3
    assert "BackupSQL-Full [Chu Nhat 01:00]" in out
    assert "BackupSQL-Diff [Thu Hai-Thu Bay 01:30]" in out
    assert "BackupSQL-Log [moi 15 phut]" in out
    assert "-Mode Log -Database ShopDB" in out and "grant_system.sql -v DB=ShopDB" in out
    assert "RUN \\BackupSystem\\BackupSQL-Full" in out


def test_khoi_phuc_thu_sql_hang_tuan():
    out = ps("verify_sql_restore.ps1", "-Database", "ShopDB", "-BackupDir", r"D:\SQLBackup")
    assert "restore_pitr.ps1 -Database ShopDB" in out and "-TargetDatabase ShopDB_kiemtra" in out
    assert "DBCC CHECKDB ([ShopDB_kiemtra])" in out and "DROP DATABASE [ShopDB_kiemtra]" in out
