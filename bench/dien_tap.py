"""
Dien tap su co cho loi v2 - ghi so do vao bench/results/dien_tap.csv (cot nhu bench/common.py).

  k1  RANSOMWARE (tuan 8): sao luu tot -> gia lap ma hoa 70% file van ban + sua file moi -> lan sao luu ke tiep phai bi
      CONG CHAN dung (khong gui gi len kho, khong co snapshot moi) -> khoi phuc tu ban tot cuoi, digest khop du lieu goc.
  k2  DUNG LAI MAY KHAC (tuan 8): may cu co SQLBackup (.bak/.trn) + ChiaSe + Web; chi khoi phuc 2 nhanh SQLBackup va
      ChiaSe ra "may moi" (tai dung phan can bang Range), in lenh RESTORE ... STOPAT va New-SmbShare (chay that khi
      --sql-dir + --sql-instance / --share). IIS de sau, dung ke hoach.
  k5  XOA / GHI DE backup phai bi tu choi: dung CHINH chung chi client (nhu ransomware tren may agent)
      gui DELETE / PUT ghi de / POST / PATCH / MOVE toi API kho; sau do tai lai, so SHA-256 -> nguyen ven.
      Kho that: chi tan cong pack + snapshot cua mot bo du lieu tham do vua sao luu (tag dien-tap-k5),
      khong dung toi config / key file / backup that.
  k6  DUT MANG giua chung: lan 1 bi dut -> noi lai -> lan 2 chi gui phan con thieu, khong mau nao gui 2 lan,
      khong co snapshot do dang; cuoi cung khoi phuc va so digest.
  k7  CHIEM BANG THONG: gioi han toc do gui (--limit), do toc do gui thuc te so voi muc dat
      (them 1 lan khong gioi han de doi chung).
  k8  SUA 1 BYTE trong kho: lat 1 bit o 3 cho (vung du lieu pack / bang index pack / snapshot) tren kho TAM,
      chay check nhanh, check day du, khoi phuc -> moi lan deu phai bat duoc va chi dung cho hong.

Che do cho k6/k7:
  mac dinh     kho STUB tren 127.0.0.1 (tests/stub_repo_server.py - KHONG phai API that cua Nguoi B).
               "Dut mang" = stub tra 503 cho moi PUT pack sau N pack. Do duoc ngay tren 1 may.
  --repo URL   API kho that qua Tailscale.  *** TOI PHAI TU CHAY ***
               k6: khi script bao, rut day mang / `tailscale down`; doi bao loi; cam lai roi nhan Enter.
               k7: chay iperf3 song song de chiem bang thong (xem docs/tuan7-thi-nghiem.md).
               Du lieu la bo mau sinh moi (seed theo gio) de chac chan co du lieu moi phai gui; snapshot gan
               tag dien-tap-k6 / dien-tap-k7. Kho phai init truoc; mat khau qua --password-file.
k8 chi chay tren kho local tam trong bench/work (khong bao gio sua kho that).

  python bench/dien_tap.py k8
  python bench/dien_tap.py k5
  python bench/dien_tap.py k6 --size 100MB
  python bench/dien_tap.py k7 --limit 4MB/s
"""
import argparse
import hashlib
import os
import random
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(REPO))

from bench import make_dataset  # noqa: E402
from bench.common import (RESULTS_DIR, append_rows, dir_size, fmt_bytes, hostname, now_iso,  # noqa: E402
                          power_note, setup_console)
from core import packer  # noqa: E402
from core.errors import IntegrityError, RepoError  # noqa: E402
from core.ratelimit import RateLimiter, parse_rate  # noqa: E402
from core.repo_http import HttpRepo  # noqa: E402
from core.repo_local import LocalRepo  # noqa: E402
from core.repository import Repository, init_repo  # noqa: E402

PASSWORD = "dien-tap-mat-khau"
FAST_SCRYPT = {"n": 2 ** 14}


class Counting:
    """Boc backend: dem byte + thoi gian nam trong put_pack (de tinh toc do gui thuc)."""

    def __init__(self, inner):
        self._inner = inner
        self.bytes = self.packs = 0
        self.put_secs = 0.0

    def put_pack(self, pack_id, data):
        t0 = time.perf_counter()
        try:
            r = self._inner.put_pack(pack_id, data)
        finally:
            self.put_secs += time.perf_counter() - t0
        self.bytes += len(data)
        self.packs += 1
        return r

    def __getattr__(self, name):
        return getattr(self._inner, name)


