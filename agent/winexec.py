"""Chay PowerShell / cmd tren Windows + kiem tra dau vao chong chen lenh."""
import base64
import contextlib
import logging
import platform
import re
import subprocess
import threading

log = logging.getLogger("agent.exec")
IS_WINDOWS = platform.system() == "Windows"

_SAFE = re.compile(r'^[^"&|<>^%\r\n]*$')
_local = threading.local()


@contextlib.contextmanager
def capture():
    """Che do XEM TRUOC: run_cmd/run_ps chi ghi lai lenh (khong chay). Dung de hien ke hoach truoc khi ap."""
    old = getattr(_local, "cmds", None)
    _local.cmds = []
    try:
        yield _local.cmds
    finally:
        _local.cmds = old


def _captured(kind, text):
    cmds = getattr(_local, "cmds", None)
    if cmds is None:
        return False
    cmds.append((kind, text))
    return True


def run_ps(script, timeout=120):
    """Chay PowerShell (script qua -EncodedCommand, khong lo loi dau nhay). Tra ve (stdout, returncode)."""
    if _captured("ps", script):
        return "", 0
    if not IS_WINDOWS:
        return "", 0
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-EncodedCommand", enc], capture_output=True, timeout=timeout)
        out = r.stdout.decode("utf-8", errors="replace")
        if r.returncode != 0:
            out += r.stderr.decode("utf-8", errors="replace")
        return out, r.returncode
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("PowerShell loi: %s", e)
        return str(e), -1


def run_cmd(cmd, timeout=60):
    """Chay lenh cmd (chuoi). Moi gia tri lay tu ban backup phai qua safe_arg() truoc.
    Tra ve (stdout+stderr, returncode)."""
    if _captured("cmd", cmd):
        return "", 0
    if not IS_WINDOWS:
        return "", 0
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True, errors="replace")
        return r.stdout + r.stderr, r.returncode
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Lenh loi (%s): %s", cmd, e)
        return str(e), -1


def safe_arg(value):
    """Chan ky tu co the chen lenh vao chuoi lenh netsh/route/net/reg."""
    s = "" if value is None else str(value)
    if not _SAFE.match(s):
        raise ValueError(f"Gia tri khong an toan: {s!r}")
    return s
