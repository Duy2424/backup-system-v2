"""
Restore (ban v1 toi uu).

  HTTP GET (stream) ──► giai ma (BKP2 GCM / BKUP cu) ──► zstd | gzip ──► tar (stream) ──► thu muc tam
                                                                  (khong luu file .bkup xuong dia)

Sau khi giai nen + XAC THUC xong toan bo moi dong vao du lieu that:
  - so sanh snapshot ban backup voi hien tai (chi bam file nghi ngo: khac mtime)
  - them file thieu, ghi de file khac (tra lai mtime goc)
  - (tuy chon) xoa file thua khong co trong ban backup - MAC DINH TAT
  - (tuy chon) khoi phuc ra thu muc khac thay vi vi tri cu
  - (tuy chon) ap lai cau hinh mang/he thong
"""
import json
import logging
import os
import shutil
import tarfile
import time
from datetime import datetime

import zstandard

from shared import config
from shared.encryption_utils import open_decrypt_stream
from shared.text import vn_int, vn_mb, vn_num
from shared.snapshot import ExcludeMatcher, compare_snapshots, create_snapshot, long_path
from agent import sql_registry, system_state
from agent.remote_storage import RemoteStorageClient

log = logging.getLogger("agent.restore")

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
COPY_BUF = 1024 * 1024


class _CountingReader:
    def __init__(self, raw, on_bytes):
        self.raw, self.on_bytes = raw, on_bytes

    def read(self, n=-1):
        b = self.raw.read(n)
        self.on_bytes(len(b))
        return b


def _open_tar_stream(plain):
    """plain: BufferedReader da giai ma. Tu nhan dien zstd (moi) / gzip (v1 goc)."""
    if plain.peek(4)[:4] == ZSTD_MAGIC:
        return tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(plain), mode="r|")
    return tarfile.open(fileobj=plain, mode="r|*")


