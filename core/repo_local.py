"""
Backend kho tren thu muc local (test, che do offline, va la "loi" cua stub server tuan 3).

Bo cuc (docs/repo-format.md muc 9):
  config, keys/<key_id>, packs/<ab>/<pack_id>, snapshots/<id>, tmp/

- Ghi nguyen tu: ghi tmp/ -> fsync -> os.link sang ten that (loi neu da co => khong bao gio
  ghi de) -> xoa file tam. O dia khong ho tro hard link thi dung os.rename (Windows van loi
  neu dich da ton tai).
- Index chunk_id -> pack_id dung trong RAM bang cach doc footer + bang ID cua tung pack (khong
  can khoa, khong doc phan du lieu). Index cap nhat SAU khi pack da doi ten xong.
- Khong co ham xoa.
"""
import hashlib
import os
import secrets
from datetime import datetime
from pathlib import Path

from core import packer
from core.backend import Backend
from core.errors import IntegrityError, NotFound, RepoError

SNAP_MAGIC = b"BSV2SN\x01"
MAX_SNAPSHOT = 256 * 1024 * 1024


def _check_id(i, what="id"):
    if not packer.is_hex_id(i):
        raise RepoError(f"{what} không hợp lệ: {i!r}")
    return i


class LocalRepo(Backend):
    def __init__(self, root):
        self.root = Path(root)
        self._index = None          # chunk_id hex -> pack_id hex

    def describe(self):
        return str(self.root)

    # ------------------------------------------------------------ duong dan
    def _pack_path(self, pid):
        return self.root / "packs" / pid[:2] / pid

    def _tmp(self):
        d = self.root / "tmp"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{secrets.token_hex(8)}.tmp"

    def _write_once(self, dest, data):
        """True neu tao moi, False neu dich da co (khong ghi de)."""
        dest = Path(dest)
        if dest.exists():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._tmp()
        try:
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(tmp, dest)
            except FileExistsError:
                return False
            except OSError:
                try:
                    os.rename(tmp, dest)
                except FileExistsError:
                    return False
            return True
        finally:
            if tmp.exists():
                tmp.unlink()

    # ------------------------------------------------------------ config / key
    def exists(self):
        return (self.root / "config").is_file()

    def get_config(self):
        try:
            return (self.root / "config").read_bytes()
        except FileNotFoundError:
            raise NotFound(f"Không có kho tại {self.root} (chưa init?)") from None

    def put_config(self, data):
        p = self.root / "config"
        if self._write_once(p, data):
            return "created"
        if p.read_bytes() != data:
            raise RepoError("config đã tồn tại và khác nội dung (kho chỉ ghi một lần)")
        return "exists"

    def list_keys(self):
        d = self.root / "keys"
        return sorted(p.name for p in d.iterdir() if packer.is_hex_id(p.name)) if d.is_dir() else []

    def get_key(self, key_id):
        try:
            return (self.root / "keys" / _check_id(key_id, "key_id")).read_bytes()
        except FileNotFoundError:
            raise NotFound(f"Không có key {key_id}") from None

    def put_key(self, key_id, data):
        _check_id(key_id, "key_id")
        if hashlib.sha256(data).hexdigest() != key_id:
            raise IntegrityError("key_id không khớp SHA-256 nội dung")
        return "created" if self._write_once(self.root / "keys" / key_id, data) else "exists"

    # ------------------------------------------------------------ pack / index
    def list_packs(self):
        d = self.root / "packs"
        if not d.is_dir():
            return []
        return sorted(p.name for sub in d.iterdir() if sub.is_dir() for p in sub.iterdir()
                      if packer.is_hex_id(p.name))

    def _ids_of_pack(self, path):
        """Doc footer + bang ID (khong doc du lieu)."""
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(size - packer.FOOTER.size)
            _, n = packer.parse_footer(f.read(packer.FOOTER.size), size)
            f.seek(size - packer.FOOTER.size - packer.ID_LEN * n)
            table = f.read(packer.ID_LEN * n)
        return [table[i:i + packer.ID_LEN].hex() for i in range(0, len(table), packer.ID_LEN)]

    def _load_index(self):
        if self._index is None:
            idx = {}
            for pid in self.list_packs():
                try:
                    for cid in self._ids_of_pack(self._pack_path(pid)):
                        idx.setdefault(cid, pid)
                except (OSError, IntegrityError):
                    continue        # pack hong: check se bao, khong tinh mau cua no
            self._index = idx
        return self._index

    def missing_chunks(self, ids):
        idx = self._load_index()
        seen, out = set(), []
        for i in ids:
            _check_id(i, "chunk_id")
            if i not in idx and i not in seen:
                seen.add(i)
                out.append(i)
        return out

    def locate_chunks(self, ids):
        idx = self._load_index()
        return {i: idx[i] for i in ids if i in idx}

    def put_pack(self, pack_id, data):
        _check_id(pack_id, "pack_id")
        if hashlib.sha256(data).hexdigest() != pack_id:
            raise IntegrityError("SHA-256 của pack không khớp pack_id")
        _, _, ids = packer.parse_structure(data)
        created = self._write_once(self._pack_path(pack_id), data)
        idx = self._load_index()
        for cid in ids:
            idx.setdefault(cid.hex(), pack_id)
        return "created" if created else "exists"

    def get_pack(self, pack_id, start=None, end=None):
        p = self._pack_path(_check_id(pack_id, "pack_id"))
        try:
            with open(p, "rb") as f:
                if start is None:
                    return f.read()
                f.seek(start)
                return f.read(None if end is None else end - start)
        except FileNotFoundError:
            raise NotFound(f"Không có pack {pack_id}") from None

    def get_pack_tail(self, pack_id, n):
        p = self._pack_path(_check_id(pack_id, "pack_id"))
        try:
            with open(p, "rb") as f:
                size = f.seek(0, os.SEEK_END)
                f.seek(max(0, size - n))
                return f.read()
        except FileNotFoundError:
            raise NotFound(f"Không có pack {pack_id}") from None

    # ------------------------------------------------------------ snapshot
    def put_snapshot(self, snapshot_id, data):
        _check_id(snapshot_id, "snapshot_id")
        if len(data) > MAX_SNAPSHOT or not data.startswith(SNAP_MAGIC):
            raise IntegrityError("snapshot không hợp lệ")
        if hashlib.sha256(data).hexdigest() != snapshot_id:
            raise IntegrityError("SHA-256 của snapshot không khớp snapshot_id")
        return "created" if self._write_once(self.root / "snapshots" / snapshot_id, data) else "exists"

    def get_snapshot(self, snapshot_id):
        try:
            return (self.root / "snapshots" / _check_id(snapshot_id, "snapshot_id")).read_bytes()
        except FileNotFoundError:
            raise NotFound(f"Không có snapshot {snapshot_id}") from None

    def list_snapshots(self):
        d = self.root / "snapshots"
        if not d.is_dir():
            return []
        out = []
        for p in d.iterdir():
            if packer.is_hex_id(p.name):
                st = p.stat()
                out.append({"id": p.name, "size": st.st_size,
                            "mtime": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds")})
        return sorted(out, key=lambda s: s["mtime"])
