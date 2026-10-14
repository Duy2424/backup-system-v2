"""
SQL Server (.bak) va Windows Registry (.reg) cho ban backup "toan bo".
Giu logic v1; them: kiem tra ten CSDL, dung -EncodedCommand cho PowerShell, logging.
"""
import logging
import os
import re

from shared import config
from agent.winexec import IS_WINDOWS, run_cmd, run_ps, safe_arg

log = logging.getLogger("agent.sql")
_DB_NAME = re.compile(r"^[\w\- ]{1,128}$")


def _db_ok(name):
    if not _DB_NAME.match(name or ""):
        log.warning("Bo qua CSDL co ten khong hop le: %r", name)
        return False
    return True


def has_sql_server():
    if not IS_WINDOWS:
        return False
    out, _ = run_ps("Get-Service -Name 'MSSQLSERVER','MSSQL$*' -ErrorAction SilentlyContinue | "
                    "Where-Object {$_.Status -eq 'Running'} | Select-Object -ExpandProperty Name")
    return bool(out.strip())


def list_sql_databases():
    if not IS_WINDOWS:
        return []
    inst = safe_arg(config.SQL_SERVER_INSTANCE)
    query = "SET NOCOUNT ON; SELECT name FROM sys.databases WHERE database_id > 4 AND state_desc='ONLINE'"
    out, rc = run_cmd(f'sqlcmd -S {inst} -E -h -1 -W -Q "{query}"')
    if rc == 0:
        return [l.strip() for l in out.splitlines() if l.strip() and _DB_NAME.match(l.strip())]
    out, rc = run_ps(f'Invoke-Sqlcmd -ServerInstance "{inst}" -Query "{query}" | Select-Object -ExpandProperty name')
    return [l.strip() for l in out.splitlines() if l.strip() and _DB_NAME.match(l.strip())] if rc == 0 else []


def backup_sql_database(db_name, out_dir):
    """BACKUP DATABASE ... WITH CHECKSUM ra out_dir/<db>.bak. Tra ve duong dan hoac None."""
    if not IS_WINDOWS or not _db_ok(db_name):
        return None
    os.makedirs(out_dir, exist_ok=True)
    bak = os.path.join(out_dir, f"{db_name}.bak")
    inst = safe_arg(config.SQL_SERVER_INSTANCE)
    q = f"BACKUP DATABASE [{db_name}] TO DISK=N'{bak}' WITH INIT, CHECKSUM, STATS=10"
    out, rc = run_cmd(f'sqlcmd -S {inst} -E -b -Q "{q}"', timeout=1800)
    if rc != 0 or not os.path.exists(bak):
        out2, _ = run_ps(f'Invoke-Sqlcmd -ServerInstance "{inst}" -Query "{q}" -QueryTimeout 1800 -ErrorAction Stop',
                         timeout=1800)
        out += out2
    if os.path.exists(bak):
        log.info("SQL %s -> %s (%s byte)", db_name, bak, f"{os.path.getsize(bak):,}")
        return bak
    log.warning("Backup CSDL %s that bai: %s", db_name, out[-300:])
    return None


def backup_all_sql(out_dir):
    dbs = config.SQL_DATABASES or list_sql_databases()
    if not dbs:
        log.info("Khong co CSDL nao de backup")
        return []
    return [b for b in (backup_sql_database(d, out_dir) for d in dbs) if b]


def restore_sql_database(bak_path, db_name=None):
    if not IS_WINDOWS:
        return False
    db_name = db_name or os.path.splitext(os.path.basename(bak_path))[0]
    if not _db_ok(db_name):
        return False
    inst = safe_arg(config.SQL_SERVER_INSTANCE)
    q = f"RESTORE DATABASE [{db_name}] FROM DISK=N'{safe_arg(bak_path)}' WITH REPLACE, CHECKSUM, STATS=10"
    out, rc = run_cmd(f'sqlcmd -S {inst} -E -b -Q "{q}"', timeout=1800)
    if rc == 0:
        log.info("Khoi phuc CSDL %s thanh cong", db_name)
        return True
    log.warning("Khoi phuc CSDL %s that bai: %s", db_name, out[-300:])
    return False


REGISTRY_KEYS = [
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
    r"HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion",
    r"HKEY_CURRENT_USER\SOFTWARE",
    r"HKEY_CURRENT_USER\Control Panel",
]


def backup_registry(out_dir):
    if not IS_WINDOWS:
        return []
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for i, key in enumerate(REGISTRY_KEYS):
        path = os.path.join(out_dir, f"reg_{i:02d}_{re.sub(r'[^A-Za-z0-9]+', '_', key)[:50]}.reg")
        out, rc = run_cmd(f'reg export "{key}" "{path}" /y', timeout=120)
        if rc == 0 and os.path.exists(path):
            files.append(path)
        else:
            log.warning("Xuat %s that bai: %s", key, out[:120])
    log.info("Registry: %d/%d khoa", len(files), len(REGISTRY_KEYS))
    return files


def restore_registry(reg_dir):
    if not IS_WINDOWS or not os.path.isdir(reg_dir):
        return
    for name in sorted(f for f in os.listdir(reg_dir) if f.endswith(".reg")):
        out, rc = run_cmd(f'reg import "{safe_arg(os.path.join(reg_dir, name))}"', timeout=120)
        log.log(logging.INFO if rc == 0 else logging.WARNING, "Import %s: %s", name, "OK" if rc == 0 else out[:120])