def _safe_dest(root, name):
    """Duong dan dich an toan (chan ../, duong dan tuyet doi, o dia)."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or ":" in p for p in parts):
        return None
    dest = os.path.normpath(os.path.join(root, *parts))
    if os.path.commonpath([os.path.abspath(root), os.path.abspath(dest)]) != os.path.abspath(root):
        return None
    return dest


def extract_stream(tar, dest_root, dest_for=None):
    """Giai nen tuan tu (che do stream). Chi file thuong + thu muc. Tra ve (ok, bo_qua).
    dest_for(name) -> duong dan dich (None = bo qua); mac dinh giai nen vao dest_root."""
    ok = skipped = 0
    for m in tar:
        dest = dest_for(m.name) if dest_for else _safe_dest(dest_root, m.name)
        if dest is None or not (m.isfile() or m.isdir()):
            skipped += 1
            continue
        if m.isdir():
            os.makedirs(long_path(dest), exist_ok=True)
            continue
        os.makedirs(long_path(os.path.dirname(dest)), exist_ok=True)
        src = tar.extractfile(m)
        with open(long_path(dest), "wb") as out:
            shutil.copyfileobj(src, out, COPY_BUF)
        try:
            os.utime(long_path(dest), (m.mtime, m.mtime))
        except OSError:
            pass
        ok += 1
    return ok, skipped


def _place(src, dst, mtime=None):
    os.makedirs(long_path(os.path.dirname(dst)), exist_ok=True)
    try:
        os.replace(long_path(src), long_path(dst))          # cung o dia: doi ten, khong chep
    except OSError:
        shutil.copyfile(long_path(src), long_path(dst))
    if mtime:
        os.utime(long_path(dst), (mtime, mtime))


def perform_restore(user, backup_filename, progress_cb=None, dry_run=False, delete_extra=False,
                    target_dir=None, restore_system=True):
    """
    Tra ve {success, dry_run, compare_result, system_diffs, components, backup_date}.
    progress_cb(percent, message) co the nem JobCancelled.
    """
    def progress(p, m):
        if progress_cb:
            progress_cb(int(p), m)
        log.info("[%3d%%] %s", int(p), m)

    t0 = time.perf_counter()
    work_dir = os.path.join(config.RESTORE_TEMP_DIR, f"restore_{datetime.now():%Y%m%d_%H%M%S_%f}")
    extract_dir = os.path.join(work_dir, "x")
    os.makedirs(extract_dir, exist_ok=True)
    try:
        # ===== 1. Tai + giai ma + giai nen (stream) =====
        progress(2, f"Đang tải {backup_filename} ...")
        client = RemoteStorageClient(config.SERVER_URL, user["token"])
        resp = client.download_stream(backup_filename)
        total = int(resp.headers.get("Content-Length") or 0)
        got = [0]
        last = [0.0]

        def on_bytes(n):
            got[0] += n
            now = time.monotonic()
            if total and now - last[0] >= 0.5:
                last[0] = now
                progress(3 + 57 * got[0] / total,
                         f"Đã tải và giải mã {vn_num(got[0] / 1048576, 0)}/{vn_mb(total, 0)}")

        def dest_for(name):
            # Khoi phuc ra thu muc khac: ghi thang _data/... vao dich (khong qua thu muc tam roi chuyen)
            top, _, rest = name.partition("/")
            if target_dir and top == "_data" and rest:
                return None if dry_run else _safe_dest(target_dir, rest)
            return _safe_dest(extract_dir, name)

        try:
            plain = open_decrypt_stream(_CountingReader(resp.raw, on_bytes), user["encryption_key"])
            with _open_tar_stream(plain) as tar:
                n_ok, n_skip = extract_stream(tar, extract_dir, dest_for)
        finally:
            resp.close()
        progress(60, f"Giải nén và xác thực xong: {vn_int(n_ok)} mục" + (f", bỏ qua {n_skip}" if n_skip else ""))

        # ===== 2. Metadata =====
        meta_dir = os.path.join(extract_dir, "_meta")
        with open(os.path.join(meta_dir, "metadata.json"), encoding="utf-8") as f:
            metadata = json.load(f)
        components = metadata.get("components")
        do_files = components is None or "files" in components
        backup_state = {}
        sys_path = os.path.join(meta_dir, "system_state.json")
        if os.path.exists(sys_path):
            with open(sys_path, encoding="utf-8") as f:
                backup_state = json.load(f)
        backup_snap = None
        snap_path = os.path.join(meta_dir, "snapshot.json")
        if do_files and os.path.exists(snap_path):
            with open(snap_path, encoding="utf-8") as f:
                backup_snap = json.load(f)

        compare_result = {"missing": [], "extra": [], "modified": [], "same": [],
                          "summary": {"total_backup": 0, "total_current": 0, "to_add": 0,
                                      "to_delete": 0, "to_overwrite": 0, "unchanged": 0}}
        data_dir = os.path.join(extract_dir, "_data")

        # ===== 3a. Khoi phuc ra thu muc khac: du lieu da duoc ghi thang vao dich luc giai nen =====
        if target_dir and backup_snap is not None:
            progress(65, f"Đã khôi phục {vn_int(len(backup_snap['files']))} file vào {target_dir}")
            compare_result["summary"].update(total_backup=len(backup_snap["files"]),
                                             to_add=len(backup_snap["files"]))
            sys_diffs = []
        else:
            # ===== 3b. So sanh voi hien tai =====
            current_snap = None
            if backup_snap is not None:
                progress(65, "Đang so sánh với dữ liệu hiện tại...")
                current_snap = create_snapshot(metadata.get("paths", []),
                                               matcher=ExcludeMatcher.from_config(config),
                                               reference=backup_snap)
                compare_result = compare_snapshots(backup_snap, current_snap)
                s = compare_result["summary"]
                progress(72, f"So sánh: thêm {s['to_add']}, ghi đè {s['to_overwrite']}, "
                             f"thừa {s['to_delete']}, giữ nguyên {s['unchanged']}")
            sys_diffs = []
            if backup_state and restore_system:
                current_state = system_state.capture_system_state(backup_state.get("components"))
                sys_diffs = system_state.compare_system_state(backup_state, current_state)

            if not dry_run:
                # SQL + Registry (neu co)
                sql_dir = os.path.join(extract_dir, "_sql")
                if restore_system and os.path.isdir(sql_dir):
                    for bak in sorted(f for f in os.listdir(sql_dir) if f.endswith(".bak")):
                        progress(75, f"Khôi phục CSDL {bak}")
                        sql_registry.restore_sql_database(os.path.join(sql_dir, bak), os.path.splitext(bak)[0])
                reg_dir = os.path.join(extract_dir, "_registry")
                if restore_system and os.path.isdir(reg_dir) and os.listdir(reg_dir):
                    progress(78, "Khôi phục Windows Registry")
                    sql_registry.restore_registry(reg_dir)

                if backup_snap is not None and current_snap is not None:
                    if delete_extra:
                        progress(80, f"Xoá {len(compare_result['extra'])} file thừa")
                        for rel in compare_result["extra"]:
                            p = current_snap["files"][rel]["abs_path"]
                            try:
                                os.remove(long_path(p))
                            except OSError as e:
                                log.warning("Không xoá được %s: %s", p, e)
                    todo = compare_result["modified"] + compare_result["missing"]
                    progress(85, f"Ghi {vn_int(len(todo))} file")
                    for rel in todo:
                        info = backup_snap["files"][rel]
                        src = os.path.join(data_dir, rel)
                        if not os.path.exists(long_path(src)) or not info.get("abs_path"):
                            log.warning("Thiếu dữ liệu cho %s trong bản sao lưu", rel)
                            continue
                        try:
                            _place(src, info["abs_path"], info.get("mtime"))
                        except OSError as e:
                            log.warning("Không ghi được %s: %s", info["abs_path"], e)

        secs = time.perf_counter() - t0
        if dry_run:
            progress(100, "Chạy thử xong (không thay đổi gì)")
        else:
            # Bao 100% TRUOC khi doi mang: doi IP/firewall co the cat ket noi toi server.
            progress(100, f"Khôi phục xong trong {vn_num(secs)} giây" +
                     (", đang áp dụng cấu hình hệ thống..." if backup_state and restore_system and not target_dir else ""))
            if backup_state and restore_system and not target_dir:
                system_state.restore_system_state(backup_state)

        return {"success": True, "dry_run": dry_run, "compare_result": compare_result,
                "system_diffs": sys_diffs, "components": components,
                "backup_date": metadata.get("created_at")}
    finally:
        shutil.rmtree(long_path(work_dir), ignore_errors=True)
