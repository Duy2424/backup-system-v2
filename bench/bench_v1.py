"""
Do nen (baseline) cho v1: goi THANG agent.backup_logic.perform_backup cua v1
tren bo du lieu mau tat dinh, ghi so do ra CSV.

Mac dinh 3 lan chay tren cung 1 bo du lieu:
  lan 1  full tren bo du lieu vua sinh (--seed, --size)
  lan 2  sau mutate --mutate% (vong 1)
  lan 3  sau mutate --mutate% (vong 2)
v1 luon backup full nen moi lan deu nen + ma hoa + gui lai toan bo.

Server v1:
  * Mac dinh bench TU BAT server v1 o tien trinh rieng (bench/v1_server.py),
    nghe 127.0.0.1, DB + kho nam trong thu muc lam viec cua lan bench.
    Khong can bat server.py bang tay, khong dung toi DB/storage that.
  * Muon do qua mang that (vd PC qua Tailscale): bat server v1 tren may kia
    (server/start_server.bat), lay token user tren trang Admin, roi chay
      python bench/bench_v1.py --server-url http://100.x.y.z:5000 --token <token>
    Khi do byte_gui = kich thuoc .bkup (khong dem duoc o phia server),
    dung_luong_kho = tong .bkup da gui trong lan bench nay.

Do dac (ghi CSV, xem bench/common.py CSV_COLUMNS):
  giay           thoi gian perform_backup (dong ho thuc)
  byte_doc       byte tien trinh agent doc (GetProcessIoCounters), gom ca
                 doc file tam tar.gz/.bkup cua v1
  byte_gui       tong Content-Length cac request agent gui len server
  dung_luong_kho tong dung luong thu muc kho cua server sau lan chay

Mac dinh BO QUA chup system state (PowerShell/netsh) de chi so sanh phan du
lieu file voi v2; them --with-system-state neu muon do ca phan do.

Vi du:
  python bench/bench_v1.py                       # 500MB, seed 2026, 3 lan, mutate 5%
  python bench/bench_v1.py --size 50MB --runs 2  # chay thu nhanh
"""
import argparse
import base64
import json
import os
import platform
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
from bench.common import (RESULTS_DIR, append_rows, dir_size, fmt_bytes, hostname,  # noqa: E402
                          now_iso, print_table, process_read_bytes, setup_console)


