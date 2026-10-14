"""
Thao tac muc cao tren kho v2: init, open, backup, restore, snapshots, check.

Backup (docs/repo-format.md muc 11):
  1. quet -> moi file: neu (path, size, mtime) giong snapshot truoc thi lay lai danh sach mau
     (KHONG doc file); nguoc lai doc + cat FastCDC + tinh chunk ID
  2. hoi kho "thieu mau nao" theo lo (<= 1000 ID / <= 32 MiB du lieu cho)
  3. chi mau thieu: nen + ma hoa + gom pack ~16 MiB -> put_pack
  4. SAU CUNG: snapshot (JSON nen + ma hoa) -> put_snapshot
  => snapshot ton tai thi moi mau cua no da nam trong pack da ghi xong.
  Dut giua chung: lan sau hoi lai, mau thuoc pack da ghi xong khong gui lai.

Restore: kiem tra SHA-256 ca pack truoc khi dung, giai ma + HMAC tung mau, ghi file tam roi doi
ten (khong bao gio de lai file ghi do dang mang ten that), tra lai mtime + thuoc tinh.
"""
import getpass
import hashlib
import json
import os
import platform
import secrets
import time
from collections import OrderedDict
from datetime import datetime

import zstandard

from core import FORMAT_VERSION, packer
from core.chunker import ChunkerParams, iter_chunks
from core.crypto import Keys, key_id, make_key_file, open_key_file, sha256_hex
from core.errors import Cancelled, IntegrityError, NotFound, RepoError, WrongPassword
from core.scanner import FileCache, make_matcher, scan
from shared.snapshot import long_path, root_names

CONFIG_FORMAT = "backup-system-v2"
SNAP_HEADER = b"BSV2SN\x01\x00"
QUERY_BATCH = 1000
LOCATE_BATCH = 10000
PENDING_BYTES = 32 * 1024 * 1024
PACK_CACHE = 8
_ATTR_MASK = 0x1 | 0x2 | 0x4 | 0x20 | 0x2000      # READONLY HIDDEN SYSTEM ARCHIVE NOT_CONTENT_INDEXED


def now_iso():
    # mili giay: 2 snapshot trong cung 1 giay van sap xep dung (latest)
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class _Progress:
    """Goi callback(done, total, message) toi da ~2 lan/giay."""

    def __init__(self, cb, total, interval=0.5):
        self.cb, self.total, self.done, self.interval, self.last = cb, total, 0, interval, 0.0

    def add(self, n, msg=""):
        self.done += n
        if self.cb and time.monotonic() - self.last >= self.interval:
            self.last = time.monotonic()
            self.cb(self.done, self.total, msg)

    def final(self, msg):
        if self.cb:
            self.cb(self.done, self.total, msg)


# ===================================================================== init / open

def init_repo(backend, password, params=ChunkerParams(), pack_target=packer.DEFAULT_TARGET, scrypt=None):
    """Tao kho moi: key file truoc, config sau cung (config co = kho dung duoc)."""
    try:
        backend.get_config()
        raise RepoError(f"Kho đã tồn tại: {backend.describe()}")
    except NotFound:
        pass
    cfg = {
        "format": CONFIG_FORMAT, "version": FORMAT_VERSION, "repo_id": secrets.token_hex(16),
        "created": now_iso(), "chunker": params.to_dict(), "pack_target_size": int(pack_target),
        "compression": {"algorithm": "zstd", "level": 3}, "cipher": "AES-256-GCM",
        "chunk_id": "HMAC-SHA256", "kdf": "scrypt",
    }
    keys = Keys.generate(cfg["repo_id"])
    kf = make_key_file(keys, password, scrypt=scrypt)
    backend.put_key(key_id(kf), kf)
    backend.put_config(json.dumps(cfg, indent=1).encode("utf-8"))
    return Repository(backend, keys, cfg)


