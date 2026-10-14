"""
Ham dung chung cho cac script bench: ghi CSV, do byte doc cua tien trinh,
tinh dung luong thu muc, doi don vi.

Moi so do deu ghi ra CSV trong bench/results/ voi cung bo cot (CSV_COLUMNS)
de tuan 9 ve bieu do. 7 cot dau la bat buoc theo ke hoach; cac cot sau la
thong tin bo sung de doc lai so lieu.
"""
import csv
import ctypes
import os
import platform
import re
import socket
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "bench" / "results"

CSV_COLUMNS = [
    "thoi_gian",          # thoi diem bat dau lan chay (ISO 8601, gio may)
    "phien_ban",          # v1 / v2 / restic ...
    "lan_chay",           # 1 = full, 2.. = sau moi lan mutate
    "giay",               # thoi gian chay (giay, dong ho thuc)
    "byte_doc",           # byte tien trinh agent doc tu dia (bo dem IO cua he dieu hanh)
    "byte_gui",           # byte than request gui len kho
    "dung_luong_kho",     # tong dung luong kho sau lan chay
    "may",                # ten may do
    "kich_thuoc_du_lieu", # tong byte du lieu nguon tai lan chay
    "so_file",            # so file trong ban backup
    "mo_ta",              # full / mutate 5% vong 1 ...
    "ghi_chu",            # seed, kich thuoc, che do...
]

_UNITS = {"": 1, "B": 1, "K": 1024, "KB": 1024, "KIB": 1024,
          "M": 1024 ** 2, "MB": 1024 ** 2, "MIB": 1024 ** 2,
          "G": 1024 ** 3, "GB": 1024 ** 3, "GIB": 1024 ** 3}


def setup_console():
    """Tranh UnicodeEncodeError khi in tieng Viet ra pipe/file tren Windows."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def parse_size(text):
    """'500MB' -> 524288000. Don vi he 2 (MB = MiB = 1024^2)."""
    if isinstance(text, int):
        return text
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]*)\s*", str(text))
    if not m or m.group(2).upper() not in _UNITS:
        raise ValueError(f"Kich thuoc khong hop le: {text!r} (vd 500MB, 2GB, 1048576)")
    return int(float(m.group(1)) * _UNITS[m.group(2).upper()])


def fmt_bytes(n):
    if n is None:
        return "-"
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def dir_size(path):
    """Tong byte cua moi file trong thu muc (de quy)."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


def process_read_bytes():
    """
    Tong byte tien trinh hien tai da doc (tu luc khoi dong).
    Windows: GetProcessIoCounters().ReadTransferCount (moi lenh ReadFile, ke ca
    doc file tam). Linux: /proc/self/io rchar. Khong ho tro -> None.
    """
    if platform.system() == "Windows":
        counters = _IoCounters()
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        ok = kernel32.GetProcessIoCounters(ctypes.c_void_p(kernel32.GetCurrentProcess()),
                                           ctypes.byref(counters))
        return counters.ReadTransferCount if ok else None
    try:
        with open("/proc/self/io", encoding="ascii") as f:
            for line in f:
                if line.startswith("rchar:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def hostname():
    return socket.gethostname()


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def append_rows(csv_path, rows):
    """Ghi them dong vao CSV (tao file + header neu chua co). UTF-8 co BOM de Excel doc dung."""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not csv_path.exists() or csv_path.stat().st_size == 0
    with open(csv_path, "a", newline="", encoding="utf-8-sig" if new_file else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if new_file:
            w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in CSV_COLUMNS})


def print_table(rows):
    """In bang ket qua gon cho terminal."""
    head = f"{'ban':<4} {'lan':>3} {'mo ta':<22} {'giay':>8} {'byte doc':>11} {'byte gui':>11} {'kho':>11} {'so file':>7}"
    print(head)
    print("-" * len(head))
    for r in rows:
        print(f"{r['phien_ban']:<4} {r['lan_chay']:>3} {r['mo_ta']:<22} {float(r['giay']):>8.2f} "
              f"{fmt_bytes(r['byte_doc'] if r['byte_doc'] != '' else None):>11} "
              f"{fmt_bytes(r['byte_gui']):>11} {fmt_bytes(r['dung_luong_kho']):>11} {r['so_file']:>7}")