class LocalStub:
    """Stub API kho tren 127.0.0.1 (chi de dien tap/test)."""

    def __init__(self, root, **kw):
        from werkzeug.serving import make_server
        from tests.stub_repo_server import create_stub_app
        self.app = create_stub_app(root, **kw)
        self.state = self.app.config["stub_state"]
        self.srv = make_server("127.0.0.1", 0, self.app, threaded=True)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.port}"

    def close(self):
        self.srv.shutdown()


class LocalKho(LocalStub):
    """API kho THAT (kho/app.py, tuan 2-3 cua Nguoi B) chay tam tren 127.0.0.1 - dung cho K1/K2 (va K5 khi khong --repo)."""

    def __init__(self, root):
        from werkzeug.serving import make_server
        from kho.app import create_app
        self.app = create_app(root)
        self.state = self.app.config["kho_state"]
        self.srv = make_server("127.0.0.1", 0, self.app, threaded=True)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.port}"


def _row(kb, lan, mo_ta, secs, note, **kw):
    r = {"thoi_gian": now_iso(), "phien_ban": f"v2 {kb}", "lan_chay": lan, "giay": f"{secs:.3f}",
         "byte_doc": "", "byte_gui": 0, "dung_luong_kho": "", "may": hostname(),
         "kich_thuoc_du_lieu": "", "so_file": "", "mo_ta": mo_ta, "ghi_chu": note}
    r.update(kw)
    print(f"[{kb}] lan {lan} {mo_ta}: {secs:.2f}s"
          + (f", gui {fmt_bytes(int(r['byte_gui']))}" if r["byte_gui"] else "") + f" | {note}", flush=True)
    return r


def _http(args, url, **kw):
    kw.setdefault("retries", args.retries)
    kw.setdefault("backoff", args.backoff)
    return HttpRepo(url, cert=args.cert, key=args.key, ca=args.ca, **kw)


def _password(args):
    if args.password_file:
        with open(args.password_file, encoding="utf-8-sig") as f:
            return f.readline().rstrip("\r\n")
    return os.environ.get("BACKUP_V2_PASSWORD") or PASSWORD


def _dataset(args, work, name="du_lieu", offset=0):
    """Kho that: seed theo gio (+offset) de du lieu chac chan moi, phai gui het."""
    seed = args.seed if args.seed is not None else (int(time.time()) if args.repo else make_dataset.SEED_DEFAULT)
    seed += offset
    root = work / name
    ds = make_dataset.generate(root, args.size, seed)
    print(f"[dien tap] du lieu {args.size} seed={seed}: {ds['so_file']} file, {fmt_bytes(ds['tong_byte'])}", flush=True)
    return root, ds, seed


# ===================================================================== K5
def _attacks(pid, sid, kid, real):
    junk = os.urandom(64 * 1024)
    out = [("DELETE", f"/packs/{pid}", None, "xoá pack"),
           ("DELETE", f"/snapshots/{sid}", None, "xoá snapshot"),
           ("PUT", f"/packs/{pid}", junk, "ghi đè pack bằng dữ liệu rác"),
           ("PUT", f"/snapshots/{sid}", junk, "ghi đè snapshot bằng dữ liệu rác"),
           ("POST", f"/packs/{pid}", junk, "POST vào pack"),
           ("PATCH", f"/snapshots/{sid}", junk, "PATCH snapshot"),
           ("MOVE", f"/packs/{pid}", None, "MOVE pack (WebDAV)")]
    if not real:
        out += [("DELETE", f"/keys/{kid}", None, "xoá key file"),
                ("DELETE", "/config", None, "xoá config"),
                ("PUT", f"/keys/{kid}", junk, "ghi đè key file"),
                ("PUT", "/config", b'{"format":"gia-mao"}', "ghi đè config")]
    return out


def _verdict(r):
    if isinstance(r, str):
        return "LOI KET NOI"
    if r.status_code >= 300:
        return "TU CHOI"
    try:
        if r.status_code == 200 and r.json().get("status") == "exists":
            return "BO QUA (exists)"
    except ValueError:
        pass
    return "CHAP NHAN !!!"


