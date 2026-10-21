"""
Thi nghiem tuan 7 (E1-E4, phan v2): quet KICH THUOC MAU x MUC NEN tren cung bo du lieu.

Moi to hop: kho moi, full -> mutate 5% -> backup -> mutate 5% -> backup (giong bench_v1/v2).
Ban sao du lieu duoc doc lam nong mot luot truoc khi bam gio (file vua copy lan dau doc cham gap
nhieu lan tren Windows do trinh diet virus quet) -> cung dieu kien cache nong nhu bench_v2.
Cot ghi_chu co nguon=sac / nguon=pinNN%: chi so sanh thoi gian giua cac dong cung nguon.
min = avg/2, max = avg*8 (ti le nhu mac dinh 512K/1M/8M). Muc nen 0 = khong nen.
Ghi bench/results/v2_sweep.csv (cot nhu bench/common.py, phien_ban = "v2 avg=1024K zstd=3")
va in bang tom tat: thoi gian, byte gui lan 2+3, dung luong kho cuoi, ti le khu trung lap.

  python bench/sweep_v2.py                                   # 200MB, avg 256K..4M, zstd 0/1/3/9
  python bench/sweep_v2.py --size 50MB --avg 512,1024 --levels 3
"""
import argparse
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(REPO))

from bench import make_dataset  # noqa: E402
from bench.common import (RESULTS_DIR, append_rows, dir_size, fmt_bytes, hostname, now_iso,  # noqa: E402
                          power_note, setup_console, warm_read)
from core.chunker import ChunkerParams  # noqa: E402
from core.repo_local import LocalRepo  # noqa: E402
from core.repository import init_repo  # noqa: E402


def main(argv=None):
    setup_console()
    ap = argparse.ArgumentParser(description="Quet kich thuoc mau x muc nen (v2).")
    ap.add_argument("--size", default="200MB")
    ap.add_argument("--seed", type=int, default=make_dataset.SEED_DEFAULT)
    ap.add_argument("--mutate", type=float, default=5.0)
    ap.add_argument("--avg", default="256,512,1024,2048,4096", help="KiB, phan cach dau phay")
    ap.add_argument("--levels", default="0,1,3,9", help="muc zstd, 0 = khong nen")
    ap.add_argument("--workdir", default=str(REPO / "bench" / "work"))
    ap.add_argument("--csv", default=str(RESULTS_DIR / "v2_sweep.csv"))
    args = ap.parse_args(argv)

    work = Path(args.workdir).resolve() / f"sweep-{datetime.now():%Y%m%d-%H%M%S}"
    goc = work / "goc" / "du_lieu"
    print(f"[sweep] sinh du lieu {args.size} seed={args.seed} ...", flush=True)
    ds = make_dataset.generate(goc, args.size, args.seed)
    summary = []
    try:
        for avg in [int(x) for x in args.avg.split(",")]:
            for lvl in [int(x) for x in args.levels.split(",")]:
                label = f"v2 avg={avg}K zstd={lvl}"
                case = work / f"a{avg}_z{lvl}"
                data = case / "du_lieu"
                shutil.copytree(goc, data)
                warm_read(data)
                params = ChunkerParams(avg * 512, avg * 1024, avg * 8192)
                repo = init_repo(LocalRepo(case / "kho"), "sweep", params, zstd_level=lvl, scrypt={"n": 2 ** 12})
                rows, logical = [], 0
                for i in range(1, 4):
                    if i > 1:
                        make_dataset.mutate(data, args.mutate, args.seed, round_no=i - 1)
                    nguon = power_note()
                    t0 = time.perf_counter()
                    s = repo.backup([str(data)])["stats"]
                    secs = time.perf_counter() - t0
                    logical += s["bytes"]
                    rows.append({"thoi_gian": now_iso(), "phien_ban": label, "lan_chay": i, "giay": f"{secs:.3f}",
                                 "byte_doc": s["bytes_read"], "byte_gui": s["bytes_uploaded"],
                                 "dung_luong_kho": dir_size(case / "kho"), "may": hostname(),
                                 "kich_thuoc_du_lieu": s["bytes"], "so_file": s["files"],
                                 "mo_ta": "full" if i == 1 else f"mutate {args.mutate:g}% vong {i - 1}",
                                 "ghi_chu": f"seed={args.seed} size={args.size} digest0={ds['digest'][:12]} "
                                            f"chunks={s['chunks']} chunks_new={s['chunks_new']} {nguon}".rstrip()})
                append_rows(args.csv, rows)
                kho = rows[-1]["dung_luong_kho"]
                summary.append((label, float(rows[0]["giay"]), (float(rows[1]["giay"]) + float(rows[2]["giay"])) / 2,
                                rows[1]["byte_gui"] + rows[2]["byte_gui"], kho, logical / kho))
                print(f"[sweep] {label}: full {rows[0]['giay']}s, gui lan 2+3 {fmt_bytes(summary[-1][3])}, "
                      f"kho {fmt_bytes(kho)}", flush=True)
                shutil.rmtree(case, ignore_errors=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{'to hop':<22} {'full s':>7} {'tang s':>7} {'gui 2+3':>11} {'kho cuoi':>11} {'ti le':>6}")
    for label, tf, ti, sent, kho, ratio in summary:
        print(f"{label:<22} {tf:7.2f} {ti:7.2f} {fmt_bytes(sent):>11} {fmt_bytes(kho):>11} {ratio:6.2f}x")
    print(f"\nDa ghi {len(summary) * 3} dong vao {args.csv}  (ti le = du lieu logic 3 snapshot / dung luong kho)")


if __name__ == "__main__":
    main()
