"""2a scanner: loc, thu muc rong, duong dan dai, cache theo (path, size, mtime)."""
import os

from core.scanner import FileCache, make_matcher, scan
from tests.core_helpers import write


def test_quet_loc_thu_muc_rong_va_thu_tu(tmp_path):
    r = tmp_path / "goc"
    write(r / "b.txt", b"b")
    write(r / "a" / "Báo cáo.docx", b"x")
    write(r / "a" / "~$Báo cáo.docx", b"lock")
    write(r / "__pycache__" / "x.pyc", b"x")
    write(r / "contract.docx", b"khong bi loai nham")
    (r / "rong").mkdir()
    got = [(e.type, e.path) for e in scan([str(r)])]
    assert got == [("dir", "goc"), ("file", "goc/b.txt"), ("file", "goc/contract.docx"),
                   ("dir", "goc/a"), ("dir", "goc/rong"), ("file", "goc/a/Báo cáo.docx")]
    got2 = [e.path for e in scan([str(r)], make_matcher(["*.docx"]))]
    assert "goc/contract.docx" not in got2


def test_duong_dan_dai_hon_260(tmp_path):
    deep = tmp_path / "goc" / "/".join(["thu_muc_rat_dai_" + str(i) for i in range(16)])
    write(deep / "f.txt", b"sau")
    files = [e for e in scan([str(tmp_path / "goc")]) if e.type == "file"]
    assert len(files) == 1 and len(files[0].abs) > 260 and files[0].size == 3


def test_cache_theo_size_va_mtime(tmp_path):
    r = tmp_path / "g"
    write(r / "f.txt", b"abc")
    e = next(x for x in scan([str(r)]) if x.type == "file")
    cache = FileCache([e.to_tree(["id1"])])
    assert cache.lookup(e) == ["id1"]
    os.utime(r / "f.txt", ns=(e.mtime_ns + 10 ** 9, e.mtime_ns + 10 ** 9))
    assert cache.lookup(next(x for x in scan([str(r)]) if x.type == "file")) is None
    write(r / "f.txt", b"abcd")
    os.utime(r / "f.txt", ns=(e.mtime_ns, e.mtime_ns))
    assert cache.lookup(next(x for x in scan([str(r)]) if x.type == "file")) is None