def k5(args, work):
    import requests
    data, ds, seed = _dataset(args, work)
    note0 = f"seed={seed} size={args.size} {power_note()}".strip()
    stubs, rows = [], []
    try:
        if args.repo:
            backend, note0 = _http(args, args.repo, retries=0), note0 + " kho=that"
            repo = Repository.open(backend, _password(args))
        else:
            stub = LocalStub(work / "kho")
            stubs.append(stub)
            backend, note0 = _http(args, stub.url, retries=0), note0 + " kho=stub-127.0.0.1"
            repo = init_repo(backend, PASSWORD, pack_target=args.pack_mb * 1024 * 1024, scrypt=FAST_SCRYPT)
        sid = repo.backup([str(data)], tags=["dien-tap-k5"])["snapshot_id"]
        h0 = repo.load_snapshot(sid)["tree"]
        first = next(h for e in h0 for h in e.get("chunks", ()))
        pid = backend.locate_chunks([first])[first]
        kid = backend.list_keys()[0]
        before = {"pack": hashlib.sha256(backend.get_pack(pid)).hexdigest(),
                  "snapshot": hashlib.sha256(backend.get_snapshot(sid)).hexdigest(),
                  "key": hashlib.sha256(backend.get_key(kid)).hexdigest(),
                  "config": hashlib.sha256(backend.get_config()).hexdigest()}
        accepted = 0
        for i, (method, path, body, what) in enumerate(_attacks(pid, sid, kid, bool(args.repo)), 1):
            t0 = time.perf_counter()
            try:
                r = backend.s.request(method, backend.base + path, data=body, timeout=30,
                                      headers={"Content-Type": "application/octet-stream"} if body else None)
                code = r.status_code
            except requests.RequestException as e:
                r = code = f"loi:{e.__class__.__name__}"
            v = _verdict(r)
            accepted += v.startswith("CHAP NHAN")
            rows.append(_row("K5", i, f"{what}: {method} {path.split('/')[1] if '/' in path[1:] else path}",
                             time.perf_counter() - t0, f"{note0} ma={code} ket_qua={v}"))
        after = {"pack": hashlib.sha256(backend.get_pack(pid)).hexdigest(),
                 "snapshot": hashlib.sha256(backend.get_snapshot(sid)).hexdigest(),
                 "key": hashlib.sha256(backend.get_key(kid)).hexdigest(),
                 "config": hashlib.sha256(backend.get_config()).hexdigest()}
        intact = before == after and pid == before["pack"] and sid == before["snapshot"]
        still = any(s["id"] == sid for s in backend.list_snapshots())
        out = work / "khoi_phuc"
        t0 = time.perf_counter()
        Repository.open(_http(args, backend.base), _password(args) if args.repo else PASSWORD).restore(sid, out)
        ok = make_dataset.dataset_digest(out / data.name) == make_dataset.dataset_digest(data)
        rows.append(_row("K5", len(rows) + 1, "sau tấn công: tải lại + khôi phục", time.perf_counter() - t0,
                         f"{note0} chap_nhan={accepted} nguyen_ven={'co' if intact else 'KHONG'} "
                         f"snapshot_con={'co' if still else 'KHONG'} digest={'khop' if ok else 'KHAC'}"))
    finally:
        for s in stubs:
            s.close()
        if rows:
            append_rows(args.csv, rows)
    return rows


