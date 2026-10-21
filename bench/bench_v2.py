"""
Do v2 (core: FastCDC + khu trung lap + AES-GCM) tren CUNG bo du lieu voi bench_v1.py, kho local.

  lan 1  full tren bo du lieu vua sinh (--seed, --size)
  lan 2  sau mutate --mutate% (vong 1)
  lan 3  sau mutate --mutate% (vong 2)
  sau do khoi phuc snapshot cuoi ra thu muc moi va so digest voi du lieu nguon (kiem chung).

Cot CSV nhu bench_v1 (bench/common.py). Voi kho local:
  byte_gui       = tong byte pack moi + snapshot (dung bang luong se gui qua mang o tuan 3)
  dung_luong_kho = dung luong thu muc kho sau lan chay
Ghi bench/results/v2.csv roi in bang so sanh voi cac dong cung seed/size trong bench/results/v1.csv.

  python bench/bench_v2.py                   # 500MB, seed 2026, 3 lan, mutate 5%
  python bench/bench_v2.py --size 50MB --runs 2
"""
import argparse
import csv
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(REPO))

from bench import make_dataset  # noqa: E402
from bench.common import (RESULTS_DIR, append_rows, dir_size, fmt_bytes, hostname,  # noqa: E402
                          now_iso, power_note, print_table, process_read_bytes, setup_console)
from core.repo_local import LocalRepo  # noqa: E402
from core.repository import init_repo  # noqa: E402

PASSWORD = "bench-v2-mat-khau"


