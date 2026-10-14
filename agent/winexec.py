"""Chay PowerShell / cmd tren Windows + kiem tra dau vao chong chen lenh."""
import base64
import logging
import platform
import re
import subprocess

log = logging.getLogger("agent.exec")
IS_WINDOWS = platform.system() == "Windows"

_SAFE = re.compile(r'^[^"&|<>^%\r\n]*$')


def run_ps(script, timeout=120):
    """Chay PowerShell (script qua -EncodedCommand, khong lo loi dau nhay). Tra ve (stdout, returncode)."""
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
