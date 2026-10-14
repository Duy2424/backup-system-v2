"""
Backup (ban v1 toi uu).

Luong du lieu - moi file nguon chi DOC 1 LAN, khong ghi file tam:

  file ──► bam SHA-256 ──► tar ──► zstd (da luong) ──► AES-256-GCM theo doan ──► queue ──► HTTP PUT (chunked)
                                                                                 (thread upload)

So voi v1 goc (bam 1 luot + tar.gz 1 luot + doc lai tar + doc lai .bkup + nap ca file vao RAM
khi upload multipart): it doc dia hon ~3 lan, nen nhanh hon, RAM co dinh (~16 MiB).

Cau truc tar (giu tuong thich restore cu):
  _meta/metadata.json, _meta/system_state.json, _sql/*.bak, _registry/*.reg,
  _data/<rel>..., _meta/snapshot.json (cuoi cung vi can hash cua tung file)
"""
import hashlib
import io
import json
import logging
import os
import queue
import re
import shutil
import tarfile
import threading
import time
from datetime import datetime

import zstandard

from shared import config
from shared.encryption_utils import EncryptWriter
from shared.snapshot import ExcludeMatcher, long_path, scan_files
from shared.text import vn_int, vn_mb, vn_num
from agent import sql_registry, system_state
from agent.remote_storage import RemoteStorageClient

log = logging.getLogger("agent.backup")

FORMAT_VERSION = "1.5"
ZSTD_LEVEL = 3
COPY_BUF = 1024 * 1024
_QUEUE_DEPTH = 16          # ~16 MiB dem giua nen va upload


class JobCancelled(Exception):
    """Nguoi dung bam Huy tren web."""


class _Aborted(Exception):
    pass


class _QueueSink:
    """Dau cuoi pipeline: day tung doan da ma hoa vao queue cho thread upload."""

    def __init__(self, q, abort):
        self.q, self.abort = q, abort

    def write(self, b):
        data = bytes(b)
        while True:
            if self.abort.is_set():
                raise _Aborted()
            try:
                self.q.put(data, timeout=0.5)
                return len(data)
            except queue.Full:
                continue


class _Counter(io.RawIOBase):
    """Lop mong cho tarfile (can tell()) + dem byte chua nen."""

    def __init__(self, inner):
        super().__init__()
        self.inner, self.n = inner, 0

    def writable(self):
        return True

    def write(self, b):
        self.inner.write(b)
        self.n += len(b)
        return len(b)

    def tell(self):
        return self.n


class _HashingReader:
    """Doc DUNG `size` byte (tarfile yeu cau), bam SHA-256 tren duong di.
    File bi rut ngan giua chung -> bu 0 va danh dau; file dai them -> chi lay `size` byte."""

    def __init__(self, f, size, on_bytes):
        self.f, self.left, self.on_bytes = f, size, on_bytes
        self.h = hashlib.sha256()
        self.changed = False

    def read(self, n=-1):
        if n is None or n < 0 or n > self.left:
            n = self.left
        parts, got = [], 0
        while got < n:
            b = self.f.read(n - got)
            if not b:
                self.changed = True
                b = b"\x00" * (n - got)
            parts.append(b)
            got += len(b)
        data = b"".join(parts) if len(parts) != 1 else parts[0]
        self.left -= len(data)
        self.h.update(data)
        self.on_bytes(len(data))
        return data


def _add_bytes(tar, name, data, mtime=None):
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    ti.mtime = mtime or time.time()
    tar.addfile(ti, io.BytesIO(data))


def _safe_name(s):
    return re.sub(r"[^A-Za-z0-9_-]", "_", s)[:40] or "user"