def _import_v1(work):
    """Nap module v1 (agent/ + shared/) va chuyen thu muc tam cua v1 vao `work`."""
    for sub in ("shared", "agent"):
        p = str(REPO / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    import config
    config.BACKUP_TEMP_DIR = str(work / "v1_tmp")
    config.SNAPSHOTS_DIR = str(work / "v1_snap")
    os.makedirs(config.BACKUP_TEMP_DIR, exist_ok=True)
    os.makedirs(config.SNAPSHOTS_DIR, exist_ok=True)
    import backup_logic
    return config, backup_logic


def _start_local_server(work):
    log = open(work / "v1_server.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(REPO / "bench" / "v1_server.py"), "--workdir", str(work)],
                            stdout=subprocess.PIPE, stderr=log, text=True, cwd=str(REPO))
    line = proc.stdout.readline()
    if not line:
        proc.wait(5)
        log.close()
        raise RuntimeError("Khong bat duoc server v1:\n" + (work / "v1_server.log").read_text(encoding="utf-8"))
    return proc, json.loads(line)


def _sum_request_bytes(log_path, offset):
    total = 0
    if not log_path.exists():
        return 0, offset
    with open(log_path, "rb") as f:
        f.seek(offset)
        for line in f:
            total += json.loads(line).get("content_length", 0)
        offset = f.tell()
    return total, offset


def main(argv=None):
    setup_console()
    ap = argparse.ArgumentParser(description="Do toc do backup v1 tren bo du lieu mau.")
    ap.add_argument("--size", default=make_dataset.SIZE_DEFAULT)
    ap.add_argument("--seed", type=int, default=make_dataset.SEED_DEFAULT)
    ap.add_argument("--mutate", type=float, default=5.0, help="%% thay doi giua cac lan (mac dinh 5)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workdir", default=str(REPO / "bench" / "work"))
    ap.add_argument("--csv", default=str(RESULTS_DIR / "v1.csv"))
    ap.add_argument("--server-url", help="dung server v1 co san thay vi tu bat (vd http://100.x.y.z:5000)")
    ap.add_argument("--token", help="X-Auth-Token cua user tren server do (bat buoc khi co --server-url)")
    ap.add_argument("--with-system-state", action="store_true", help="do ca buoc chup system state cua v1")
    ap.add_argument("--keep", action="store_true", help="giu lai du lieu + kho sau khi do")
    args = ap.parse_args(argv)
    if args.server_url and not args.token:
        ap.error("--server-url can --token")

    work = Path(args.workdir).resolve() / f"v1-{datetime.now():%Y%m%d-%H%M%S}"
    data = work / "du_lieu"
    work.mkdir(parents=True)
    print(f"[bench v1] thu muc lam viec: {work}")
    print(f"[bench v1] sinh du lieu {args.size} seed={args.seed} ...", flush=True)
    ds = make_dataset.generate(data, args.size, args.seed)
    print(f"[bench v1] {ds['so_file']} file, {fmt_bytes(ds['tong_byte'])}, digest {ds['digest'][:16]}")

    config, backup_logic = _import_v1(work)
    if not args.with_system_state:
        backup_logic.system_state.capture_system_state = lambda: {
            "platform": platform.platform(), "hostname": hostname()}

    proc = None
    if args.server_url:
        config.SERVER_URL = args.server_url.rstrip("/")
        user = {"id": 0, "username": "bench", "token": args.token,
                "encryption_key": base64.urlsafe_b64encode(os.urandom(32)).decode()}
        req_log, kho_dir, che_do = None, None, f"server={config.SERVER_URL}"
    else:
        proc, user = _start_local_server(work)
        config.SERVER_URL = f"http://127.0.0.1:{user['port']}"
        req_log, kho_dir, che_do = work / "v1_requests.jsonl", work / "v1_kho", "server=local"
    print(f"[bench v1] server v1: {config.SERVER_URL}")

    rows, log_off, kho_cong_don = [], 0, 0
    try:
        for i in range(1, args.runs + 1):
            if i == 1:
                mo_ta = "full"
            else:
                st = make_dataset.mutate(data, args.mutate, args.seed, round_no=i - 1)
                mo_ta = f"mutate {args.mutate:g}% vong {i - 1}"
                print(f"[bench v1] {mo_ta}: {st}")
            files = make_dataset.iter_files(data)
            expected, data_bytes = len(files), sum(p.stat().st_size for _, p in files)

            if req_log is not None:
                _, log_off = _sum_request_bytes(req_log, log_off)
            start = now_iso()
            r0 = process_read_bytes()
            t0 = time.perf_counter()
            result = backup_logic.perform_backup(user, paths=[str(data)], components=["files"])
            secs = time.perf_counter() - t0
            r1 = process_read_bytes()

            so_file = result["snapshot_summary"]["total_files"]
            if so_file != expected:
                raise SystemExit(f"v1 chi backup {so_file}/{expected} file (bo loc exclude cua v1 "
                                 f"loai nham?) -> so do khong hop le, dung lai.")
            if req_log is not None:
                time.sleep(0.2)
                byte_gui, log_off = _sum_request_bytes(req_log, log_off)
                kho = dir_size(kho_dir)
            else:
                byte_gui = result["size"]
                kho_cong_don += result["size"]
                kho = kho_cong_don
            rows.append({
                "thoi_gian": start, "phien_ban": "v1", "lan_chay": i, "giay": f"{secs:.3f}",
                "byte_doc": "" if r0 is None else r1 - r0, "byte_gui": byte_gui,
                "dung_luong_kho": kho, "may": hostname(), "kich_thuoc_du_lieu": data_bytes,
                "so_file": so_file, "mo_ta": mo_ta,
                "ghi_chu": (f"seed={args.seed} size={args.size} digest0={ds['digest'][:12]} {che_do} "
                            f"system_state={'co' if args.with_system_state else 'bo_qua'} "
                            f"bkup={result['filename']}"),
            })
            print(f"[bench v1] lan {i} xong: {secs:.2f}s, gui {fmt_bytes(byte_gui)}, kho {fmt_bytes(kho)}",
                  flush=True)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(10)

    append_rows(args.csv, rows)
    print()
    print_table(rows)
    print(f"\n[bench v1] da ghi {len(rows)} dong vao {args.csv}")
    if args.keep:
        print(f"[bench v1] giu lai {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