# ===================================================================== K6
def k6(args, work):
    data, ds, seed = _dataset(args, work)
    base = f"seed={seed} size={args.size} digest0={ds['digest'][:12]} {power_note()}".strip()
    rows, stubs = [], []
    try:
        if args.repo:
            url, note = args.repo, f"{base} kho=that"
            repo = Repository.open(_http(args, url), _password(args))
            ref_bytes = None
        else:
            note = f"{base} kho=stub-127.0.0.1"
            ref = LocalStub(work / "kho_doi_chung")
            stubs.append(ref)
            cnt = Counting(_http(args, ref.url))
            r0 = init_repo(cnt, PASSWORD, pack_target=args.pack_mb * 1024 * 1024, scrypt=FAST_SCRYPT)
            t0 = time.perf_counter()
            st = r0.backup([str(data)])["stats"]
            ref_bytes = cnt.bytes
            rows.append(_row("K6", 0, "đối chứng: không đứt mạng", time.perf_counter() - t0,
                             f"{note} packs={cnt.packs} chunks={st['chunks']}", byte_gui=cnt.bytes,
                             kich_thuoc_du_lieu=st["bytes"], so_file=st["files"]))
            cut_after = max(1, cnt.packs // 2)
            stub = LocalStub(work / "kho", fail_after_packs=cut_after)
            stubs.append(stub)
            url = stub.url
            repo = init_repo(_http(args, url), PASSWORD, pack_target=args.pack_mb * 1024 * 1024, scrypt=FAST_SCRYPT)

        # ---- lan 1: dut giua chung
        cnt1 = Counting(repo.backend)
        repo.backend = cnt1
        if args.repo:
            print("\n>>> Dang sao luu. Khi tien do chay duoc mot luc, RUT DAY MANG hoac `tailscale down`.\n"
                  ">>> Script se bao loi sau khi het so lan thu lai.", flush=True)
        t0 = time.perf_counter()
        result1 = "đứt mạng"
        try:
            repo.backup([str(data)], tags=["dien-tap-k6"], progress=_printer() if args.repo else None)
            result1 = "KHÔNG đứt (mạng nối lại trong lúc tự thử lại)"
        except RepoError as e:
            err1 = str(e)
            print(f"[K6] lan 1 dung voi loi: {err1[:200]}", flush=True)
        secs1 = time.perf_counter() - t0
        snaps_after_cut = len(_http(args, url).list_snapshots()) if not args.repo else ""
        rows.append(_row("K6", 1, f"lần 1: {result1}", secs1,
                         f"{note} packs_gui={cnt1.packs}"
                         + (f" snapshot_tren_kho={snaps_after_cut}" if not args.repo else ""),
                         byte_gui=cnt1.bytes))

        # ---- noi lai, lan 2
        if args.repo:
            input("\n>>> Cam lai mang / `tailscale up`, kiem tra ping toi PC, roi nhan Enter... ")
        else:
            stubs[-1].state["fail_after"] = None
        repo2 = Repository.open(_http(args, url), _password(args) if args.repo else PASSWORD)
        cnt2 = Counting(repo2.backend)
        repo2.backend = cnt2
        t0 = time.perf_counter()
        res2 = repo2.backup([str(data)], tags=["dien-tap-k6"])
        secs2, st2 = time.perf_counter() - t0, res2["stats"]
        extra = ""
        if not args.repo:
            dem = Counter(stubs[-1].state["received"])
            extra = f" mau_gui_2_lan={sum(1 for v in dem.values() if v > 1)}"
        rows.append(_row("K6", 2, "lần 2: sau khi nối lại", secs2,
                         f"{note} chunks_new={st2['chunks_new']}/{st2['chunks']}{extra}"
                         + (f" tong_2_lan/doi_chung={(cnt1.bytes + cnt2.bytes) / ref_bytes:.3f}" if ref_bytes else ""),
                         byte_gui=cnt2.bytes, kich_thuoc_du_lieu=st2["bytes"], so_file=st2["files"]))

        # ---- kiem chung
        out = work / "khoi_phuc"
        t0 = time.perf_counter()
        Repository.open(_http(args, url), _password(args) if args.repo else PASSWORD).restore(res2["snapshot_id"], out)
        ok = make_dataset.dataset_digest(out / data.name) == make_dataset.dataset_digest(data)
        rows.append(_row("K6", 3, "khôi phục kiểm chứng", time.perf_counter() - t0,
                         f"{note} digest={'khop' if ok else 'KHAC'}"))
        if not ok:
            raise SystemExit("K6: KHOI PHUC KHONG KHOP DU LIEU NGUON")
    finally:
        for s in stubs:
            s.close()
        if rows:
            append_rows(args.csv, rows)
    return rows


def _printer():
    last = [0.0]

    def cb(done, total, msg):
        if time.monotonic() - last[0] >= 1 or done >= total:
            last[0] = time.monotonic()
            print(f"  {done * 100 / max(total, 1):5.1f}%  {fmt_bytes(done)}/{fmt_bytes(total)}", flush=True)
    return cb


# ===================================================================== K7
def k7(args, work):
    limit = parse_rate(args.limit)
    rows, stubs = [], []
    try:
        for lan, lim in ((1, None), (2, args.limit)):
            data, ds, seed = _dataset(args, work, f"du_lieu_{lan}", offset=lan)   # moi lan du lieu khac -> gui het
            note = f"seed={seed} size={args.size} {power_note()}".strip()
            if args.repo:
                backend = _http(args, args.repo, limiter=RateLimiter(rate=lim) if lim else None)
                repo = Repository.open(Counting(backend), _password(args))
                note += " kho=that"
            else:
                stub = LocalStub(work / f"kho{lan}")
                stubs.append(stub)
                backend = _http(args, stub.url, limiter=RateLimiter(rate=lim) if lim else None)
                repo = init_repo(Counting(backend), PASSWORD, pack_target=args.pack_mb * 1024 * 1024,
                                 scrypt=FAST_SCRYPT)
                note += " kho=stub-127.0.0.1"
            cnt = repo.backend
            t0 = time.perf_counter()
            st = repo.backup([str(data)], tags=["dien-tap-k7"])["stats"]
            secs = time.perf_counter() - t0
            avg = cnt.bytes / secs                                          # chiem duong truyen trung binh
            burst = cnt.bytes / cnt.put_secs if cnt.put_secs else 0.0       # chi tinh luc dang PUT
            # Token bucket cho don toi da 1 giay khi client ban chia mau -> luc PUT nhanh hon muc dat,
            # nhung trung binh ca lan chay khong vuot muc dat.
            if lim:
                note += (f" gioi_han={args.limit} toc_do_tb={fmt_bytes(avg)}/s lech={(avg - limit) / limit * 100:+.1f}%"
                         f" toc_do_luc_gui={fmt_bytes(burst)}/s")
            else:
                note += f" khong_gioi_han toc_do_tb={fmt_bytes(avg)}/s toc_do_luc_gui={fmt_bytes(burst)}/s"
            rows.append(_row("K7", lan, f"giới hạn {args.limit}" if lim else "không giới hạn (đối chứng)", secs,
                             f"{note} thoi_gian_gui={cnt.put_secs:.2f}s", byte_gui=cnt.bytes,
                             kich_thuoc_du_lieu=st["bytes"], so_file=st["files"]))
            shutil.rmtree(data, ignore_errors=True)
    finally:
        for s in stubs:
            s.close()
        if rows:
            append_rows(args.csv, rows)
    return rows


# ===================================================================== K8
def _flip(path, offset):
    with open(path, "r+b") as f:
        f.seek(offset)
        b = f.read(1)
        f.seek(offset)
        f.write(bytes([b[0] ^ 0x01]))


def _targets(kho):
    """3 cho sua: giua vung du lieu cua pack lon nhat, giua bang index ma hoa cua pack do, giua 1 snapshot."""
    packs = sorted((p for p in (kho / "packs").rglob("*") if p.is_file()), key=lambda p: p.stat().st_size)
    big = packs[-1]
    data = big.read_bytes()
    n, index_len, _ = packer.parse_structure(data)
    idx_start = len(data) - packer.tail_size(index_len, n)
    snap = sorted(p for p in (kho / "snapshots").iterdir() if p.is_file())[-1]
    return [
        ("pack - vùng dữ liệu", big, len(packer.HEADER) + (idx_start - len(packer.HEADER)) // 2),
        ("pack - bảng index", big, idx_start + index_len // 2),
        ("snapshot", snap, snap.stat().st_size // 2),
    ]


def _try(fn):
    t0 = time.perf_counter()
    try:
        r = fn()
        return time.perf_counter() - t0, r, None
    except (IntegrityError, RepoError, ValueError) as e:
        return time.perf_counter() - t0, None, e


def _file_at(repo, sid, pack_path, off):
    """File (trong snapshot) co mau nam dung cho `off` cua pack -> de thu khoi phuc rieng file do."""
    entries = packer.read_index(repo.keys, pack_path.read_bytes())
    e = next(e for e in entries if e.offset <= off < e.offset + e.length)
    h = e.id.hex()
    return next(t["path"] for t in repo.load_snapshot(sid)["tree"] if h in t.get("chunks", ()))


def k8(args, work):
    data, ds, seed = _dataset(args, work)
    kho = work / "kho"
    repo = init_repo(LocalRepo(kho), PASSWORD, pack_target=args.pack_mb * 1024 * 1024, scrypt=FAST_SCRYPT)
    sid = repo.backup([str(data)])["snapshot_id"]
    base = f"seed={seed} size={args.size} {power_note()}".strip()
    rows = []
    try:
        for lan, (where, path, off) in enumerate(_targets(kho), 1):
            one = _file_at(repo, sid, path, off) if lan == 1 else None
            _flip(path, off)
            r = Repository.open(LocalRepo(kho), PASSWORD)
            s_fast, rep_fast, _ = _try(lambda: r.check(read_data=False))
            s_full, rep_full, _ = _try(lambda: r.check(read_data=True))
            out = work / f"khoi_phuc_{lan}"
            s_rst, _, err = _try(lambda: r.restore(sid, out))
            one_note = ""
            if one:     # chi doc dung mau qua Range -> khong qua buoc SHA-256 ca pack, phai nho GCM cua mau
                s_one, _, err_one = _try(lambda: r.restore(sid, work / f"mot_file_{lan}", include=one))
                one_note = f"khoi_phuc_1_file={'TU CHOI' if err_one else 'CHAY XONG'}({s_one:.2f}s) "
            _flip(path, off)                                           # tra lai byte goc
            s_ok, rep_ok, _ = _try(lambda: Repository.open(LocalRepo(kho), PASSWORD).check(read_data=True))
            bat = lambda rep: "BAT" if rep and rep["errors"] else "LOT"  # noqa: E731
            note = (f"{base} file={path.parent.name}/{path.name[:12]} offset={off} "
                    f"check_nhanh={bat(rep_fast)}({s_fast:.2f}s) check_day_du={bat(rep_full)}({s_full:.2f}s) "
                    f"khoi_phuc={'TU CHOI' if err else 'CHAY XONG'}({s_rst:.2f}s) {one_note}"
                    f"loi='{(rep_full or {}).get('errors', ['-'])[0][:90] if rep_full and rep_full['errors'] else err}' "
                    f"sau_khi_tra_byte={'sach' if rep_ok and not rep_ok['errors'] else 'VAN LOI'}")
            rows.append(_row("K8", lan, f"sửa 1 bit: {where}", s_full, note, dung_luong_kho=dir_size(kho)))
            shutil.rmtree(out, ignore_errors=True)
    finally:
        if rows:
            append_rows(args.csv, rows)
    return rows


# ===================================================================== K1 (tuan 8): ransomware -> cong chan -> khoi phuc
RANSOM_TARGETS = (".txt", ".md", ".csv", ".json", ".ini", ".xml", ".docx", ".xlsx")


def _ransomware(root, rng, ratio=0.7):
    """Gia lap ransomware: ghi noi dung ngau nhien (entropy cao) + doi ten .locked cho `ratio` file van ban / van phong,
    sua file moi (canary), de lai thu doi tien chuoc. Tra ve so file bi ma hoa."""
    files = [p for _, p in make_dataset.iter_files(root)
             if p.suffix.lower() in RANSOM_TARGETS and "canary" not in p.name.lower()]
    hit = rng.sample(files, max(1, int(len(files) * ratio)))
    for p in hit:
        p.write_bytes(os.urandom(max(p.stat().st_size, 64)))
        p.rename(p.with_name(p.name + ".locked"))
    for c in root.rglob("~bks_canary*"):
        c.write_bytes(b"DA BI MA HOA " + os.urandom(32))
    (root / "HUONG_DAN_CHUOC.txt").write_bytes(b"Your files are encrypted. Pay 2 BTC to ...")
    return len(hit)


def _open_kho(args, work, stubs, note0):
    """(backend, repo, ghi chu): kho that qua --repo, hoac API kho THAT (kho/app.py) chay tam tren 127.0.0.1."""
    if args.repo:
        backend = _http(args, args.repo)
        return backend, Repository.open(backend, _password(args)), note0 + " kho=that"
    k = LocalKho(work / "kho")
    stubs.append(k)
    backend = _http(args, k.url)
    repo = init_repo(backend, PASSWORD, pack_target=args.pack_mb * 1024 * 1024, scrypt=FAST_SCRYPT)
    return backend, repo, note0 + " kho=api-127.0.0.1"


def k1(args, work):
    """K1: ransomware ma hoa du lieu -> lan sao luu ke tiep bi CONG CHAN dung (khong gui gi len kho)
    -> khoi phuc tu snapshot tot cuoi cung, so digest voi du lieu goc."""
    from core.anomaly import AnomalyDetected
    data, ds, seed = _dataset(args, work)
    (data / "~bks_canary_dung_sua.txt").write_bytes("File mồi - không ai được sửa".encode("utf-8"))
    digest0 = make_dataset.dataset_digest(data)
    note0 = f"seed={seed} size={args.size} {power_note()}".strip()
    stubs, rows = [], []
    try:
        backend, repo, note = _open_kho(args, work, stubs, note0)
        pw = _password(args) if args.repo else PASSWORD
        t0 = time.perf_counter()
        res = repo.backup([str(data)], tags=["dien-tap-k1"])
        sid = res["snapshot_id"]
        rows.append(_row("K1", 1, "sao lưu bình thường", time.perf_counter() - t0,
                         f"{note} snapshot={sid[:12]} chunks={res['stats']['chunks']}",
                         byte_gui=res["stats"]["bytes_uploaded"], so_file=ds["so_file"], kich_thuoc_du_lieu=ds["tong_byte"]))
        snaps_before, packs_before = len(backend.list_snapshots()), None
        n_enc = _ransomware(data, random.Random(seed))
        t0 = time.perf_counter()
        try:
            Repository.open(backend, pw).backup([str(data)], tags=["dien-tap-k1"])
            blocked, reasons = False, "KHONG CHAN - ban bi ma hoa da len kho"
        except AnomalyDetected as e:
            blocked, reasons = True, "; ".join(e.report["reasons"])
        snaps_after = len(backend.list_snapshots())
        rows.append(_row("K1", 2, "ransomware rồi sao lưu: cổng chặn", time.perf_counter() - t0,
                         f"{note} ma_hoa={n_enc} cong_chan={'CHAN' if blocked else 'LOT'} "
                         f"snapshot_moi={snaps_after - snaps_before} ly_do='{reasons[:150]}'"))
        out = work / "khoi_phuc"
        t0 = time.perf_counter()
        st = Repository.open(backend, pw).restore(sid, out)
        ok = make_dataset.dataset_digest(out / data.name) == digest0
        rows.append(_row("K1", 3, "khôi phục từ bản tốt cuối", time.perf_counter() - t0,
                         f"{note} snapshot={sid[:12]} files={st['files']} tai={fmt_bytes(st['bytes_downloaded'])} "
                         f"khop_sha256={st.get('verified', 0)}/{st['files']} digest={'khop' if ok else 'KHAC'}",
                         byte_doc=st["bytes_downloaded"], so_file=st["files"]))
    finally:
        for s in stubs:
            s.close()
        if rows:
            append_rows(args.csv, rows)
    return rows


# ===================================================================== K2 (tuan 8): dung lai CHI CSDL + chia se tren may khac
def _fake_sql_backups(d, rng):
    """File .bak/.trn gia, ten theo quy uoc scripts/sql (FULL 5 ngay truoc, DIFF 1 ngay, LOG moi 15 phut gan day)."""
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    plan = [("FULL", now - timedelta(days=5), "bak", 1_500_000), ("DIFF", now - timedelta(days=1), "bak", 600_000),
            ("LOG", now - timedelta(minutes=45), "trn", 150_000), ("LOG", now - timedelta(minutes=30), "trn", 150_000),
            ("LOG", now - timedelta(minutes=15), "trn", 150_000)]
    for kind, t, ext, size in plan:
        (d / f"ShopDB_{kind}_{t:%Y%m%d_%H%M%S}.{ext}").write_bytes(rng.randbytes(size))


def _hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(root).rglob("*") if p.is_file()}


def k2(args, work):
    """K2: may chu hong -> dung lai CHI CSDL (file .bak/.trn) + thu muc chia se tren MAY KHAC, chua dung IIS:
    chi tai dung 2 nhanh can tu snapshot (Range), in (hoac chay) lenh RESTORE SQL va New-SmbShare."""
    seed = args.seed if args.seed is not None else (int(time.time()) if args.repo else make_dataset.SEED_DEFAULT)
    rng = random.Random(seed)
    may_cu = work / "may_cu"
    share, sqlb, web = may_cu / "ChiaSe", may_cu / "SQLBackup", may_cu / "Web"
    ds = make_dataset.generate(share, args.size, seed)
    if args.sql_dir:
        shutil.copytree(args.sql_dir, sqlb / Path(args.sql_dir).name)
    else:
        _fake_sql_backups(sqlb / "ShopDB", rng)
    web.mkdir(parents=True)
    (web / "index.html").write_bytes(b"<h1>IIS - dung lai o buoc sau</h1>\n" * 2000)
    (web / "web.config").write_bytes(b"<configuration/>")
    print(f"[dien tap] may cu: ChiaSe {ds['so_file']} file, SQLBackup {len(list(sqlb.rglob('*.*')))} file, Web (bo qua khi dung lai)", flush=True)
    note0 = f"seed={seed} size={args.size} {power_note()}".strip()
    stubs, rows = [], []
    try:
        backend, repo, note = _open_kho(args, work, stubs, note0)
        pw = _password(args) if args.repo else PASSWORD
        t0 = time.perf_counter()
        res = repo.backup([str(sqlb), str(share), str(web)], tags=["dien-tap-k2"])
        sid, total_up = res["snapshot_id"], res["stats"]["bytes_uploaded"]
        rows.append(_row("K2", 1, "sao lưu máy cũ: SQLBackup + ChiaSe + Web", time.perf_counter() - t0,
                         f"{note} snapshot={sid[:12]} files={res['stats']['files']}", byte_gui=total_up,
                         so_file=res["stats"]["files"], kich_thuoc_du_lieu=res["stats"]["bytes"]))
        may_moi = work / "may_moi"
        r = Repository.open(backend, pw)
        got = 0
        for lan, inc in ((2, "SQLBackup"), (3, "ChiaSe")):
            t0 = time.perf_counter()
            st = r.restore(sid, may_moi, include=inc)
            got += st["bytes_downloaded"]
            rows.append(_row("K2", lan, f"máy mới: chỉ khôi phục {inc}", time.perf_counter() - t0,
                             f"{note} files={st['files']} tai={fmt_bytes(st['bytes_downloaded'])} "
                             f"khop_sha256={st.get('verified', 0)}/{st['files']}", byte_doc=st["bytes_downloaded"], so_file=st["files"]))
        ok_share = make_dataset.dataset_digest(may_moi / "ChiaSe") == make_dataset.dataset_digest(share)
        ok_sql = _hashes(may_moi / "SQLBackup") == _hashes(sqlb)
        web_restored = (may_moi / "Web").exists()

        sql_new = may_moi / "SQLBackup" / (Path(args.sql_dir).name if args.sql_dir else "ShopDB")
        db = sql_new.name
        stop_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inst = args.sql_instance or r"<may-moi>\SQLEXPRESS"
        cmd_sql = (f'powershell -ExecutionPolicy Bypass -File scripts\\sql\\restore_pitr.ps1 -Database {db} '
                   f'-BackupDir "{sql_new.parent}" -Instance "{inst}" -StopAt "{stop_at}" -TargetDatabase {db}_k2')
        cmd_share = f'New-SmbShare -Name ChiaSe -Path "{may_moi / "ChiaSe"}" -ChangeAccess "Users"'
        sql_result = "chua chay (can --sql-dir <thu muc .bak that> va --sql-instance)"
        if args.sql_instance and args.sql_dir:
            t0 = time.perf_counter()
            p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                                str(REPO / "scripts" / "sql" / "restore_pitr.ps1"), "-Database", db, "-BackupDir", str(sql_new.parent),
                                "-Instance", args.sql_instance, "-StopAt", stop_at, "-TargetDatabase", f"{db}_k2", "-Replace"],
                               capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace")
            print(p.stdout[-1500:], flush=True)
            sql_result = f"restore_pitr ma {p.returncode} ({time.perf_counter() - t0:.1f}s) -> CSDL {db}_k2"
        share_result = "chua chay (them --share, can Administrator)"
        if args.share:
            p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd_share],
                               capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
            share_result = f"New-SmbShare ma {p.returncode}"
        rows.append(_row("K2", 4, "máy mới: dựng lại CSDL + chia sẻ, bỏ qua Web", 0.0,
                         f"{note} tai_mot_phan={fmt_bytes(got)}/{fmt_bytes(total_up)} web_bo_qua={'co' if not web_restored else 'KHONG'} "
                         f"chia_se={'khop' if ok_share else 'KHAC'} sql_file={'khop' if ok_sql else 'KHAC'} sql='{sql_result}' share='{share_result}'"))
        print("\nLenh dung lai tren may moi:\n  " + cmd_sql + "\n  " + cmd_share, flush=True)
    finally:
        for s in stubs:
            s.close()
        if rows:
            append_rows(args.csv, rows)
    return rows


def main(argv=None):
    setup_console()
    ap = argparse.ArgumentParser(description="Dien tap su co K1/K2 (tuan 8), K5/K6/K7/K8 (tuan 7) cho loi v2.")
    ap.add_argument("kich_ban", choices=["k1", "k2", "k5", "k6", "k7", "k8"])
    ap.add_argument("--size", default=None, help="k1: 20MB, k2: 20MB, k5: 5MB, k6: 100MB, k7: 40MB, k8: 30MB")
    ap.add_argument("--sql-dir", help="k2: thu muc .bak/.trn THAT (vd D:\\SQLBackup\\ShopDB) thay cho file gia")
    ap.add_argument("--sql-instance", help="k2: chay restore_pitr.ps1 that len instance nay (vd (localdb)\\MSSQLLocalDB)")
    ap.add_argument("--share", action="store_true", help="k2: tao SMB share that (can Administrator)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--limit", default="4MB/s", help="k7: muc gioi han")
    ap.add_argument("--pack-mb", type=int, default=4, help="kich thuoc pack muc tieu (MiB) cho kho moi")
    ap.add_argument("--repo", help="URL API kho that (bo trong = stub 127.0.0.1)")
    ap.add_argument("--cert")
    ap.add_argument("--key")
    ap.add_argument("--ca")
    ap.add_argument("--password-file")
    ap.add_argument("--retries", type=int, default=3, help="so lan thu lai khi loi mang")
    ap.add_argument("--backoff", type=float, default=0.5)
    ap.add_argument("--workdir", default=str(REPO / "bench" / "work"))
    ap.add_argument("--csv", default=str(RESULTS_DIR / "dien_tap.csv"))
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    if args.kich_ban == "k8" and args.repo:
        ap.error("k8 chi chay tren kho local tam, khong sua kho that")
    args.size = args.size or {"k1": "20MB", "k2": "20MB", "k5": "5MB", "k6": "100MB", "k7": "40MB", "k8": "30MB"}[args.kich_ban]

    work = Path(args.workdir).resolve() / f"{args.kich_ban}-{datetime.now():%Y%m%d-%H%M%S}"
    work.mkdir(parents=True)
    try:
        rows = {"k1": k1, "k2": k2, "k5": k5, "k6": k6, "k7": k7, "k8": k8}[args.kich_ban](args, work)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    print(f"\n[dien tap] da ghi {len(rows)} dong vao {args.csv}")
    return rows


if __name__ == "__main__":
    main()