def perform_backup(user, paths=None, backup_type="full", components=None, progress_cb=None):
    """
    Backup chon loc theo thanh phan. Tra ve dict:
      {success, filename, size, sha256, components, snapshot_summary, stats}
    progress_cb(percent, message) co the nem JobCancelled de dung.
    """
    t_start = time.perf_counter()

    def progress(p, m, cancellable=True):
        if progress_cb:
            try:
                progress_cb(int(p), m)
            except JobCancelled:
                if cancellable:
                    raise
                # Du lieu da len kho xong: huy luc nay chi de lai file mo coi -> cho hoan tat
        log.info("[%3d%%] %s", int(p), m)

    # ----- thanh phan -----
    comps = [c for c in (components or config.BACKUP_COMPONENTS) if c in config.BACKUP_COMPONENTS]
    comps = comps or list(config.BACKUP_COMPONENTS)
    do_files = "files" in comps
    is_full = set(comps) >= set(config.BACKUP_COMPONENTS)
    backup_type = "full" if is_full else "selected"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{_safe_name(user['username'])}_{stamp}.bkup"
    work_dir = os.path.join(config.BACKUP_TEMP_DIR, filename[:-5])
    os.makedirs(work_dir, exist_ok=True)
    progress(1, f"Bắt đầu sao lưu ({'toàn bộ' if is_full else 'chọn lọc'}): {', '.join(comps)}")

    try:
        # ===== 1. Danh sach file (chi metadata, chua doc noi dung) =====
        file_list, used_paths, skipped = [], [], []
        if do_files:
            used_paths = [p for p in (paths or config.DEFAULT_BACKUP_PATHS) if os.path.exists(p)]
            if not used_paths:
                raise ValueError(f"Không có đường dẫn nào tồn tại để sao lưu: {paths or config.DEFAULT_BACKUP_PATHS}")
            progress(2, "Đang quét thư mục...")
            matcher = ExcludeMatcher.from_config(config)
            file_list = list(scan_files(used_paths, matcher,
                                        on_error=lambda p, e: skipped.append({"path": p, "error": str(e)})))
        total_bytes = sum(st.st_size for _, _, st in file_list)
        if do_files:
            progress(5, f"Tìm thấy {vn_int(len(file_list))} file, {vn_mb(total_bytes)}")

        # ===== 2. System state / SQL / Registry =====
        progress(6, "Đang ghi nhận cấu hình hệ thống...")
        sys_state = system_state.capture_system_state(comps)
        bak_files, reg_files = [], []
        if is_full:
            if sql_registry.has_sql_server():
                progress(8, "Đang sao lưu SQL Server...")
                bak_files = sql_registry.backup_all_sql(os.path.join(work_dir, "sql"))
            progress(10, "Đang xuất Windows Registry...")
            reg_files = sql_registry.backup_registry(os.path.join(work_dir, "registry"))

        # ===== 3. Pipeline tar -> zstd -> AES-GCM -> upload =====
        client = RemoteStorageClient(config.SERVER_URL, user["token"])
        if not client.ping():
            raise ConnectionError(f"Không kết nối được server {config.SERVER_URL}")

        q, abort = queue.Queue(maxsize=_QUEUE_DEPTH), threading.Event()
        upload_result, upload_error = {}, []

        def chunks():
            while True:
                try:
                    item = q.get(timeout=0.5)
                except queue.Empty:
                    if abort.is_set():
                        raise _Aborted() from None
                    continue
                if item is None:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item

        def uploader():
            try:
                upload_result.update(client.upload_stream(filename, chunks()))
            except BaseException as e:      # noqa: BLE001 - chuyen loi ve thread chinh
                upload_error.append(e)
                abort.set()

        th = threading.Thread(target=uploader, name="upload", daemon=True)
        th.start()

        snap_files = {}
        done = [0]
        last_report = [0.0]

        def on_bytes(n):
            done[0] += n
            now = time.monotonic()
            if now - last_report[0] >= 0.5:
                last_report[0] = now
                pct = 12 + 85 * done[0] / total_bytes if total_bytes else 50
                progress(pct, f"Đã xử lý {vn_num(done[0] / 1048576, 0)}/{vn_mb(total_bytes, 0)}")

        enc = zw = None
        try:
            enc = EncryptWriter(_QueueSink(q, abort), user["encryption_key"])
            zw = zstandard.ZstdCompressor(level=ZSTD_LEVEL, threads=-1).stream_writer(
                enc, closefd=False, write_return_read=True)
            counter = _Counter(zw)
            with tarfile.TarFile(fileobj=counter, mode="w", format=tarfile.PAX_FORMAT,
                                 copybufsize=COPY_BUF) as tar:
                meta = {
                    "user_id": user["id"], "username": user["username"],
                    "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "backup_type": backup_type, "components": comps, "paths": used_paths,
                    "version": FORMAT_VERSION, "compression": "zstd", "has_files": do_files,
                    "has_sql": bool(bak_files), "has_registry": bool(reg_files),
                }
                _add_bytes(tar, "_meta/metadata.json", json.dumps(meta, ensure_ascii=False, indent=1).encode())
                _add_bytes(tar, "_meta/system_state.json",
                           json.dumps(sys_state, ensure_ascii=False, default=str).encode())
                for b in bak_files:
                    tar.add(b, arcname=f"_sql/{os.path.basename(b)}")
                for r in reg_files:
                    tar.add(r, arcname=f"_registry/{os.path.basename(r)}")

                for rel, abs_path, st in file_list:
                    try:
                        f = open(long_path(abs_path), "rb")
                    except OSError as e:
                        skipped.append({"path": abs_path, "error": str(e)})
                        done[0] += st.st_size
                        continue
                    with f:
                        ti = tarfile.TarInfo(f"_data/{rel}")
                        ti.size, ti.mtime, ti.mode = st.st_size, st.st_mtime, 0o644
                        hr = _HashingReader(f, st.st_size, on_bytes)
                        tar.addfile(ti, hr)
                    snap_files[rel] = {"abs_path": abs_path, "size": st.st_size, "mtime": st.st_mtime,
                                       "hash": hr.h.hexdigest(),
                                       "attrs": getattr(st, "st_file_attributes", 0)}
                    if hr.changed:
                        snap_files[rel]["changed_during_backup"] = True

                snapshot = {"created_at": meta["created_at"], "paths": used_paths, "files": snap_files,
                            "total_files": len(snap_files),
                            "total_size": sum(v["size"] for v in snap_files.values()),
                            "skipped": skipped[:500]}
                _add_bytes(tar, "_meta/snapshot.json", json.dumps(snapshot, ensure_ascii=False).encode())
            zw.close()
            enc.close()
            q.put(None)
        except BaseException as e:
            abort.set()
            if enc is not None:
                enc.abandon()
            th.join(30)
            if isinstance(e, _Aborted) and upload_error:
                raise upload_error[0] from None
            raise
        progress(97, "Đang chờ server xác nhận...", cancellable=False)
        th.join()
        if upload_error:
            raise upload_error[0]

        secs = time.perf_counter() - t_start
        stats = {"seconds": round(secs, 2), "bytes_source": total_bytes, "bytes_tar": counter.n,
                 "bytes_uploaded": upload_result["size"], "files": len(snap_files), "skipped": len(skipped)}
        msg = (f"Sao lưu xong: {vn_int(len(snap_files))} file, gửi {vn_mb(upload_result['size'])} "
               f"trong {vn_num(secs)} giây")
        if skipped:
            msg += f" (bỏ qua {len(skipped)} file không đọc được)"
        progress(100, msg, cancellable=False)
        return {
            "success": True, "filename": filename, "size": upload_result["size"],
            "sha256": upload_result["sha256"], "components": comps,
            "snapshot_summary": {"total_files": len(snap_files),
                                 "total_size": snapshot["total_size"] if do_files else 0,
                                 "components": comps, "skipped": len(skipped)},
            "stats": stats,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
