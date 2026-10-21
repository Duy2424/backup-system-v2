"""
So sanh voi restic (tuan 7, E1-E4) tren CUNG bo du lieu, cung kich ban 3 lan nhu bench_v2.py.

*** TOI PHAI TU CHAY ***  Script KHONG tai restic. Tu tai restic.exe ban chinh thuc
(https://github.com/restic/restic/releases, kiem tra SHA256SUMS), dat vao PATH hoac
truyen --restic C:\\duong\\dan\\restic.exe. Neu khong tim thay restic, script dung lai
va khong ghi so do nao.

  lan 1  full tren bo du lieu vua sinh (--seed, --size)
  lan 2  sau mutate --mutate% (vong 1)
  lan 3  sau mutate --mutate% (vong 2)
  sau do khoi phuc snapshot cuoi va so digest voi du lieu nguon.

Cot CSV nhu bench/common.py, ghi bench/results/restic.csv:
  byte_doc       = ReadTransferCount cua TIEN TRINH restic (Windows); may khac de trong
  byte_gui       = data_added_packed trong summary --json (restic >= 0.17); ban cu dung data_added
  dung_luong_kho = dung luong thu muc kho restic sau lan chay
Kho restic dung mac dinh cua no (repo v2, nen zstd auto, pack 16 MiB); cache rieng trong thu muc lam viec.

  python bench/bench_restic.py                       # 500MB, seed 2026 -> so voi v2.csv
  python bench/bench_restic.py --size 200MB --restic D:\\tools\\restic.exe
"""
import argparse
import ctypes
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(REPO))

from bench import make_dataset  # noqa: E402
from bench.common import (RESULTS_DIR, _IoCounters, append_rows, dir_size, fmt_bytes,  # noqa: E402
                          hostname, now_iso, power_note, print_table, setup_console)

PASSWORD = "bench-restic-mat-khau"     # chi dung cho kho thu nghiem, xoa cung thu muc lam viec


def find_restic(arg):
    """Tra ve list lenh goi restic, hoac None neu khong co. Khong bao gio tai ve."""
    if arg:
        parts = shlex.split(arg, posix=False)
        exe = parts[0].strip('"')
        if Path(exe).is_file() or shutil.which(exe):
            return [exe] + parts[1:]
        return None
    exe = shutil.which("restic")
    return [exe] if exe else None


def parse_summary(stdout):
    """Dong {"message_type":"summary",...} cuoi cung trong output --json cua restic backup."""
    found = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("message_type") == "summary":
            found = msg
    if found is None:
        raise RuntimeError("Khong thay dong summary trong output cua restic --json")
    return found


def sent_bytes(summary):
    if "data_added_packed" in summary:
        return int(summary["data_added_packed"]), "data_added_packed"
    return int(summary.get("data_added", 0)), "data_added"


def _child_read_bytes(proc):
    """Byte tien trinh con da doc (Windows), doc tu handle truoc khi Popen bi thu don."""
    if platform.system() != "Windows":
        return None
    try:
        c = _IoCounters()
        ok = ctypes.windll.kernel32.GetProcessIoCounters(ctypes.c_void_p(int(proc._handle)), ctypes.byref(c))
        return c.ReadTransferCount if ok else None
    except (AttributeError, OSError, ValueError):
        return None


def run(cmd, env, cwd=None):
    """Chay restic, tra (giay, stdout, byte doc). Loi -> RuntimeError kem stderr."""
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)
    out, err = proc.communicate()
    secs = time.perf_counter() - t0
    read = _child_read_bytes(proc)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} ... loi {proc.returncode}: "
                           f"{err.decode('utf-8', 'replace').strip()[-800:]}")
    return secs, out.decode("utf-8", "replace"), read


def find_restored(target, name):
    """restic khoi phuc kem duong dan tuyet doi (vd target/D/.../du_lieu) -> tim thu muc `name`."""
    for dirpath, dirnames, _ in os.walk(target):
        if name in dirnames:
            return Path(dirpath) / name
    raise FileNotFoundError(f"Khong thay thu muc {name} trong {target}")