def compare_table(v2_rows, seed, size, v1_csv):
    """Bang so sanh: lan cuoi cung do cua moi phien ban v1 (cung seed + size) voi v2."""
    tag = f"seed={seed} size={size}"
    by_ver = {}
    try:
        with open(v1_csv, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if tag in r.get("ghi_chu", "") and r["mo_ta"] in ("full",) or (tag in r.get("ghi_chu", "") and r["mo_ta"].startswith("mutate")):
                    by_ver.setdefault(r["phien_ban"], {})[int(r["lan_chay"])] = r     # dong sau ghi de dong truoc
    except FileNotFoundError:
        pass
    by_ver["v2"] = {int(r["lan_chay"]): r for r in v2_rows if not r["mo_ta"].startswith("khôi phục")}
    vers = [v for v in ("v1-goc", "v1-toiuu", "v2") if v in by_ver]
    print("\nSO SANH (cung bo du lieu, giay | byte gui | dung luong kho sau lan chay)")
    head = f"{'lan':>3} {'mo ta':<18}" + "".join(f" | {v:^32}" for v in vers)
    print(head)
    print("-" * len(head))
    for i in sorted(by_ver["v2"]):
        cells = []
        for v in vers:
            r = by_ver[v].get(i)
            cells.append(f"{float(r['giay']):7.2f}s {fmt_bytes(int(r['byte_gui'])):>11} {fmt_bytes(int(r['dung_luong_kho'])):>11}"
                         if r else f"{'-':^32}")
        print(f"{i:>3} {by_ver['v2'][i]['mo_ta']:<18}" + "".join(f" | {c}" for c in cells))


def main(argv=None):
    setup_console()
    ap = argparse.ArgumentParser(description="Do v2 tren bo du lieu mau, so voi v1.")
    ap.add_argument("--size", default=make_dataset.SIZE_DEFAULT)
    ap.add_argument("--seed", type=int, default=make_dataset.SEED_DEFAULT)
    ap.add_argument("--mutate", type=float, default=5.0)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--workdir", default=str(REPO / "bench" / "work"))
    ap.add_argument("--csv", default=str(RESULTS_DIR / "v2.csv"))
    ap.add_argument("--v1-csv", default=str(RESULTS_DIR / "v1.csv"))
    ap.add_argument("--no-verify", action="store_true", help="bo qua buoc khoi phuc kiem chung")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)

    work = Path(args.workdir).resolve() / f"v2-{datetime.now():%Y%m%d-%H%M%S}"
    data, kho = work / "du_lieu", work / "kho"
    work.mkdir(parents=True)
    print(f"[bench v2] thu muc lam viec: {work}")
    print(f"[bench v2] sinh du lieu {args.size} seed={args.seed} ...", flush=True)
    ds = make_dataset.generate(data, args.size, args.seed)
    print(f"[bench v2] {ds['so_file']} file, {fmt_bytes(ds['tong_byte'])}, digest {ds['digest'][:16]}")
    repo = init_repo(LocalRepo(kho), PASSWORD)
    note = f"seed={args.seed} size={args.size} digest0={ds['digest'][:12]} kho=local {power_note()}".rstrip()

    rows = []
    for i in range(1, args.runs + 1):
        if i == 1:
            mo_ta = "full"
        else:
            st = make_dataset.mutate(data, args.mutate, args.seed, round_no=i - 1)
            mo_ta = f"mutate {args.mutate:g}% vong {i - 1}"
            print(f"[bench v2] {mo_ta}: {st}")
        start, r0, t0 = now_iso(), process_read_bytes(), time.perf_counter()
        res = repo.backup([str(data)])
        secs, r1 = time.perf_counter() - t0, process_read_bytes()
        s = res["stats"]
        rows.append({
            "thoi_gian": start, "phien_ban": "v2", "lan_chay": i, "giay": f"{secs:.3f}",
            "byte_doc": "" if r0 is None else r1 - r0, "byte_gui": s["bytes_uploaded"],
            "dung_luong_kho": dir_size(kho), "may": hostname(), "kich_thuoc_du_lieu": s["bytes"],
            "so_file": s["files"], "mo_ta": mo_ta,
            "ghi_chu": (f"{note} chunks_new={s['chunks_new']}/{s['chunks']} packs_new={s['packs_new']} "
                        f"files_read={s['files_read']}/{s['files']} snapshot={res['snapshot_id'][:12]}"),
        })
        print(f"[bench v2] lan {i} xong: {secs:.2f}s, mau moi {s['chunks_new']}/{s['chunks']}, "
              f"doc lai {s['files_read']}/{s['files']} file, gui {fmt_bytes(s['bytes_uploaded'])}, "
              f"kho {fmt_bytes(rows[-1]['dung_luong_kho'])}", flush=True)

    if not args.no_verify:
        out = work / "khoi_phuc"
        r0, t0 = process_read_bytes(), time.perf_counter()
        rst = repo.restore(repo.resolve("latest"), out)
        secs, r1 = time.perf_counter() - t0, process_read_bytes()
        ok = make_dataset.dataset_digest(out / "du_lieu") == make_dataset.dataset_digest(data)
        print(f"[bench v2] khoi phuc snapshot cuoi: {secs:.2f}s, {rst['files']} file, doc {rst['packs_read']} pack "
              f"-> digest {'KHOP 100%' if ok else 'KHAC !!!'}")
        rows.append({
            "thoi_gian": now_iso(), "phien_ban": "v2", "lan_chay": args.runs, "giay": f"{secs:.3f}",
            "byte_doc": "" if r0 is None else r1 - r0, "byte_gui": 0, "dung_luong_kho": dir_size(kho),
            "may": hostname(), "kich_thuoc_du_lieu": rst["bytes"], "so_file": rst["files"],
            "mo_ta": f"khôi phục lần {args.runs}",
            "ghi_chu": f"{note} restore packs_read={rst['packs_read']} bytes_from_repo={rst['bytes_downloaded']} "
                       f"digest={'khop' if ok else 'KHAC'}",
        })
        if not ok:
            append_rows(args.csv, rows)
            raise SystemExit("KHOI PHUC KHONG KHOP DU LIEU NGUON")

    append_rows(args.csv, rows)
    print()
    print_table(rows)
    print(f"\n[bench v2] da ghi {len(rows)} dong vao {args.csv}")
    compare_table(rows, args.seed, args.size, args.v1_csv)
    if args.keep:
        print(f"[bench v2] giu lai {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
