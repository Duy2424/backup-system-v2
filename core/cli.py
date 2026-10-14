"""
python -m core <lenh> --repo <thu muc kho> ...

  init        tao kho moi (hoi mat khau 2 lan)
  backup      sao luu cac duong dan
  restore     khoi phuc snapshot vao thu muc dich
  snapshots   liet ke snapshot
  check       kiem tra toan ven kho (SHA-256 pack, index, moi mau, snapshot)

Mat khau: --password-file FILE, hoac bien moi truong BACKUP_V2_PASSWORD, hoac nhap tay.
"""
import argparse
import getpass
import json
import os
import sys

from core import packer
from core.chunker import ChunkerParams, KiB
from core.errors import CoreError, WrongPassword
from core.repo_local import LocalRepo
from core.repository import Repository, init_repo
from shared.text import vn_int, vn_mb, vn_num


def _console():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _password(args, confirm=False):
    if args.password_file:
        with open(args.password_file, encoding="utf-8-sig") as f:
            return f.readline().rstrip("\r\n")
    env = os.environ.get("BACKUP_V2_PASSWORD")
    if env:
        return env
    pw = getpass.getpass("Mật khẩu kho: ")
    if confirm and getpass.getpass("Nhập lại: ") != pw:
        raise SystemExit("Hai lần nhập không khớp")
    return pw


def _backend(args):
    return LocalRepo(args.repo)


def _progress(done, total, msg):
    pct = f"{done * 100 / total:5.1f}%" if total else "  ... "
    sys.stderr.write(f"\r{pct} {vn_mb(done, 0)}/{vn_mb(total, 0)}  {msg[-50:]:<50}")
    sys.stderr.flush()


def cmd_init(args):
    params = ChunkerParams(args.min * KiB, args.avg * KiB, args.max * KiB)
    repo = init_repo(_backend(args), _password(args, confirm=True), params, args.pack_size * 1024 * 1024)
    print(f"Đã tạo kho {args.repo} (repo_id {repo.cfg['repo_id']})")
    print("GHI NHỚ MẬT KHẨU: mất mật khẩu = mất dữ liệu. Nên cất bản sao thư mục keys\\ + mật khẩu ở nơi an toàn.")


def cmd_backup(args):
    repo = Repository.open(_backend(args), _password(args))
    res = repo.backup(args.paths, host=args.host, tags=args.tag or (), excludes=args.exclude or (),
                      parent="auto" if args.parent is None else (None if args.parent == "none" else args.parent),
                      progress=None if args.quiet else _progress)
    if not args.quiet:
        sys.stderr.write("\n")
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return
    s = res["stats"]
    print(f"Snapshot {res['snapshot_id'][:12]}" + (f" (cha {res['parent'][:12]})" if res["parent"] else " (đầu tiên)"))
    print(f"  {vn_int(s['files'])} file, {vn_int(s['dirs'])} thư mục, {vn_mb(s['bytes'])}")
    print(f"  đọc lại {vn_int(s['files_read'])} file ({vn_mb(s['bytes_read'])}), "
          f"{vn_int(s['files_cached'])} file không đổi bỏ qua")
    print(f"  mẩu mới {vn_int(s['chunks_new'])}/{vn_int(s['chunks'])} ({vn_mb(s['bytes_new'])} dữ liệu gốc), "
          f"pack mới {s['packs_new']}, gửi {vn_mb(s['bytes_uploaded'])}")
    print(f"  {vn_num(s['seconds'], 2)} giây")
    for e in res["errors"][:10]:
        print(f"  ! bỏ qua {e['path']}: {e['error']}")


def cmd_restore(args):
    repo = Repository.open(_backend(args), _password(args))
    sid = repo.resolve(args.snapshot)
    st = repo.restore(sid, args.target, include=args.include, progress=None if args.quiet else _progress)
    if not args.quiet:
        sys.stderr.write("\n")
    print(f"Khôi phục {sid[:12]} -> {args.target}: {vn_int(st['files'])} file, {vn_int(st['dirs'])} thư mục, "
          f"{vn_mb(st['bytes'])}, đọc {st['packs_read']} pack, {vn_num(st['seconds'], 2)} giây")


def cmd_snapshots(args):
    repo = Repository.open(_backend(args), _password(args))
    snaps = repo.list_snapshots()
    if args.json:
        print(json.dumps(snaps, ensure_ascii=False, indent=1))
        return
    if not snaps:
        print("Kho chưa có snapshot")
        return
    print(f"{'ID':<12}  {'Thời gian':<25}  {'Máy':<16}  {'File':>7}  {'Dữ liệu':>10}  {'Mẩu mới':>8}  Nguồn")
    for s in snaps:
        if "error" in s:
            print(f"{s['id'][:12]}  LỖI: {s['error']}")
            continue
        st = s["stats"]
        print(f"{s['id'][:12]}  {s['time']:<25}  {s['host'][:16]:<16}  {vn_int(st.get('files', 0)):>7}  "
              f"{vn_mb(st.get('bytes', 0)):>10}  {vn_int(st.get('chunks_new', 0)):>8}  {', '.join(s['sources'])}")


def cmd_check(args):
    repo = Repository.open(_backend(args), _password(args))
    rep = repo.check(read_data=not args.fast)
    print(f"{rep['packs']} pack, {vn_int(rep['chunks'])} mẩu, {rep['snapshots']} snapshot")
    if rep["errors"]:
        for e in rep["errors"]:
            print(f"  LỖI: {e}")
        print(f"KHO CÓ LỖI ({len(rep['errors'])})")
        return 1
    print("Kho toàn vẹn." + (" (chỉ kiểm cấu trúc + SHA-256)" if args.fast else ""))
    return 0


def main(argv=None):
    _console()
    ap = argparse.ArgumentParser(prog="python -m core", description="Backup v2: chia mẩu + khử trùng lặp + AES-GCM")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", required=True, help="thư mục kho")
    common.add_argument("--password-file", help="file chứa mật khẩu (dòng đầu)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", parents=[common], help="tạo kho mới")
    p.add_argument("--min", type=int, default=512, help="KiB (mặc định 512)")
    p.add_argument("--avg", type=int, default=1024, help="KiB (mặc định 1024)")
    p.add_argument("--max", type=int, default=8192, help="KiB (mặc định 8192)")
    p.add_argument("--pack-size", type=int, default=packer.DEFAULT_TARGET // (1024 * 1024), help="MiB (mặc định 16)")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("backup", parents=[common], help="sao lưu")
    p.add_argument("paths", nargs="+")
    p.add_argument("--tag", action="append")
    p.add_argument("--host")
    p.add_argument("--exclude", action="append", help="mẫu glob theo tên, lặp lại được")
    p.add_argument("--parent", help="snapshot cha (mặc định tự tìm; 'none' = đọc lại hết)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_backup)

    p = sub.add_parser("restore", parents=[common], help="khôi phục")
    p.add_argument("snapshot", nargs="?", default="latest", help="ID (hoặc vài ký tự đầu) / latest")
    p.add_argument("--target", required=True, help="thư mục đích")
    p.add_argument("--include", help="chỉ khôi phục đường dẫn này (vd du_lieu/van_ban)")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser("snapshots", parents=[common], help="liệt kê snapshot")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_snapshots)

    p = sub.add_parser("check", parents=[common], help="kiểm tra toàn vẹn")
    p.add_argument("--fast", action="store_true", help="không giải mã từng mẩu")
    p.set_defaults(fn=cmd_check)

    args = ap.parse_args(argv)
    try:
        return args.fn(args) or 0
    except WrongPassword as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 3
    except CoreError as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 2
