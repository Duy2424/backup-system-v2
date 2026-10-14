"""
Quet thu muc + snapshot (manifest) + so sanh.

- scan_files(): duyet thu muc 1 lan (os.scandir), loc exclude, ho tro duong dan dai Windows.
- create_snapshot(): manifest {rel: {abs_path, size, mtime, hash}} - dung khi restore so sanh.
- compare_snapshots(): thieu / du / khac / giong.
Hash duoc tinh LUOI: file cung size + cung mtime voi ban backup thi coi la khong doi
(giong rsync "quick check"), chi bam khi can.
"""
import fnmatch
import hashlib
import os
from datetime import datetime

HASH_BUF = 1024 * 1024
_IS_WINDOWS = os.name == "nt"


def long_path(p):
    """Them tien to \\\\?\\ de vuot gioi han 260 ky tu tren Windows."""
    if not _IS_WINDOWS:
        return p
    p = os.path.abspath(p)
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def strip_long(p):
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\"):
        return p[4:]
    return p


class ExcludeMatcher:
    """So khop glob khong phan biet hoa thuong theo TEN file/thu muc (khong phai chuoi con)."""

    def __init__(self, dir_patterns=(), file_patterns=(), abs_paths=()):
        self.dirs = [p.lower() for p in dir_patterns]
        self.files = [p.lower() for p in file_patterns]
        self.abs = {os.path.normcase(os.path.abspath(p)) for p in abs_paths}

    @classmethod
    def from_config(cls, config):
        return cls(config.EXCLUDE_DIRS, config.EXCLUDE_FILES, config.exclude_abs_paths())

    def skip_dir(self, name, path=None):
        n = name.lower()
        if any(fnmatch.fnmatchcase(n, p) for p in self.dirs):
            return True
        return path is not None and os.path.normcase(strip_long(path)) in self.abs

    def skip_file(self, name):
        n = name.lower()
        return any(fnmatch.fnmatchcase(n, p) for p in self.files)


def root_names(paths):
    """Ten goc cho tung duong dan (trung ten -> them ~2, ~3) de rel path khong dung nhau."""
    seen, out = {}, []
    for p in paths:
        base = os.path.basename(os.path.normpath(p)) or os.path.splitdrive(p)[0].rstrip(":") or "root"
        n = seen.get(base.lower(), 0) + 1
        seen[base.lower()] = n
        out.append(base if n == 1 else f"{base}~{n}")
    return out


def scan_files(paths, matcher=None, on_error=None):
    """
    Sinh (rel, abs_path, stat) cho moi file thuong. rel = "<ten goc>/<duong dan con>" dang '/'.
    abs_path la duong dan binh thuong (khong co tien to \\\\?\\).
    """
    matcher = matcher or ExcludeMatcher()
    for base, name in zip(paths, root_names(paths)):
        if not os.path.exists(base):
            continue
        if os.path.isfile(base):
            try:
                yield name, os.path.abspath(base), os.stat(long_path(base))
            except OSError as e:
                if on_error:
                    on_error(base, e)
            continue
        stack = [(long_path(base), name)]
        while stack:
            d, rel_d = stack.pop()
            try:
                with os.scandir(d) as it:
                    entries = sorted(it, key=lambda e: e.name)
            except OSError as e:
                if on_error:
                    on_error(strip_long(d), e)
                continue
            subdirs = []
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if not matcher.skip_dir(e.name, e.path):
                            subdirs.append((e.path, f"{rel_d}/{e.name}"))
                    elif e.is_file(follow_symlinks=False):
                        if not matcher.skip_file(e.name):
                            yield f"{rel_d}/{e.name}", strip_long(e.path), e.stat(follow_symlinks=False)
                except OSError as err:
                    if on_error:
                        on_error(strip_long(e.path), err)
            stack.extend(reversed(subdirs))


def hash_file(path, chunk_size=HASH_BUF):
    """SHA-256 hex cua file, None neu khong doc duoc."""
    h = hashlib.sha256()
    try:
        with open(long_path(path), "rb") as f:
            for block in iter(lambda: f.read(chunk_size), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return None


def create_snapshot(paths, exclude_patterns=None, matcher=None, reference=None):
    """
    Manifest cua `paths`. `reference` (snapshot khac): file cung size + mtime voi
    reference thi lay lai hash cu, khong doc file (nhanh khi restore so sanh).
    `exclude_patterns` giu de tuong thich: danh sach glob ap cho ca file lan thu muc.
    """
    if matcher is None:
        pats = exclude_patterns or []
        matcher = ExcludeMatcher(pats, pats)
    ref_files = (reference or {}).get("files", {})
    snap = {"created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "paths": list(paths), "files": {}}
    for rel, abs_path, st in scan_files(paths, matcher):
        ref = ref_files.get(rel)
        if ref and ref.get("size") == st.st_size and _same_mtime(ref.get("mtime"), st.st_mtime):
            digest = ref.get("hash")
        else:
            digest = hash_file(abs_path)
        snap["files"][rel] = {"abs_path": abs_path, "size": st.st_size,
                              "mtime": st.st_mtime, "hash": digest}
    snap["total_files"] = len(snap["files"])
    snap["total_size"] = sum(f["size"] for f in snap["files"].values())
    return snap


def _same_mtime(a, b):
    return a is not None and abs(float(a) - float(b)) < 1e-3


def compare_snapshots(backup_snap, current_snap):
    """
    missing  : co trong backup, hien tai khong co -> them lai
    extra    : hien tai co, backup khong co        -> (tuy chon) xoa
    modified : co ca 2 nhung khac noi dung         -> ghi de
    same     : giong nhau
    """
    b, c = backup_snap["files"], current_snap["files"]
    missing = sorted(set(b) - set(c))
    extra = sorted(set(c) - set(b))
    modified, same = [], []
    for rel in sorted(set(b) & set(c)):
        if b[rel].get("size") != c[rel].get("size") or b[rel].get("hash") != c[rel].get("hash"):
            modified.append(rel)
        else:
            same.append(rel)
    return {
        "missing": missing, "extra": extra, "modified": modified, "same": same,
        "summary": {"total_backup": len(b), "total_current": len(c), "to_add": len(missing),
                    "to_delete": len(extra), "to_overwrite": len(modified), "unchanged": len(same)},
    }