class Repository:
    def __init__(self, backend, keys, cfg):
        self.backend, self.keys, self.cfg = backend, keys, cfg
        self.params = ChunkerParams.from_dict(cfg["chunker"])
        self.pack_target = int(cfg.get("pack_target_size", packer.DEFAULT_TARGET))
        self._zc = zstandard.ZstdCompressor(level=6)
        self._zd = zstandard.ZstdDecompressor()

    @classmethod
    def open(cls, backend, password):
        cfg = json.loads(backend.get_config().decode("utf-8"))
        if cfg.get("format") != CONFIG_FORMAT:
            raise RepoError("Không phải kho backup-system-v2")
        if int(cfg.get("version", 0)) > FORMAT_VERSION:
            raise RepoError(f"Kho phiên bản {cfg.get('version')} mới hơn phần mềm này ({FORMAT_VERSION})")
        kids = backend.list_keys()
        if not kids:
            raise RepoError("Kho không có key file nào")
        for kid in kids:
            try:
                keys = open_key_file(backend.get_key(kid), password)
            except WrongPassword:
                continue
            if keys.repo_id != cfg["repo_id"]:
                raise RepoError("Key file không thuộc kho này")
            return cls(backend, keys, cfg)
        raise WrongPassword("Sai mật khẩu: không mở được key file nào của kho")

    def add_password(self, new_password):
        kf = make_key_file(self.keys, new_password)
        self.backend.put_key(key_id(kf), kf)
        return key_id(kf)

    # ================================================================= snapshot
    def save_snapshot(self, snap):
        raw = json.dumps(snap, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        data = SNAP_HEADER + self.keys.seal(self._zc.compress(raw), SNAP_HEADER)
        sid = sha256_hex(data)
        self.backend.put_snapshot(sid, data)
        return sid, len(data)

    def load_snapshot(self, sid):
        data = self.backend.get_snapshot(sid)
        if sha256_hex(data) != sid:
            raise IntegrityError(f"snapshot {sid[:12]}: SHA-256 không khớp tên")
        if not data.startswith(SNAP_HEADER):
            raise IntegrityError(f"snapshot {sid[:12]}: sai header")
        z = self.keys.open(data[len(SNAP_HEADER):], SNAP_HEADER, f"snapshot {sid[:12]}")
        snap = json.loads(self._zd.decompress(z, max_output_size=512 * 1024 * 1024))
        if int(snap.get("version", 0)) > FORMAT_VERSION:
            raise RepoError("Snapshot phiên bản mới hơn phần mềm này")
        return snap

    def list_snapshots(self):
        out = []
        for s in self.backend.list_snapshots():
            try:
                snap = self.load_snapshot(s["id"])
                out.append({"id": s["id"], "time": snap["time"], "host": snap["host"], "user": snap.get("user"),
                            "sources": [r["source"] for r in snap["roots"]], "tags": snap.get("tags", []),
                            "parent": snap.get("parent"), "stats": snap.get("stats", {}), "size": s["size"]})
            except (IntegrityError, RepoError, ValueError) as e:
                out.append({"id": s["id"], "error": str(e), "time": s.get("mtime", "")})
        return sorted(out, key=lambda x: x["time"])

    def resolve(self, ref):
        snaps = [s for s in self.list_snapshots() if "error" not in s]
        if not snaps:
            raise NotFound("Kho chưa có snapshot nào")
        if ref in (None, "", "latest"):
            return snaps[-1]["id"]
        hits = [s["id"] for s in snaps if s["id"].startswith(ref.lower())]
        if len(hits) != 1:
            raise NotFound(f"Không xác định được snapshot '{ref}' ({len(hits)} kết quả)")
        return hits[0]

    def find_parent(self, host, sources, limit=50):
        """Snapshot moi nhat cung may + cung danh sach thu muc nguon (giai ma tu moi nhat, dung som)."""
        metas = sorted(self.backend.list_snapshots(), key=lambda s: s["mtime"], reverse=True)[:limit]
        best = None
        for m in metas:
            try:
                snap = self.load_snapshot(m["id"])
            except (IntegrityError, RepoError, ValueError):
                continue
            if snap.get("host") == host and [r["source"] for r in snap["roots"]] == sources:
                if best is None or snap["time"] > best[1]["time"]:
                    best = (m["id"], snap)
                break
        return best

    # ================================================================= backup
    def backup(self, paths, host=None, user=None, tags=(), parent="auto", excludes=(),
               progress=None, cancel=None):
        t0 = time.perf_counter()
        sources = [os.path.abspath(p) for p in paths]
        host, user = host or platform.node(), user or getpass.getuser()
        errors = []
        entries = list(scan(sources, make_matcher(excludes),
                            on_error=lambda p, e: errors.append({"path": p, "error": str(e)})))
        if not entries:
            raise RepoError("Không có gì để sao lưu (đường dẫn không tồn tại?)")

        parent_id, parent_snap = None, None
        if parent == "auto":
            found = self.find_parent(host, sources)
            if found:
                parent_id, parent_snap = found
        elif parent:
            parent_id = self.resolve(parent)
            parent_snap = self.load_snapshot(parent_id)
        cache = FileCache.from_snapshot(parent_snap)

        st = dict(files=0, dirs=0, bytes=0, files_cached=0, files_read=0, bytes_read=0, chunks=0,
                  chunks_new=0, bytes_new=0, packs_new=0, bytes_uploaded=0)
        prog = _Progress(progress, sum(e.size for e in entries if e.type == "file" and cache.lookup(e) is None))
        known = set()
        batch, batch_bytes = [], 0
        writer = packer.PackWriter(self.keys, self.pack_target)

        def upload_pack():
            nonlocal writer
            pid, data, _ = writer.finish()
            self.backend.put_pack(pid, data)
            st["packs_new"] += 1
            st["bytes_uploaded"] += len(data)
            writer = packer.PackWriter(self.keys, self.pack_target)

        def flush():
            nonlocal batch, batch_bytes
            query, seen = [], set()
            for cid, _ in batch:
                h = cid.hex()
                if h not in known and h not in seen:
                    seen.add(h)
                    query.append(h)
            missing = set()
            for i in range(0, len(query), QUERY_BATCH):
                missing.update(self.backend.missing_chunks(query[i:i + QUERY_BATCH]))
            for cid, data in batch:
                h = cid.hex()
                if h in known:
                    continue
                known.add(h)
                if h in missing:
                    blob = self.keys.encrypt_chunk(cid, data)
                    if writer.would_overflow(len(blob)):
                        upload_pack()
                    writer.add(cid, blob, len(data))
                    st["chunks_new"] += 1
                    st["bytes_new"] += len(data)
            batch, batch_bytes = [], 0

        tree = []
        for e in entries:
            if cancel and cancel():
                raise Cancelled()
            if e.type == "dir":
                tree.append(e.to_tree())
                st["dirs"] += 1
                continue
            cached = cache.lookup(e)
            if cached is not None:
                known.update(cached)
                tree.append(e.to_tree(list(cached)))
                st["files"] += 1
                st["files_cached"] += 1
                st["bytes"] += e.size
                st["chunks"] += len(cached)
                continue
            ids, size = [], 0
            try:
                with open(long_path(e.abs), "rb", buffering=0) as f:
                    for data in iter_chunks(f, self.params, size_hint=e.size):
                        cid = self.keys.chunk_id(data)
                        h = cid.hex()
                        ids.append(h)
                        size += len(data)
                        prog.add(len(data), e.path)
                        if h not in known:
                            batch.append((cid, data))
                            batch_bytes += len(data)
                            if len(batch) >= QUERY_BATCH or batch_bytes >= PENDING_BYTES:
                                flush()
            except OSError as err:
                errors.append({"path": e.abs, "error": str(err)})
                continue
            item = e.to_tree(ids)
            if size != e.size:
                item["size"] = size
                item["changed_during_backup"] = True
            tree.append(item)
            st["files"] += 1
            st["files_read"] += 1
            st["bytes"] += size
            st["bytes_read"] += size
            st["chunks"] += len(ids)
        flush()
        if len(writer):
            upload_pack()

        st["seconds"] = round(time.perf_counter() - t0, 3)
        snap = {
            "version": FORMAT_VERSION, "time": now_iso(), "host": host, "user": user,
            "roots": [{"name": n, "source": s} for n, s in zip(root_names(sources), sources)],
            "parent": parent_id, "tags": list(tags), "chunker": self.params.to_dict(),
            "stats": st, "tree": tree, "errors": errors[:500],
        }
        sid, snap_size = self.save_snapshot(snap)          # luon la buoc CUOI
        st["bytes_uploaded"] += snap_size
        st["seconds"] = round(time.perf_counter() - t0, 3)
        prog.final("xong")
        return {"snapshot_id": sid, "parent": parent_id, "stats": st, "errors": errors}

    # ================================================================= restore
    def restore(self, snapshot_id, target, include=None, progress=None):
        t0 = time.perf_counter()
        snap = self.load_snapshot(snapshot_id)
        tree = snap["tree"]
        if include:
            inc = include.strip("/").replace("\\", "/")
            tree = [e for e in tree if e["path"] == inc or e["path"].startswith(inc + "/")]
            if not tree:
                raise NotFound(f"Snapshot không có '{include}'")
        files = [e for e in tree if e["type"] == "file"]
        ids = list(dict.fromkeys(h for e in files for h in e["chunks"]))
        loc = {}
        for i in range(0, len(ids), LOCATE_BATCH):
            loc.update(self.backend.locate_chunks(ids[i:i + LOCATE_BATCH]))
        lost = [h for h in ids if h not in loc]
        if lost:
            raise IntegrityError(f"Kho thiếu {len(lost)} mẩu mà snapshot cần (vd {lost[0][:12]})")

        target = os.path.abspath(target)
        cache = _PackCache(self)
        prog = _Progress(progress, sum(e["size"] for e in files))
        st = {"files": 0, "dirs": 0, "bytes": 0}

        def dest_of(path):
            parts = path.split("/")
            if any(p in ("", ".", "..") or ":" in p for p in parts):
                raise IntegrityError(f"Đường dẫn không an toàn trong snapshot: {path!r}")
            return os.path.join(target, *parts)

        for e in tree:
            if e["type"] == "dir":
                os.makedirs(long_path(dest_of(e["path"])), exist_ok=True)
                st["dirs"] += 1
        for e in files:
            dest = dest_of(e["path"])
            os.makedirs(long_path(os.path.dirname(dest)), exist_ok=True)
            tmp = dest + ".bks-part"
            size = 0
            try:
                with open(long_path(tmp), "wb") as out:
                    for h in e["chunks"]:
                        data = cache.chunk(h, loc[h])
                        out.write(data)
                        size += len(data)
                        prog.add(len(data), e["path"])
                if size != e["size"]:
                    raise IntegrityError(f"{e['path']}: kích thước khôi phục {size} != {e['size']}")
                _make_writable(dest)
                os.replace(long_path(tmp), long_path(dest))
            except BaseException:
                try:
                    os.remove(long_path(tmp))
                except OSError:
                    pass
                raise
            os.utime(long_path(dest), ns=(e["mtime_ns"], e["mtime_ns"]))
            _set_attrs(dest, e.get("attrs", 0))
            st["files"] += 1
            st["bytes"] += size
        for e in reversed(tree):                 # mtime thu muc dat sau cung (ghi file lam doi mtime)
            if e["type"] == "dir":
                try:
                    os.utime(long_path(dest_of(e["path"])), ns=(e["mtime_ns"], e["mtime_ns"]))
                except OSError:
                    pass
        st.update(packs_read=cache.packs_read, bytes_downloaded=cache.bytes_read,
                  seconds=round(time.perf_counter() - t0, 3))
        prog.final("xong")
        return st

    # ================================================================= check
    def check(self, read_data=True, progress=None):
        """Kiem tra toan bo kho. Tra ve {"packs","chunks","snapshots","errors":[...]}."""
        errors, index = [], {}
        packs = self.backend.list_packs()
        for n, pid in enumerate(packs, 1):
            try:
                for e in packer.verify_pack(self.backend.get_pack(pid), pid, self.keys, read_data):
                    index.setdefault(e.id.hex(), pid)
            except (IntegrityError, RepoError) as ex:
                errors.append(f"pack {pid[:12]}: {ex}")
            if progress:
                progress(n, len(packs), f"pack {n}/{len(packs)}")
        snaps = self.backend.list_snapshots()
        for s in snaps:
            try:
                snap = self.load_snapshot(s["id"])
                lost = {h for e in snap["tree"] for h in e.get("chunks", ()) if h not in index}
                if lost:
                    errors.append(f"snapshot {s['id'][:12]}: thiếu {len(lost)} mẩu")
            except (IntegrityError, RepoError, ValueError) as ex:
                errors.append(f"snapshot {s['id'][:12]}: {ex}")
        return {"packs": len(packs), "chunks": len(index), "snapshots": len(snaps), "errors": errors}


class _PackCache:
    """LRU vai pack da kiem tra SHA-256 + giai ma index."""

    def __init__(self, repo, size=PACK_CACHE):
        self.repo, self.size = repo, size
        self._lru = OrderedDict()
        self.packs_read = self.bytes_read = 0

    def chunk(self, cid_hex, pack_id):
        item = self._lru.get(pack_id)
        if item is None:
            data = self.repo.backend.get_pack(pack_id)
            self.packs_read += 1
            self.bytes_read += len(data)
            if hashlib.sha256(data).hexdigest() != pack_id:
                raise IntegrityError(f"pack {pack_id[:12]}: SHA-256 không khớp tên (pack bị sửa/hỏng)")
            item = (data, {e.id.hex(): e for e in packer.read_index(self.repo.keys, data)})
            self._lru[pack_id] = item
            if len(self._lru) > self.size:
                self._lru.popitem(last=False)
        else:
            self._lru.move_to_end(pack_id)
        data, entries = item
        e = entries.get(cid_hex)
        if e is None:
            raise IntegrityError(f"pack {pack_id[:12]} không chứa mẩu {cid_hex[:12]}")
        return self.repo.keys.decrypt_chunk(e.id, packer.blob_of(data, e), e.raw_length)


def _make_writable(path):
    if os.name == "nt" and os.path.exists(long_path(path)):
        import ctypes
        attrs = ctypes.windll.kernel32.GetFileAttributesW(long_path(path))
        if attrs != -1 and attrs & 0x1:
            ctypes.windll.kernel32.SetFileAttributesW(long_path(path), attrs & ~0x1)


def _set_attrs(path, attrs):
    if os.name == "nt" and attrs:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(long_path(path), (attrs & _ATTR_MASK) or 0x80)