def main(argv=None):
    setup_console()
    ap = argparse.ArgumentParser(description="Do restic tren bo du lieu mau, so voi v2.")
    ap.add_argument("--restic", default=None, help="duong dan restic.exe (mac dinh: tim trong PATH)")
    ap.add_argument("--size", default=make_dataset.SIZE_DEFAULT)
    ap.add_argument("--seed", type=int, default=make_dataset.SEED_DEFAULT)
    ap.add_argument("--mutate", type=float, default=5.0)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workdir", default=str(REPO / "bench" / "work"))
    ap.add_argument("--csv", default=str(RESULTS_DIR / "restic.csv"))
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)

    restic = find_restic(args.restic)
    if not restic:
        print("Khong tim thay restic. Tu tai ban chinh thuc tu github.com/restic/restic/releases "
              "(kiem tra SHA256SUMS), roi chay lai voi --restic <duong dan restic.exe>. Chua ghi so do nao.")
        return 3

    work = Path(args.workdir).resolve() / f"restic-{datetime.now():%Y%m%d-%H%M%S}"
    data, kho = work / "du_lieu", work / "kho"
    work.mkdir(parents=True)
    env = dict(os.environ, RESTIC_PASSWORD=PASSWORD, RESTIC_REPOSITORY=str(kho),
               RESTIC_CACHE_DIR=str(work / "cache"))
    _, ver, _ = run(restic + ["version"], env)
    ver = ver.strip().splitlines()[0] if ver.strip() else "restic ?"
    print(f"[bench restic] {ver}\n[bench restic] thu muc lam viec: {work}")
    print(f"[bench restic] sinh du lieu {args.size} seed={args.seed} ...", flush=True)
    ds = make_dataset.generate(data, args.size, args.seed)
    run(restic + ["init"], env)
    note = f"seed={args.seed} size={args.size} digest0={ds['digest'][:12]} kho=local {ver} {power_note()}".rstrip()

    rows = []
    try:
        for i in range(1, args.runs + 1):
            if i == 1:
                mo_ta = "full"
            else:
                make_dataset.mutate(data, args.mutate, args.seed, round_no=i - 1)
                mo_ta = f"mutate {args.mutate:g}% vong {i - 1}"
            start = now_iso()
            secs, out, read = run(restic + ["backup", "--json", "du_lieu"], env, cwd=str(work))
            s = parse_summary(out)
            sent, field = sent_bytes(s)
            rows.append({
                "thoi_gian": start, "phien_ban": "restic", "lan_chay": i, "giay": f"{secs:.3f}",
                "byte_doc": "" if read is None else read, "byte_gui": sent,
                "dung_luong_kho": dir_size(kho), "may": hostname(),
                "kich_thuoc_du_lieu": s.get("total_bytes_processed", ""),
                "so_file": s.get("total_files_processed", ""), "mo_ta": mo_ta,
                "ghi_chu": (f"{note} byte_gui={field} files_new={s.get('files_new')} "
                            f"files_changed={s.get('files_changed')} snapshot={str(s.get('snapshot_id', ''))[:12]}"),
            })
            print(f"[bench restic] lan {i}: {secs:.2f}s, gui {fmt_bytes(sent)}, kho {fmt_bytes(rows[-1]['dung_luong_kho'])}",
                  flush=True)

        if not args.no_verify:
            out_dir = work / "khoi_phuc"
            secs, _, read = run(restic + ["restore", "latest", "--target", str(out_dir)], env)
            got = find_restored(out_dir, "du_lieu")
            ok = make_dataset.dataset_digest(got) == make_dataset.dataset_digest(data)
            print(f"[bench restic] khoi phuc: {secs:.2f}s -> digest {'KHOP 100%' if ok else 'KHAC !!!'}")
            rows.append({
                "thoi_gian": now_iso(), "phien_ban": "restic", "lan_chay": args.runs, "giay": f"{secs:.3f}",
                "byte_doc": "" if read is None else read, "byte_gui": 0, "dung_luong_kho": dir_size(kho),
                "may": hostname(), "kich_thuoc_du_lieu": "", "so_file": "",
                "mo_ta": f"khôi phục lần {args.runs}", "ghi_chu": f"{note} digest={'khop' if ok else 'KHAC'}",
            })
    finally:
        if rows:
            append_rows(args.csv, rows)
    print()
    print_table(rows)
    print(f"\n[bench restic] da ghi {len(rows)} dong vao {args.csv}")
    if args.keep:
        print(f"[bench restic] giu lai {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
