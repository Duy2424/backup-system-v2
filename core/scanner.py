"""
Quet thu muc cho v2.

- scan(): duyet de quy (os.scandir), bo qua theo mau exclude (glob theo TEN, khong phan biet
  hoa thuong), tra ve Entry cho ca thu muc (de khoi phuc thu muc rong) lan file:
  path tuong doi dang "<ten goc>/a/b.txt", size, mtime_ns, attrs (thuoc tinh file Windows).
- Ho tro duong dan > 260 ky tu (tien to \\\\?\\).
- FileCache: tra lai danh sach chunk cua file KHONG doi (cung path + size + mtime_ns) tu snapshot
  truoc -> khong can doc lai file.
"""
import os
import stat as _stat
from dataclasses import dataclass

from shared import config
from shared.snapshot import ExcludeMatcher, long_path, root_names, strip_long


@dataclass
class Entry:
    path: str          # "<ten goc>/con/file.txt" (luon dung '/')
    type: str          # "file" | "dir"
    abs: str           # duong dan tuyet doi binh thuong (khong co \\?\)
    size: int
    mtime_ns: int
    attrs: int

    def to_tree(self, chunks=None):
        d = {"path": self.path, "type": self.type, "mtime_ns": self.mtime_ns, "attrs": self.attrs}
        if self.type == "file":
            d["size"] = self.size
            d["chunks"] = chunks if chunks is not None else []
        return d


def make_matcher(extra_patterns=()):
    """Bo loc mac dinh cua he thong + mau them (ap cho ca file lan thu muc)."""
    m = ExcludeMatcher.from_config(config)
    for p in extra_patterns:
        m.dirs.append(p.lower())
        m.files.append(p.lower())
    return m


def _entry(rel, abs_path, st, typ):
    return Entry(rel, typ, strip_long(abs_path), st.st_size if typ == "file" else 0,
                 st.st_mtime_ns, getattr(st, "st_file_attributes", 0))


def scan(paths, matcher=None, on_error=None):
    """Sinh Entry theo thu tu tat dinh (thu muc truoc noi dung cua no, ten sap xep)."""
    matcher = matcher or make_matcher()
    for base, name in zip(paths, root_names(paths)):
        lp = long_path(base)
        try:
            st = os.stat(lp)
        except OSError as e:
            if on_error:
                on_error(base, e)
            continue
        if _stat.S_ISREG(st.st_mode):
            yield _entry(name, lp, st, "file")
            continue
        yield _entry(name, lp, st, "dir")
        stack = [(lp, name)]
        while stack:
            d, rel_d = stack.pop()
            try:
                with os.scandir(d) as it:
                    items = sorted(it, key=lambda e: e.name)
            except OSError as e:
                if on_error:
                    on_error(strip_long(d), e)
                continue
            subdirs = []
            for e in items:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if not matcher.skip_dir(e.name, e.path):
                            subdirs.append(e)
                    elif e.is_file(follow_symlinks=False) and not matcher.skip_file(e.name):
                        yield _entry(f"{rel_d}/{e.name}", e.path, e.stat(follow_symlinks=False), "file")
                except OSError as err:
                    if on_error:
                        on_error(strip_long(e.path), err)
            # thu muc: yield entry roi day vao stack (dao nguoc de giu thu tu ten khi pop)
            for e in subdirs:
                try:
                    yield _entry(f"{rel_d}/{e.name}", e.path, e.stat(follow_symlinks=False), "dir")
                except OSError as err:
                    if on_error:
                        on_error(strip_long(e.path), err)
            stack.extend((e.path, f"{rel_d}/{e.name}") for e in reversed(subdirs))


class FileCache:
    """path -> (size, mtime_ns, chunks) cua snapshot truoc."""

    def __init__(self, tree=()):
        self._m = {e["path"]: e for e in tree if e.get("type") == "file"}

    @classmethod
    def from_snapshot(cls, snap):
        return cls(snap.get("tree", []) if snap else [])

    def __len__(self):
        return len(self._m)

    def match(self, entry):
        """Ban ghi cua snapshot truoc neu file khong doi (cung path + size + mtime_ns)."""
        e = self._m.get(entry.path)
        if e and e.get("size") == entry.size and e.get("mtime_ns") == entry.mtime_ns:
            return e
        return None

    def lookup(self, entry):
        e = self.match(entry)
        return e.get("chunks") if e else None
